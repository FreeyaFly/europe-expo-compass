"""Merge catalog/fairs.json (the fair catalogue Claude maintains) into the app's data.

    python tools/update_catalog.py            -> check the catalogue and show what would change
    python tools/update_catalog.py --apply    -> apply it
    --lang zh|en                              -> message language (default: the app's language, then the system's)

Only the `fairs` collection and `meta/catalog` are touched. Your own data (`plans`: status, priority,
notes; `settings`: Highlight) is never changed.
Rules:
- a fair id never changes once created (your notes hang on it); a renamed fair keeps its id
- a fair that disappeared from the catalogue is removed, except when you wrote a status or note for it:
  then it stays and is reported
- if the local program is running, changes go through it (otherwise it would overwrite the file
  with its own copy on the next save); if not, the data file is written directly, with a backup first
"""
import datetime
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import cli_lang

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'catalog' / 'fairs.json'
DATA = ROOT / 'data' / 'expo.json'
PORT = int(os.environ.get('EXPO_PORT', 8766))

INDUSTRIES = {'tech', 'telecom', 'finance', 'energy', 'industry', 'logistics', 'health', 'food', 'build', 'auto',
              'fashion', 'sport', 'maritime', 'retail', 'policy', 'media'}
COUNTRIES = {'NL', 'BE', 'DE', 'FR', 'GB', 'ES', 'IT', 'CH', 'AT', 'DK', 'SE', 'FI', 'NO', 'IS', 'IE', 'PT', 'PL', 'CZ',
             'LU', 'HU', 'GR', 'RO', 'BG', 'HR', 'SI', 'SK', 'EE', 'LV', 'LT', 'CY', 'MT'}
CJK = re.compile('[\u3000-\u9fff\uff00-\uffef]')
TEXT_FIELDS = ['name', 'highlight', 'ticket', 'venue', 'exhibitors', 'visitors', 'language']
REQUIRED = ['id', 'name', 'start', 'end', 'city', 'country', 'venue', 'url', 'industries', 'type', 'scale', 'audience',
            'verify', 'verifiedAt', 'sourceUrl', 'series', 'cycle', 'eventStatus', 'scaleBasis', 'schemaVersion']
ENUMS = {'type': {'trade', 'conf', 'expoconf'}, 'scale': {'flagship', 'large', 'medium', 'boutique'},
         'audience': {'trade', 'mixed'}, 'verify': {'official', 'aggregator'},
         'cycle': {'annual', 'biennial', 'semiannual', 'irregular'},
         'eventStatus': {'scheduled', 'postponed', 'cancelled', 'rescheduled'}, 'scaleBasis': {'figures', 'reputation'}}


def check(catalog):
    errors, ids = [], set()
    for f in catalog['fairs']:
        fid = f.get('id', '?')
        for k in REQUIRED:
            if k not in f:
                errors.append(f'{fid}: missing {k}')
        if fid in ids:
            errors.append(f'{fid}: duplicate id')
        ids.add(fid)
        if f.get('start', '') > f.get('end', ''):
            errors.append(f'{fid}: start after end')
        if not set(f.get('industries', [])) <= INDUSTRIES:
            errors.append(f'{fid}: unknown industry {set(f["industries"]) - INDUSTRIES}')
        if f.get('country') not in COUNTRIES:
            errors.append(f'{fid}: unknown country {f.get("country")}')
        for k, ok in ENUMS.items():
            if k in f and f[k] not in ok:
                errors.append(f'{fid}: {k}={f[k]!r} not one of {sorted(ok)}')
        if any(ord(c) >= 0x3000 for c in f.get('city', '')):
            errors.append(f'{fid}: city must be in English')
        for d in f.get('deadlines', []):
            if not {'label', 'date'} <= set(d):
                errors.append(f'{fid}: deadline needs label and date')
        # every Chinese text needs an English version in `en`, so the English UI never shows Chinese
        en = f.get('en')
        if not isinstance(en, dict):
            errors.append(f'{fid}: missing en (English texts)')
            continue
        for k in TEXT_FIELDS:
            v = f.get(k)
            if isinstance(v, str) and CJK.search(v):
                if not en.get(k):
                    errors.append(f'{fid}: {k} is Chinese but en.{k} is missing')
                elif CJK.search(en[k]):
                    errors.append(f'{fid}: en.{k} still contains Chinese')
        labels = [d.get('label', '') for d in f.get('deadlines', [])]
        if any(CJK.search(x) for x in labels):
            en_labels = en.get('deadlines') or []
            if len(en_labels) != len(labels) or any(CJK.search(x) for x in en_labels):
                errors.append(f'{fid}: en.deadlines must give one English label per deadline')
    return errors


