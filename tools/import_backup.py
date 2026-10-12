"""Import your own data (status, notes, Highlight) from a backup file into the local app.

    python tools/import_backup.py <file.json>            -> show what would be imported
    python tools/import_backup.py <file.json> --apply    -> import it (stop the local program first)

Accepts the page's「导出备份」file ({"format": "expo-compass-backup", "collections": {...}}) and the
export Claude makes from the online version (same shape). Only `plans` and `settings` are taken from it;
the fair catalogue always comes from catalog/fairs.json (run tools/update_catalog.py for that).
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'expo.json'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
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
    print(f'状态和笔记：{len(plans)} 条；Highlight 设置：{"有" if settings.get("prefs") else "没有"}')
    if unknown:
        print(f'注意：{len(unknown)} 条对应的展会不在本地目录里（仍会导入，展会补进目录后就能看到）：{", ".join(unknown)}')
    if '--apply' not in sys.argv:
        print('\n这只是预览。先关掉本地程序，再加 --apply 执行。')
        return
    if DATA.exists():
        backup = DATA.parent / 'backups' / f'expo-before-import-{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(DATA, backup)
        print(f'已备份：{backup}')
    cols['plans'] = {**cols.get('plans', {}), **plans}
    if settings:
        cols['settings'] = {**cols.get('settings', {}), **settings}
    data['savedAt'] = datetime.datetime.now().isoformat(timespec='seconds')
    tmp = DATA.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(DATA)
    print(f'已写入 {DATA}')


if __name__ == '__main__':
    main()
