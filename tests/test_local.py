"""End-to-end test of the local version, on a throw-away copy of the data.

    python tests/test_local.py

Builds app/test.html, starts server.py --test on port 8796 with a temp data folder holding the
current catalogue, opens the test page in headless Edge and prints the PASS/FAIL report.
Your real data (data/expo.json) is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_CANDIDATES = [
    Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
    Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
    Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Edge/Application/msedge.exe',
]


def find_edge():
    for p in EDGE_CANDIDATES:
        if p.is_file():
            return str(p)
    found = shutil.which('msedge')
    if found:
        return found
    sys.exit('Microsoft Edge was not found. Install Edge, or add msedge.exe to PATH, then run the test again.')


PORT = 8796


def main():
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'build.py'), '--test'], check=True)
    catalog = json.loads((ROOT / 'catalog' / 'fairs.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as tmp:
        data = {'format': 1, 'collections': {'fairs': {f['id']: f for f in catalog['fairs']}, 'meta': {'catalog': catalog['meta']}}}
        (Path(tmp) / 'expo.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        server = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--test', '--port', str(PORT), '--data', tmp])
        try:
            time.sleep(1.5)
            subprocess.run([find_edge(), '--headless=new', '--disable-gpu', f'--user-data-dir={tmp}\\edge',
                            '--virtual-time-budget=20000', '--dump-dom', f'http://127.0.0.1:{PORT}/test.html'],
                           capture_output=True, timeout=120)
            result = Path(tmp) / 'test-result.txt'
            for _ in range(50):
                if result.exists():
                    break
                time.sleep(0.2)
            report = result.read_text(encoding='utf-8') if result.exists() else 'FAIL no test report (page did not finish)'
        finally:
            server.terminate()
            server.wait()
    print(report)
    fails = report.count('FAIL')
    print(f'\n{report.count("PASS")} passed, {fails} failed')
    (ROOT / 'tests' / 'result.txt').write_text(report, encoding='utf-8')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
