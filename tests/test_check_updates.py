"""Offline checks for the date matching in tools/check_updates.py (no network).

    python tests/test_check_updates.py
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_updates import check_fair  # noqa: E402

TODAY = datetime.date(2026, 10, 12)
FAIR = {'start': '2026-11-17', 'end': '2026-11-19', 'verify': 'official'}
FOUND = [
    'METSTRADE 17-19 November 2026 RAI Amsterdam',
    'Join us 17–19 Nov 2026',
    'November 17-19, 2026 · Amsterdam',
    '17.–19.11.2026 Messe Nürnberg',
    '17. bis 19. November 2026',
    'du 17 au 19 novembre 2026',
    'dal 17 al 19 novembre 2026',
    '17 t/m 19 november 2026',
    'Dates: 17/11/2026 - 19/11/2026',
    '{"startDate":"2026-11-17T09:00","endDate":"2026-11-19T17:00"}',
    'Tuesday 17 November 2026 to Thursday 19 November 2026',
    '17.–19. marraskuuta 2026',
    'ADE 17 ––– 19/11 Amsterdam 2026',
    'Offshore Energy 17 & 19 November 2026',
    'Milano - 17 | 18 | 19 novembre 2026',
    'SIAE 17•19 November 2026',
    '17 et 19 novembre 2026 Paris Expo',
    '17 y 19 de noviembre de 2026',
    '17 und 19. November 2026',
]
NOT_FOUND = [
    'METSTRADE 18-20 November 2026',              # dates moved
    'METSTRADE 2027: 16-18 November',            # only next year shown
    'Save the date for the next edition',         # no dates at all
    '117 exhibitors from 19 countries in November',  # numbers that are not the dates
]


def main():
    fails = 0
    for text in FOUND:
        status = check_fair(FAIR, text, None, TODAY)[0]
        if status != 'ok':
            fails += 1
            print(f'FAIL should find dates: {text!r} -> {status}')
    for text in NOT_FOUND:
        status = check_fair(FAIR, text, None, TODAY)[0]
        if status == 'ok':
            fails += 1
            print(f'FAIL should not find dates: {text!r}')
    single = {'start': '2027-04-20', 'end': '2027-04-20', 'verify': 'official'}
    if check_fair(single, 'Tuesday 20 April 2027, Guildhall', None, TODAY)[0] != 'ok':
        fails += 1
        print('FAIL one-day event')
    ended = {'start': '2026-10-07', 'end': '2026-10-11', 'verify': 'official'}
    if check_fair(ended, 'See you again 6-10 October 2027', None, TODAY)[0] != 'next':
        fails += 1
        print('FAIL next edition not spotted')
    if check_fair(FAIR, None, 'HTTP 403', TODAY)[0] != 'blocked':
        fails += 1
        print('FAIL blocked page')
    total = len(FOUND) + len(NOT_FOUND) + 3
    print(f'{total - fails} passed, {fails} failed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
