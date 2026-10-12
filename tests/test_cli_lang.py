"""Offline checks for the command-line tools' two languages (no network).

    python tests/test_cli_lang.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))
import check_updates  # noqa: E402
import cli_lang  # noqa: E402
import import_backup  # noqa: E402
import server  # noqa: E402
import update_catalog  # noqa: E402

CJK = re.compile('[　-鿿＀-￯]')
results = []


def ok(cond, msg):
    results.append(('PASS ' if cond else 'FAIL ') + msg)


def strings(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, str):
        yield v


def keys(v, prefix=''):
    out = set()
    for k, x in v.items():
        out.add(prefix + k)
        if isinstance(x, dict):
            out |= keys(x, prefix + k + '.')
    return out


# 1. every tool has the same message keys in both languages, and no Chinese in English
for name, mod in [('update_catalog', update_catalog), ('check_updates', check_updates),
                  ('import_backup', import_backup), ('server', server)]:
    ok(keys(mod.MSG['zh']) == keys(mod.MSG['en']), f'{name}: zh and en have the same messages')
    ok(not any(CJK.search(s) for s in strings(mod.MSG['en'])), f'{name}: English messages have no Chinese')

# 2. the order in which the language is chosen
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / 'expo.json'
    data.write_text(json.dumps({'collections': {'settings': {'prefs': {'lang': 'en'}}}}), encoding='utf-8')
    env_before = os.environ.pop('EXPO_LANG', None)
    ok(cli_lang.pick(['--lang', 'zh'], data) == 'zh', '--lang wins')
    ok(cli_lang.pick(['--lang=zh'], data) == 'zh', '--lang=zh form')
    os.environ['EXPO_LANG'] = 'zh'
    ok(cli_lang.pick([], data) == 'zh', 'EXPO_LANG comes next')
    del os.environ['EXPO_LANG']
    ok(cli_lang.pick([], data) == 'en', "then the app's own choice")
    data.write_text(json.dumps({'collections': {}}), encoding='utf-8')
    ok(cli_lang.pick([], data) in cli_lang.LANGS, 'then the system language')
    if env_before is not None:
        os.environ['EXPO_LANG'] = env_before
ok(cli_lang.strip_lang_args(['a.json', '--lang', 'en', '--apply']) == ['a.json', '--apply'], 'strip --lang from arguments')

# 3. a real run of update_catalog in each language (preview only: reads, never writes)
for lang in cli_lang.LANGS:
    out = subprocess.run([sys.executable, str(ROOT / 'tools' / 'update_catalog.py'), '--lang', lang],
                         capture_output=True, text=True, encoding='utf-8').stdout
    if lang == 'en':
        ok(out.startswith('Catalogue:') and not CJK.search(out), 'update_catalog preview in English')
    else:
        ok(out.startswith('目录：'), 'update_catalog preview in Chinese')

print('\n'.join(results))
fails = sum(r.startswith('FAIL') for r in results)
print(f'\n{len(results) - fails} passed, {fails} failed')
sys.exit(1 if fails else 0)