def server_state():
    """'none' (nothing running), 'ours' (the local program of THIS folder) or 'other' (another copy, or an
    older version that does not say which data file it serves)."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/ping', timeout=2) as r:
            info = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return 'none'
    if info.get('app') != 'expo-compass':
        return 'other'
    served = info.get('data')
    return 'ours' if served and Path(served).resolve() == DATA.resolve() else 'other'


def send(method, col, doc_id, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/doc/{col}/{urllib.parse.quote(doc_id)}', data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


STOP_CMD = 'Get-NetTCPConnection -LocalPort {port} -State Listen | ForEach-Object {{ Stop-Process -Id $_.OwningProcess }}'
MSG = {
    'zh': {
        'invalid': '目录有问题，没有做任何修改：',
        'catalog': '目录：{n} 场（{date}）',
        'added': '新增 {n}', 'changed': '修改 {n}', 'removed': '删除 {n}', 'colon': '：',
        'kept': '目录里已经没有、但你写过状态或笔记，所以保留 {n}：',
        'preview': '\n这只是预览。确认无误后加 --apply 执行。',
        'other': '\n端口 {port} 上运行的是另一份 Expo Compass（不是这个文件夹的），或者是旧版本的本地程序。\n'
                 '为了不写错地方，这次没有做任何修改。请先在 PowerShell 里运行下面这条命令，关掉占用这个端口的本地程序，再重新运行：\n  ',
        'via_server': '已通过正在运行的本地程序更新。', 'backup': '已备份：{p}', 'written': '已写入 {p}',
    },
    'en': {
        'invalid': 'The catalogue has problems; nothing was changed:',
        'catalog': 'Catalogue: {n} fairs ({date})',
        'added': 'Added {n}', 'changed': 'Changed {n}', 'removed': 'Removed {n}', 'colon': ': ',
        'kept': 'No longer in the catalogue but kept, because you wrote a status or note for them ({n}): ',
        'preview': '\nThis is only a preview. Add --apply to make the change.',
        'other': '\nAnother copy of Expo Compass (not this folder), or an older version of the local program, is running on port {port}.\n'
                 'To avoid writing to the wrong place, nothing was changed. Run this command in PowerShell to stop the program on that port, then try again:\n  ',
        'via_server': 'Updated through the running local program.', 'backup': 'Backup: {p}', 'written': 'Written to {p}',
    },
}


def main():
    apply = '--apply' in sys.argv
    m = MSG[cli_lang.pick(data_file=DATA)]
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    errors = check(catalog)
    if errors:
        print(m['invalid'])
        print('\n'.join('  ' + e for e in errors))
        sys.exit(1)
    data = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {'format': 1, 'collections': {}}
    cols = data.setdefault('collections', {})
    old, plans = cols.get('fairs', {}), cols.get('plans', {})
    new = {f['id']: {k: v for k, v in f.items() if k != 'id'} | {'id': f['id']} for f in catalog['fairs']}

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    kept = [i for i in removed if plans.get(i)]
    removed = [i for i in removed if i not in kept]
    changed = {}
    for i in sorted(set(new) & set(old)):
        diff = sorted(k for k in set(new[i]) | set(old[i]) if new[i].get(k) != old[i].get(k))
        if diff:
            changed[i] = diff
    print(m['catalog'].format(n=len(new), date=catalog.get('meta', {}).get('updatedAt', '?')))
    print(m['added'].format(n=len(added)) + (m['colon'] + ', '.join(added) if added else ''))
    print(m['changed'].format(n=len(changed)) + (m['colon'] + '; '.join(f'{i} ({", ".join(d)})' for i, d in changed.items()) if changed else ''))
    print(m['removed'].format(n=len(removed)) + (m['colon'] + ', '.join(removed) if removed else ''))
    if kept:
        print(m['kept'].format(n=len(kept)) + ', '.join(kept))
    if not apply:
        print(m['preview'])
        return
    meta = catalog.get('meta', {})
    state = server_state()
    if state == 'other':
        print(m['other'].format(port=PORT) + STOP_CMD.format(port=PORT))
        sys.exit(1)
    if state == 'ours':
        for i in added + list(changed):
            send('PUT', 'fairs', i, new[i])
        for i in removed:
            send('DELETE', 'fairs', i)
        if meta:
            send('PUT', 'meta', 'catalog', meta)
        print(m['via_server'])
    else:
        if DATA.exists():
            backup = DATA.parent / 'backups' / f'expo-before-catalog-{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(DATA, backup)
            print(m['backup'].format(p=backup))
        cols['fairs'] = {i: v for i, v in old.items() if i not in removed} | {i: new[i] for i in added + list(changed)}
        if meta:
            cols.setdefault('meta', {})['catalog'] = meta
        data['savedAt'] = datetime.datetime.now().isoformat(timespec='seconds')
        DATA.parent.mkdir(exist_ok=True)
        tmp = DATA.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(DATA)
        print(m['written'].format(p=DATA))


if __name__ == '__main__':
    main()
