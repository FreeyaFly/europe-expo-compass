"""Build the local Expo Compass page from the shared source.

    python tools/build.py          -> app/index.html
    python tools/build.py --test   -> also app/test.html (page + tests/test.js)

src/expo-compass.html is the one source of the page (the Claude version was published from it as is).
The local build adds the local data layer (src/local-store.js), drops the web fonts (the app works
offline) and switches to fonts that ship with Windows.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'

LOCAL_FONTS = """<style id="local-fonts">
/* local build: Windows system fonts instead of Google Fonts, so the app works without internet */
:root{--f-display:"Bahnschrift","Arial Narrow",sans-serif;--f-body:"Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;--f-mono:Consolas,"Cascadia Mono",monospace}
.brand h1,.badge,.month h2,.scale,.drawer h2,.stat b,.tl-months span{font-stretch:condensed}
</style>
<link rel="icon" href="icon.ico">
"""


def rep(s, old, new):
    assert s.count(old) == 1, f'expected exactly one match for: {old[:80]}'
    return s.replace(old, new)


def build(test=False):
    page = (SRC / 'expo-compass.html').read_text(encoding='utf-8')
    local = (SRC / 'local-store.js').read_text(encoding='utf-8')
    for line in ['<link rel="preconnect" href="https://fonts.googleapis.com">\n',
                 '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n']:
        page = rep(page, line, '')
    start = page.index('<link rel="stylesheet" href="https://fonts.googleapis.com')
    end = page.index('>', start) + 1
    page = page[:start] + page[end:]
    page = page.replace('</style>\n', '</style>\n' + LOCAL_FONTS, 1)  # right after the page's own styles
    page = rep(page, '<script>\n', f'<script>\n{local}\n</script>\n<script>\n')
    doc = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
          '<style>[hidden]{display:none!important}body{margin:0}</style></head><body>\n'
    (ROOT / 'app' / 'index.html').write_text(doc + page + '\n</body></html>\n', encoding='utf-8')
    print('built app/index.html')
    if test:
        tests = (ROOT / 'tests' / 'test.js').read_text(encoding='utf-8')
        (ROOT / 'app' / 'test.html').write_text(doc + page + f'\n<script>\n{tests}\n</script>\n</body></html>\n', encoding='utf-8')
        print('built app/test.html')


if __name__ == '__main__':
    build(test='--test' in sys.argv)
