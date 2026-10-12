"""Import your own data (status, notes, Highlight, language) from a backup file into the local app.

    python tools/import_backup.py <file.json>            -> show what would be imported
    python tools/import_backup.py <file.json> --apply    -> import it (stop the local program first)
    --lang zh|en                                         -> message language (default: the app's, then the system's)

Accepts the file from the page's "Export backup" button ({"format": "expo-compass-backup", "collections": {...}}).
Only `plans` and `settings` are taken from it; the fair catalogue always comes from catalog/fairs.json
(run tools/update_catalog.py for that).
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

import cli_lang

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'expo.json'

MSG = {
    'zh': {
        'summary': '状态和笔记：{n} 条；Highlight 和语言设置：{s}', 'yes': '有', 'no': '没有',
        'unknown': '注意：{n} 条对应的展会不在本地目录里（仍会导入，展会补进目录后就能看到）：',
        'preview': '\n这只是预览。先关掉本地程序，再加 --apply 执行。',
        'backup': '已备份：{p}', 'written': '已写入 {p}',
    },
    'en': {
        'summary': 'Status and notes: {n}; Highlight and language settings: {s}', 'yes': 'yes', 'no': 'no',
        'unknown': 'Note: {n} of them belong to fairs that are not in the local catalogue (they are imported anyway and appear once the fair is added): ',
        'preview': '\nThis is only a preview. Stop the local program first, then add --apply.',
        'backup': 'Backup: {p}', 'written': 'Written to {p}',
    },
}


def main():
    args = [a for a in cli_lang.strip_lang_args(sys.argv[1:]) if not a.startswith('--')]
    m = MSG[cli_lang.pick(data_file=DATA)]
    if not args:
        print(__doc__)
        sys.exit(1)
    src = json.loads(Path(args[0]).read_text(encoding='utf-8'))
    incoming = src.get('collections', {})
    data = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {'format': 1, 'collections': {}}
    cols = data.setdefault('collections', {})
    fairs = cols.get('fairs', {})
    plans = incoming.get('plans', {}) or {}
    settings = incoming.get('settings', {}) or {}
    unknown = [i for i in plans if i not in fairs]
    print(m['summary'].format(n=len(plans), s=m['yes'] if settings.get('prefs') else m['no']))
    if unknown:
        print(m['unknown'].format(n=len(unknown)) + ', '.join(unknown))
    if '--apply' not in sys.argv:
        print(m['preview'])
        return
    if DATA.exists():
        backup = DATA.parent / 'backups' / f'expo-before-import-{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(DATA, backup)
        print(m['backup'].format(p=backup))
    cols['plans'] = {**cols.get('plans', {}), **plans}
    if settings:
        cols['settings'] = {**cols.get('settings', {}), **settings}
    data['savedAt'] = datetime.datetime.now().isoformat(timespec='seconds')
    tmp = DATA.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(DATA)
    print(m['written'].format(p=DATA))


if __name__ == '__main__':
    main()
