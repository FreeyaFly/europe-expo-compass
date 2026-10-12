"""Europe Expo Compass · 本地程序

只在本机 127.0.0.1 上运行：提供展会页面，并把数据保存在 data/expo.json。
每天第一次修改前，自动把当天的数据复制一份到 data/backups/（保留最近 30 天）。

用法：双击「启动 Expo Compass.bat」即可；也可以手动运行
    python server.py [--port 8766] [--data 数据文件夹]
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
NAME_RE = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')                  # collection names
ID_RE = re.compile(r'^(?!\.\.?$)[A-Za-z0-9_\-.~:@+]{1,200}$')    # same rule as the page
MAX_BODY = 5 * 1024 * 1024
KEEP_BACKUPS = 30


class Store:
    """All collections in one JSON file: {"format": 1, "savedAt": ..., "collections": {col: {id: doc}}}."""

    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.file = data_dir / 'expo.json'
        self.backups = data_dir / 'backups'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.backups.mkdir(exist_ok=True)
        if self.file.exists():
            with open(self.file, encoding='utf-8') as f:
                self.collections = json.load(f).get('collections', {})
        else:
            self.collections = {}
            self._write()

    def _backup_today(self):
        today = datetime.date.today().isoformat()
        target = self.backups / f'expo-{today}.json'
        if self.file.exists() and not target.exists():
            shutil.copy2(self.file, target)
            old = sorted(self.backups.glob('expo-*.json'))
            for f in old[:-KEEP_BACKUPS]:
                f.unlink()

    def _write(self):
        payload = {'format': 1, 'savedAt': datetime.datetime.now().isoformat(timespec='seconds'), 'collections': self.collections}
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix='.expo-', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)  # atomic: the file is never half-written

    def change(self, method, col, doc_id, body):
        self._backup_today()
        docs = self.collections.setdefault(col, {})
        if method == 'PUT':
            docs[doc_id] = body
        elif method == 'PATCH':
            if doc_id not in docs:
                raise KeyError(doc_id)
            merge(docs[doc_id], body)
        elif method == 'DELETE':
            docs.pop(doc_id, None)
        self._write()


def merge(target, patch):
    """Same rule as the page's store: nested objects merge, everything else (arrays included) replaces."""
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            merge(target[k], v)
        else:
            target[k] = v


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    port = 8766
    test_mode = False  # --test: the browser test posts its PASS/FAIL report to /api/test-result

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body=b'', ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self):
        """Reads and writes are only accepted from the page itself, never from other websites."""
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.port}', f'http://localhost:{self.port}'}
        if origin is not None and origin not in allowed:
            return False
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/ping':
            # `data` lets tools/update_catalog.py tell this copy apart from another Expo Compass folder
            return self._send(200, {'ok': True, 'app': 'expo-compass', 'data': str(self.store.file.resolve())})
        if path == '/api/data':
            if not self._same_origin():
                return self._send(403, {'error': 'forbidden'})
            return self._send(200, {'collections': self.store.collections})
        name = 'index.html' if path in ('/', '/index.html') else path.lstrip('/')
        types = {'html': 'text/html; charset=utf-8', 'png': 'image/png', 'ico': 'image/x-icon',
                 'webmanifest': 'application/manifest+json; charset=utf-8'}
        m = re.fullmatch(r'[A-Za-z0-9_\-]+\.(html|png|ico|webmanifest)', name)
        f = APP / name
        if not m or not f.is_file():
            return self._send(404, {'error': 'not found'})
        return self._send(200, f.read_bytes(), types[m.group(1)])

    def _doc_request(self, method):
        if not self._same_origin():
            return self._send(403, {'error': 'forbidden'})
        m = re.fullmatch(r'/api/doc/([^/]+)/([^/]+)', urlparse(self.path).path)
        if not m:
            return self._send(404, {'error': 'not found'})
        col, doc_id = unquote(m.group(1)), unquote(m.group(2))
        if not NAME_RE.match(col) or not ID_RE.match(doc_id):
            return self._send(400, {'error': 'bad collection or id'})
        body = None
        if method in ('PUT', 'PATCH'):
            n = int(self.headers.get('Content-Length') or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {'error': 'bad body size'})
            try:
                body = json.loads(self.rfile.read(n).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {'error': 'body is not JSON'})
            if not isinstance(body, dict):
                return self._send(400, {'error': 'body must be an object'})
        try:
            self.store.change(method, col, doc_id, body)
        except KeyError:
            return self._send(404, {'error': 'document does not exist'})
        except OSError as e:
            return self._send(500, {'error': f'could not save: {e}'})
        return self._send(200, {'ok': True})

    def do_POST(self):
        if self.test_mode and urlparse(self.path).path == '/api/test-result' and self._same_origin():
            n = int(self.headers.get('Content-Length') or 0)
            (self.store.dir / 'test-result.txt').write_bytes(self.rfile.read(min(n, MAX_BODY)))
            return self._send(200, {'ok': True})
        return self._send(404, {'error': 'not found'})

    def do_PUT(self):
        self._doc_request('PUT')

    def do_PATCH(self):
        self._doc_request('PATCH')

    def do_DELETE(self):
        self._doc_request('DELETE')


def main():
    ap = argparse.ArgumentParser(description='Europe Expo Compass 本地程序')
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--data', default=str(ROOT / 'data'))
    ap.add_argument('--test', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()
    Handler.test_mode = args.test
    Handler.store = Store(Path(args.data))
    Handler.port = args.port
    try:
        server = HTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        print(f'端口 {args.port} 已被占用：Expo Compass 可能已经在运行。', file=sys.stderr)
        sys.exit(1)
    print(f'Expo Compass 正在运行：http://127.0.0.1:{args.port}/   数据：{Handler.store.file}')
    server.serve_forever()


if __name__ == '__main__':
    main()
