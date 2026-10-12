"""Check the fair catalogue against the organisers' own websites, without Claude.

    python tools/check_updates.py              -> check every fair that has not ended yet, plus recently ended ones
    python tools/check_updates.py --soon 60    -> only fairs starting in the next 60 days
    python tools/check_updates.py --limit 10   -> only the first 10 (quick try)

For each fair it opens the official page and reports:
  确认      the stored start and end dates are on the page
  需人工看  the page opened but the stored dates were not found (date changed, or the page shows them only
            after JavaScript runs)
  下一届    the fair has ended and the page mentions dates in a later year
  打不开    the page could not be opened (blocked, timeout, error)
The report is written to reports/check-<date>.md. Nothing in the catalogue or your data is changed:
reading web pages can go wrong, so every finding is a hint for a person to confirm on the official site.
"""
import argparse
import concurrent.futures as cf
import datetime
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'catalog' / 'fairs.json'
DATA = ROOT / 'data' / 'expo.json'
REPORTS = ROOT / 'reports'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36 Edg/124.0')

# Month names in the languages the fairs' sites use; inflected forms are matched by prefix.
MONTHS = {
    1: 'jan january januar januari janvier gennaio enero tammik',
    2: 'feb february februar februari février fevrier febbraio febrero helmik',
    3: 'mar march märz maerz mrz maart mars marzo marts maalisk',
    4: 'apr april avril aprile abril huhtik',
    5: 'may mai mei maggio mayo maj toukok',
    6: 'jun june juni juin giugno junio kesäk',
    7: 'jul july juli juillet luglio julio heinäk',
    8: 'aug august augustus augusti août aout agosto elok',
    9: 'sep sept september septembre settembre septiembre syysk',
    10: 'oct october oktober octobre ottobre octubre lokak',
    11: 'nov november novembre noviembre marrask',
    12: 'dec december dezember décembre decembre dicembre diciembre jouluk',
}
MONTH_RE = {m: '(?:' + '|'.join(re.escape(w) for w in words.split()) + r')[a-zäöé]*\.?' for m, words in MONTHS.items()}
# what can sit between two day numbers of a range: dashes, &, |, •, "and" in several languages, "au", "bis"…
SEP = r'\s*(?:[-–—&|•·/,+]+|et|and|und|y|e|en|og|och|ja|to|bis|au|al|t/m|tot|till|hasta|through)\s*'
ORD = r'\.?(?:er|st|nd|rd|th|e)?'  # 1er, 1st, 17., 17e


