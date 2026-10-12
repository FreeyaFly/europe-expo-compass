"""Which language the command-line tools speak: Chinese (zh) or English (en).

Order: a `--lang zh|en` argument, then the EXPO_LANG environment variable, then the language chosen in the app
(settings/prefs.lang in data/expo.json), then the system language (Chinese Windows -> zh, anything else -> en).
"""
import json
import locale
import os
import sys
from pathlib import Path

LANGS = ('zh', 'en')


def _system_lang():
    try:  # Windows: the UI language of the signed-in user (0x04 is the Chinese primary language id)
        import ctypes
        if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04:
            return 'zh'
        return 'en'
    except (AttributeError, OSError):
        pass
    name = (locale.getlocale()[0] or os.environ.get('LANG', '')).lower()
    return 'zh' if name.startswith('zh') or 'chinese' in name else 'en'


def pick(argv=None, data_file=None):
    argv = sys.argv[1:] if argv is None else argv
    for i, a in enumerate(argv):
        if a.startswith('--lang='):
            v = a.split('=', 1)[1]
        elif a == '--lang' and i + 1 < len(argv):
            v = argv[i + 1]
        else:
            continue
        if v in LANGS:
            return v
    if os.environ.get('EXPO_LANG') in LANGS:
        return os.environ['EXPO_LANG']
    if data_file and Path(data_file).exists():
        try:
            prefs = json.loads(Path(data_file).read_text(encoding='utf-8')).get('collections', {}).get('settings', {}).get('prefs', {})
            if prefs.get('lang') in LANGS:
                return prefs['lang']
        except (ValueError, OSError):
            pass
    return _system_lang()


def strip_lang_args(argv):
    """argv without --lang and its value, for tools that read positional arguments."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
        elif a == '--lang':
            skip = True
        elif not a.startswith('--lang='):
            out.append(a)
    return out
