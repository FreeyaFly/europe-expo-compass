"""Check the fair catalogue against the organisers' own websites, without Claude.

    python tools/check_updates.py              -> check every fair that has not ended yet, plus recently ended ones
    python tools/check_updates.py --soon 60    -> only fairs starting in the next 60 days
    python tools/check_updates.py --limit 10   -> only the first 10 (quick try)
    --lang zh|en                               -> report language (default: the app's language, then the system's)

For each fair it opens the official page and reports:
  confirmed        the stored start and end dates are on the page
  needs a look     the page opened but the stored dates were not found (date changed, or the page shows them
                   only after JavaScript runs)
  next edition     the fair has ended and the page mentions dates in a later year
  could not open   the page could not be opened (blocked, timeout, error)
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

import cli_lang

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


def error_name(e):
    """A short, language-neutral name for a network error (Windows words its own messages in the system language)."""
    reason = getattr(e, 'reason', e)
    if isinstance(reason, TimeoutError) or 'timed out' in str(reason):
        return 'timeout'
    if isinstance(reason, ConnectionRefusedError):
        return 'connection refused'
    if isinstance(reason, ConnectionResetError):
        return 'connection reset'
    if isinstance(reason, ssl.SSLError):
        return 'SSL error'
    if isinstance(reason, OSError) and getattr(reason, 'errno', None) in (11001, -2, -3, 8):
        return 'unknown host'
    return type(reason).__name__


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
        return None, error_name(e)
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
    """(status, reason, page excerpt). reason is a key of MSG[lang]['why'], or the error text for 'blocked'."""
    start, end = datetime.date.fromisoformat(f['start']), datetime.date.fromisoformat(f['end'])
    if err:
        return 'blocked', err, ''
    if end < today:
        later = [m for y in (end.year + 1, end.year + 2)
                 for m in re.finditer(rf'(?:{"|".join(MONTH_RE.values())})[^.]{{0,25}}{y}|{y}-\d\d-\d\d|\d{{1,2}}[./]\d{{1,2}}[./]{y}', text, re.I)]
        return ('next', 'later_year', snippet(text, later[0].start())) if later else ('ended', 'no_next', '')
    s, e = date_hits(text, start), date_hits(text, end)
    s_year, e_year = any(y for _, y in s), any(y for _, y in e)
    if s and (e or start == end):
        if s_year or e_year:
            return 'ok', 'dates_and_year', ''
        return 'ok', 'dates_no_year', snippet(text, s[0][0])
    pos = (s or e or [(None, None)])[0][0]
    hint = snippet(text, pos) if pos is not None else ''
    other = re.search(rf'(?:{MONTH_RE[start.month]})[^.]{{0,20}}{start.year}', text, re.I)
    if not hint and other:
        hint = snippet(text, other.start())
    return 'check', ('one_date' if pos is not None else 'no_dates'), hint


MSG = {
    'zh': {
        'start': '检查 {n} 场展会的官网，大约需要 {a}–{b} 分钟…',
        'title': '# 展会官网检查 {d}',
        'summary': '共检查 {n} 场：确认 {ok} · 需人工看 {check} · 打不开 {blocked} · 下一届线索 {next}',
        'note': '这份报告只是提示：脚本读网页可能读错。任何改动都请先在官网上确认，再更新目录。',
        'groups': {'mine': '要去 / 已报名，需要你确认', 'check': '需人工看：页面上没找到登记的日期',
                   'blocked': '打不开：请手动打开官网看', 'next': '下一届：已结束的展会，页面上出现了更晚年份的日期',
                   'ended': '已结束、还没找到下一届', 'upgrade': '仅见于聚合站、这次在官网上确认到了日期（可以改成已核实）'},
        'why': {'later_year': '页面上有更晚年份的日期', 'no_next': '还没找到下一届的日期', 'dates_and_year': '日期和年份都在页面上',
                'dates_no_year': '日期在页面上（附近没写年份）', 'one_date': '只找到开始或结束其中一天', 'no_dates': '页面上没找到这两个日期'},
        'excerpt': '页面上写的：', 'confirmed': '确认无误', 'none': '无', 'count': '（{n}）', 'colon': '：', 'report': '\n完整报告：{p}',
    },
    'en': {
        'start': 'Checking the official websites of {n} fairs; this takes about {a}–{b} minutes…',
        'title': '# Official website check {d}',
        'summary': 'Checked {n} fairs: confirmed {ok} · needs a look {check} · could not open {blocked} · next edition hints {next}',
        'note': 'This report only gives hints: reading web pages can go wrong. Confirm every change on the official site before updating the catalogue.',
        'groups': {'mine': 'Going / registered: please confirm', 'check': 'Needs a look: the stored dates were not found on the page',
                   'blocked': 'Could not open: please open the official site by hand', 'next': 'Next edition: ended fairs whose page shows a later year',
                   'ended': 'Ended, next edition not found yet', 'upgrade': 'Aggregator only, but the dates were found on the official site this time (can be marked verified)'},
        'why': {'later_year': 'the page shows dates in a later year', 'no_next': 'no dates for the next edition yet', 'dates_and_year': 'dates and year are on the page',
                'dates_no_year': 'dates are on the page (no year nearby)', 'one_date': 'only the start or the end date was found', 'no_dates': 'neither date was found on the page'},
        'excerpt': 'The page says: ', 'confirmed': 'Confirmed', 'none': 'none', 'count': ' ({n})', 'colon': ': ', 'report': '\nFull report: {p}',
    },
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--soon', type=int, help='only fairs starting within this many days')
    ap.add_argument('--limit', type=int, help='only check this many fairs')
    ap.add_argument('--ended-days', type=int, default=120, help='also look for the next edition of fairs ended within this many days')
    ap.add_argument('--lang', choices=cli_lang.LANGS, help="report language (default: the app's language, then the system's)")
    args = ap.parse_args()
    lang = args.lang or cli_lang.pick([], data_file=DATA)
    m = MSG[lang]
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
    print(m['start'].format(n=len(todo), a=max(1, len(todo) // 25), b=max(2, len(todo) // 12)))

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
    def name(f):  # the fair's name in the report language
        return (f.get('en') or {}).get('name', f['name']) if lang == 'en' else f['name']
    groups = {
        'mine': [r for r in rows if mine(r[0]) and r[1] != 'ok'],
        'check': [r for r in rows if r[1] == 'check' and not mine(r[0])],
        'blocked': [r for r in rows if r[1] == 'blocked' and not mine(r[0])],
        'next': [r for r in rows if r[1] == 'next'],
        'ended': [r for r in rows if r[1] == 'ended'],
        'upgrade': [r for r in rows if r[1] == 'ok' and r[0]['verify'] != 'official'],
    }
    ok = [r for r in rows if r[1] == 'ok']
    lines = [m['title'].format(d=today), '',
             m['summary'].format(n=len(rows), ok=len(ok), check=sum(r[1] == 'check' for r in rows),
                                 blocked=sum(r[1] == 'blocked' for r in rows), next=sum(r[1] == 'next' for r in rows)), '',
             m['note'], '']
    for key, rs in groups.items():
        if not rs:
            continue
        lines += ['## ' + m['groups'][key] + m['count'].format(n=len(rs)), '']
        for f, status, why, hint in rs:
            lines.append(f'- **{name(f)}** · {f["start"]} – {f["end"]} · {m["why"].get(why, why)} · {f["url"]}')
            if hint:
                lines.append(f'  - {m["excerpt"]}{hint}')
        lines.append('')
    lines += ['## ' + m['confirmed'] + m['count'].format(n=len(ok)), '', ', '.join(name(r[0]) for r in ok) or m['none'], '']
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f'check-{today}.md'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines[:3]))
    for key, rs in groups.items():
        if rs:
            print(f'  {m["groups"][key]}{m["colon"]}{len(rs)}')
    print(m['report'].format(p=out))


if __name__ == '__main__':
    sys.exit(main())