def fetch(url, timeout=20):
    """Return (text, error). Text keeps visible words plus JSON-LD (many sites put event dates there)."""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept-Language': 'en,de;q=0.8,fr;q=0.6,nl;q=0.5',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Upgrade-Insecure-Requests': '1'})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            raw = r.read(3_000_000).decode(r.headers.get_content_charset() or 'utf-8', errors='ignore')
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}'
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, type(e).__name__ + (f': {e.reason}' if hasattr(e, 'reason') else '')
    jsonld = ' '.join(re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', raw, re.S | re.I))
    body = re.sub(r'<(script|style|noscript)\b.*?</\1>', ' ', raw, flags=re.S | re.I)
    body = re.sub(r'<[^>]+>', ' ', body)
    text = html.unescape(body + ' ' + jsonld)
    return re.sub(r'\s+', ' ', text), None


def date_hits(text, d: datetime.date):
    """Places where this calendar date appears, in the common European ways of writing it."""
    day, mon, yr = d.day, d.month, d.year
    D = rf'(?<!\d)0?{day}(?!\d)'
    pats = [
        rf'{yr}-0?{mon}-0?{day}(?!\d)',                                   # 2026-11-17 (also JSON-LD)
        rf'{D}\.?\s*[./-]\s*0?{mon}\s*[./-]\s*(?:{yr}|{yr % 100})(?!\d)',   # 17.11.2026, 17/11/26
        rf'{D}\.?(?:\s*[-–—/&]+\s*\d{{1,2}}\.?)?\s*[./]\s*0?{mon}(?:[./]|(?!\d))',   # 17.–19.11. / 21 ––– 25/10
        rf'\d{{1,2}}\.?\s*[-–—&]+\s*{D}\s*[./]\s*0?{mon}(?!\d)',               # 21 ––– 25/10 (end day)
        # 17–19 November · 17 au 19 novembre · 24 & 25 November · 24 | 25 | 26 novembre · 14•20 June · 29 et 30 septembre
        rf'{D}{ORD}(?:{SEP}\d{{1,2}}{ORD}){{0,3}}\s*(?:de\s+)?{MONTH_RE[mon]}',
        rf'(?:\d{{1,2}}{ORD}{SEP}){{1,3}}{D}{ORD}\s*(?:de\s+)?{MONTH_RE[mon]}',   # same, matching the end day
        rf'{MONTH_RE[mon]}\s*(?:\d{{1,2}}{SEP})?{D}(?!\d)',                    # Nov 17, November 17–19
        rf'{MONTH_RE[mon]}\s*(?:\d{{1,2}}{SEP}){{1,3}}{D}(?!\d)',             # November 15-17 (end day)
    ]
    out = []
    for p in pats:
        for m in re.finditer(p, text, re.I):
            near = text[max(0, m.start() - 60): m.end() + 60]
            out.append((m.start(), str(yr) in near or f"'{yr % 100}" in near or bool(re.match(rf'{yr}', m.group()))))
    return out


def snippet(text, pos, width=70):
    return '…' + text[max(0, pos - width): pos + width].strip() + '…'


def check_fair(f, text, err, today):
    start, end = datetime.date.fromisoformat(f['start']), datetime.date.fromisoformat(f['end'])
    if err:
        return 'blocked', err, ''
    if end < today:
        later = [m for y in (end.year + 1, end.year + 2)
                 for m in re.finditer(rf'(?:{"|".join(MONTH_RE.values())})[^.]{{0,25}}{y}|{y}-\d\d-\d\d|\d{{1,2}}[./]\d{{1,2}}[./]{y}', text, re.I)]
        return ('next', '页面上有更晚年份的日期', snippet(text, later[0].start())) if later else ('ended', '还没找到下一届的日期', '')
    s, e = date_hits(text, start), date_hits(text, end)
    s_year, e_year = any(y for _, y in s), any(y for _, y in e)
    if s and (e or start == end):
        if s_year or e_year:
            return 'ok', '日期和年份都在页面上', ''
        return 'ok', '日期在页面上（附近没写年份）', snippet(text, s[0][0])
    pos = (s or e or [(None, None)])[0][0]
    hint = snippet(text, pos) if pos is not None else ''
    other = re.search(rf'(?:{MONTH_RE[start.month]})[^.]{{0,20}}{start.year}', text, re.I)
    if not hint and other:
        hint = snippet(text, other.start())
    return 'check', ('只找到开始或结束其中一天' if pos is not None else '页面上没找到这两个日期'), hint


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--soon', type=int, help='only fairs starting within this many days')
    ap.add_argument('--limit', type=int, help='only check this many fairs')
    ap.add_argument('--ended-days', type=int, default=120, help='also look for the next edition of fairs ended within this many days')
    args = ap.parse_args()
    today = datetime.date.today()
    fairs = json.loads(CATALOG.read_text(encoding='utf-8'))['fairs']
    plans = json.loads(DATA.read_text(encoding='utf-8')).get('collections', {}).get('plans', {}) if DATA.exists() else {}

    def wanted(f):
        start, end = datetime.date.fromisoformat(f['start']), datetime.date.fromisoformat(f['end'])
        if args.soon is not None:
            return today <= start <= today + datetime.timedelta(days=args.soon) or start <= today <= end
        return end >= today or (today - end).days <= args.ended_days
    todo = sorted((f for f in fairs if wanted(f)), key=lambda f: f['start'])
    if args.limit:
        todo = todo[:args.limit]
    print(f'检查 {len(todo)} 场展会的官网，大约需要 {max(1, len(todo) // 25)}–{max(2, len(todo) // 12)} 分钟…')

    urls = sorted({f['url'] for f in todo})
    pages = {}
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for url, res in zip(urls, pool.map(fetch, urls)):
            pages[url] = res
    rows = []
    for f in todo:
        text, err = pages[f['url']]
        if not err and f.get('sourceUrl') and f['sourceUrl'] != f['url']:
            status, why, hint = check_fair(f, text, err, today)
            if status == 'check':  # the dates were found on a sub-page before: look there too
                text2, err2 = fetch(f['sourceUrl'])
                if not err2:
                    text, err = text2, err2
        rows.append((f, *check_fair(f, text, err, today)))

    def mine(f):
        return (plans.get(f['id']) or {}).get('status') in ('going', 'registered')
    groups = {
        '要去 / 已报名，需要你确认': [r for r in rows if mine(r[0]) and r[1] != 'ok'],
        '需人工看：页面上没找到登记的日期': [r for r in rows if r[1] == 'check' and not mine(r[0])],
        '打不开：请手动打开官网看': [r for r in rows if r[1] == 'blocked' and not mine(r[0])],
        '下一届：已结束的展会，页面上出现了更晚年份的日期': [r for r in rows if r[1] == 'next'],
        '已结束、还没找到下一届': [r for r in rows if r[1] == 'ended'],
        '仅见于聚合站、这次在官网上确认到了日期（可以改成已核实）': [r for r in rows if r[1] == 'ok' and r[0]['verify'] != 'official'],
    }
    ok = [r for r in rows if r[1] == 'ok']
    lines = [f'# 展会官网检查 {today}', '',
             f'共检查 {len(rows)} 场：确认 {len(ok)} · 需人工看 {sum(r[1] == "check" for r in rows)} · '
             f'打不开 {sum(r[1] == "blocked" for r in rows)} · 下一届线索 {sum(r[1] == "next" for r in rows)}', '',
             '这份报告只是提示：脚本读网页可能读错。任何改动都请先在官网上确认，再更新目录。', '']
    for title, rs in groups.items():
        if not rs:
            continue
        lines += [f'## {title}（{len(rs)}）', '']
        for f, status, why, hint in rs:
            lines.append(f'- **{f["name"]}** · {f["start"]} – {f["end"]} · {why} · {f["url"]}')
            if hint:
                lines.append(f'  - 页面上写的：{hint}')
        lines.append('')
    lines += [f'## 确认无误（{len(ok)}）', '', ', '.join(r[0]['name'] for r in ok) or '无', '']
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f'check-{today}.md'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines[:3]))
    for title, rs in groups.items():
        if rs:
            print(f'  {title}：{len(rs)}')
    print(f'\n完整报告：{out}')


if __name__ == '__main__':
    sys.exit(main())
