#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F1 2026 �е� ? ������ �ڵ� ���� ��ũ��Ʈ
ǥ�� ���̺귯���� ����Ѵ� (�ܺ� ��Ű�� ��ġ ���ʿ�).

  python3 scripts/update.py

data/live.json �� ���� ����. data/static.json �� �ǵ帮�� �ʴ´�.
"""
import json, os, re, sys, html, urllib.request, urllib.error, urllib.parse
import http.client, random, tempfile, time
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'data', 'static.json')
LIVE   = os.path.join(ROOT, 'data', 'live.json')
SEASON = 2026
API    = f'https://api.jolpi.ca/ergast/f1/{SEASON}'
UA     = 'f1-paddock-updater/1.0 (+github pages static site)'
KST    = timezone(timedelta(hours=9))

# jolpica ����̹� id �� �� ����Ʈ���� ���� id
ALIAS = {'max_verstappen': 'verstappen', 'arvid_lindblad': 'lindblad'}
TEAM_ALIAS = {'sauber': 'audi'}

NEWS_FEEDS = [
    ('Formula1.com', 'https://www.formula1.com/content/fom-website/en/latest/all.xml'),
    ('Autosport',    'https://www.autosport.com/rss/f1/news/'),
    ('Motorsport',   'https://www.motorsport.com/rss/f1/news/'),
]
# �ѱ��� ����: ���� ���� RSS �˻� (��� ko, ���� KR)
GNEWS = 'https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko'
NEWS_KO_QUERIES = [
    '"F1" (�׶����� OR ���� OR ��� OR ����̹�) when:10d',
    '���ķ�1 OR ���ķ��� when:10d',
    'F1 (����� OR ��� OR �޸������� OR �ƶ�) when:10d',
]

# �������� ������ ���� ���� (����/������)
NEWS_SKIP = re.compile(r'\b(betting|bet builder|odds|bet365|promo|sweepstake|giveaway)\b', re.I)
# ����/���� + ���̽��� ������ ��������ǰ�������� ���
NEWS_KO_SKIP = re.compile(
    r'(����|���|���θ��|�̺�Ʈ ����|����|����'
    r'|���̴���|����|��ǰ|��Ƽũ|�÷���|����� ���|������'
    r'|�������� ü��|�Ŀ� ���|MOU|��������'
    r'|�ð�|���|�ַ�|ī����|ȣ�� ��Ű��)')
# ���� F1/���ͽ����� �ƶ��� �ݵ�� �־�� �Ѵ�
NEWS_KO_KEEP = re.compile(r'(F1|������|���ķ�|�׶�����|\bGP\b|��������|����|���|�����|����̹�|�� ����)', re.I)


class DataUnavailable(RuntimeError):
    """An upstream response cannot safely replace the saved snapshot."""


def get(url, tries=3, decode=None):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return decode(raw) if decode else raw
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException) as e:
            retryable = not isinstance(e, urllib.error.HTTPError) or e.code in (408, 429) or e.code >= 500
            print(f'  ! ��û {i + 1}/{tries}: {url} ({e})', file=sys.stderr)
            if not retryable or i == tries - 1:
                print(f'  ! ����: {url} ({e})', file=sys.stderr)
                return None
            delay = min(30, 2 ** (i + 1) + random.random())
            if isinstance(e, urllib.error.HTTPError):
                retry_after = (e.headers or {}).get('Retry-After', '')
                if retry_after.isdigit():
                    delay = min(30, max(delay, int(retry_after)))
            time.sleep(delay)
    return None


def getjson(url):
    return get(url, decode=lambda b: json.loads(b.decode('utf-8')))


def norm(did):
    return ALIAS.get(did, did)


# ---------------------------------------------------------------- ����/���
PAGE = 100          # jolpica �� limit �� 100 ���� �߶󳽴�. �ݵ�� ���� �޾ƾ� �Ѵ�.


def fetch_paged(path, key, label):
    """��� �迭 ��������Ʈ�� ������ ������ ��� ���庰�� ��ģ��. {����: [���, ...]}

    jolpica/Ergast �� limit �ִ�ġ�� 100 �̶� limit=1000 �� ������ 100�Ǹ� �´�.
    �� ���̽��� ����� ������ ��迡 ���� �ɰ����Ƿ� ���庰�� �̾���δ�.
    """
    races, offset, total = {}, 0, None
    while True:
        rs = getjson(f'{API}/{path}?limit={PAGE}&offset={offset}')
        if rs is None:
            raise DataUnavailable(f'{label}: offset={offset} ���� ����')
        md = rs['MRData']
        page_total = int(md['total'])
        if total is not None and total != page_total:
            raise DataUnavailable(f'{label}: ������ ���� �� total ����')
        total = page_total
        before = sum(len(v) for v in races.values())
        for race in md['RaceTable']['Races']:
            races.setdefault(int(race['round']), []).extend(race.get(key, []))
        count = sum(len(v) for v in races.values()) - before
        if count == 0 and offset < total:
            raise DataUnavailable(f'{label}: �� �߰� ������')
        offset += count
        if offset >= total:
            break
    if total is not None:
        got = sum(len(v) for v in races.values())
        print(f'  �� {label} {got}/{total}�� �� {len(races)}�� ����')
        if got != total:
            raise DataUnavailable(f'{label}: �ҿ����� ������ {got}/{total}')
    return races


def fetch_results():
    return fetch_paged('results.json', 'Results', '��� ���')


def fetch_sprints():
    """������Ʈ ���. ��°� ���� ��������Ʈ�� �̰� ���� ���� ����Ʈ�� ��߳���."""
    return fetch_paged('sprint.json', 'SprintResults', '������Ʈ ���')


# ���� Ű �� ȭ�� ǥ��. ������ �� �ָ� ���� ������.
SESSION_KEYS = [
    ('FirstPractice', 'FP1'),
    ('SecondPractice', 'FP2'),
    ('ThirdPractice', 'FP3'),
    ('SprintQualifying', '������Ʈ ����'),
    ('Sprint', '������Ʈ'),
    ('Qualifying', '����'),
]


def fetch_schedule():
    """���庰 ���� �ð�(UTC ISO). {'13': {'FirstPractice': '2026-09-04T10:30:00Z', ...}}

    ������Ʈ �ָ��� FP2/FP3 ��� SprintQualifying��Sprint �� ���´�.
    """
    j = getjson(f'{API}.json?limit=30')
    out = {}
    if not j:
        print('  ! ���� �ð�ǥ�� �������� ���߽��ϴ�', file=sys.stderr)
        return out
    for race in j['MRData']['RaceTable']['Races']:
        s = {}
        for key, _ in SESSION_KEYS:
            v = race.get(key) or {}
            if v.get('date'):
                s[key] = v['date'] + 'T' + v.get('time', '00:00:00Z')
        if race.get('date'):
            s['Race'] = race['date'] + 'T' + race.get('time', '00:00:00Z')
        out[str(int(race['round']))] = s
    print(f'  �� ���� �ð�ǥ {len(out)}�� ����')
    return out


def fetch_season():
    ds = getjson(f'{API}/driverstandings.json')
    cs = getjson(f'{API}/constructorstandings.json')
    races_by_rd = fetch_results()
    if not (ds and cs and races_by_rd):
        raise DataUnavailable('����/��� API�� �������� ���߽��ϴ�')

    dl = ds['MRData']['StandingsTable']['StandingsLists'][0]
    cl = cs['MRData']['StandingsTable']['StandingsLists'][0]
    # ���� API �� round �� '���� ����'�� ����Ű�� ��찡 �־� �ŷ����� �ʴ´�.
    # ������ ����� �����ϴ� ������ ���带 ���� ����� ����.
    rounds_done = max(races_by_rd)

    # ���̽� ������� �����/�ְ�����/���� ����� ���
    podiums, best, winners, last_podium = {}, {}, {}, {}
    race_results = {}          # ���庰 ��ü ����ǥ
    for rd in sorted(races_by_rd):
        top, rows = {}, []
        for res in races_by_rd[rd]:
            did = norm(res['Driver']['driverId'])
            pos = int(res['position'])
            best[did] = min(best.get(did, 99), pos)
            if pos <= 3:
                podiums[did] = podiums.get(did, 0) + 1
                top[pos] = did
            if pos == 1:
                winners[str(rd)] = did
            pts = float(res.get('points', 0) or 0)
            rows.append(dict(
                p=pos,
                d=did,
                g=int(res.get('grid', 0) or 0),
                pts=int(pts) if pts.is_integer() else pts,
                # �����ڴ� ���, ��Ÿ�̾�� ����
                t=(res.get('Time') or {}).get('time') or res.get('status', ''),
            ))
        race_results[str(rd)] = sorted(rows, key=lambda x: x['p'])
        if rd == rounds_done:
            last_podium = {str(rd): [top.get(1), top.get(2), top.get(3)]}

    # ������Ʈ ��� (����Ʈ�� �ٴ� ���� ���)
    sprint_results = {}
    for rd, res_list in fetch_sprints().items():
        rows = []
        for res in res_list:
            pts = float(res.get('points', 0) or 0)
            rows.append(dict(
                p=int(res['position']),
                d=norm(res['Driver']['driverId']),
                g=int(res.get('grid', 0) or 0),
                pts=int(pts) if pts.is_integer() else pts,
                t=(res.get('Time') or {}).get('time') or res.get('status', ''),
            ))
        sprint_results[str(rd)] = sorted(rows, key=lambda x: x['p'])

    drivers = []
    for s in dl['DriverStandings']:
        d = s['Driver']
        did = norm(d['driverId'])
        cons = s['Constructors'][-1]['constructorId']
        drivers.append(dict(
            id=did,
            code=d.get('code') or d['familyName'][:3].upper(),
            num=int(d.get('permanentNumber') or 0),
            first=d['givenName'], last=d['familyName'],
            dob=d.get('dateOfBirth', ''),
            nationality=d.get('nationality', ''),
            team=TEAM_ALIAS.get(cons, cons),
            pos=int(s['position']), pts=float(s['points']),
            wins=int(s['wins']),
            podiums=podiums.get(did, 0),
            best=best.get(did, 0),
        ))
    for d in drivers:
        d['pts'] = int(d['pts']) if float(d['pts']).is_integer() else d['pts']

    constructors = [dict(
        id=TEAM_ALIAS.get(s['Constructor']['constructorId'], s['Constructor']['constructorId']),
        pos=int(s['position']),
        pts=int(float(s['points'])),
        wins=int(s['wins']),
    ) for s in cl['ConstructorStandings']]

    return rounds_done, drivers, constructors, winners, last_podium, race_results, sprint_results


# ---------------------------------------------------------------- ����
def text(el):
    return html.unescape(re.sub(r'<[^>]+>', '', (el.text or ''))).strip() if el is not None else ''


def fetch_news(limit=14):
    items = []
    for src, url in NEWS_FEEDS:
        raw = get(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f'  ! RSS �Ľ� ���� {src}: {e}', file=sys.stderr)
            continue
        for i, it in enumerate(root.iter('item')):
            title = text(it.find('title'))
            link = text(it.find('link'))
            if not title or not link.startswith('http'):
                continue
            if NEWS_SKIP.search(title):
                continue
            date = ''
            pd = it.find('pubDate')
            if pd is not None and pd.text:
                m = re.search(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', pd.text)
                if m:
                    mon = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
                           'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m.group(2))
                    if mon:
                        date = f'{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}'
            items.append(dict(en=title, url=link, src=src, date=date, ord=i))
        print(f'  �� {src}: {sum(1 for x in items if x["src"]==src)}��')

    seen, out = set(), []
    # ���� �ǵ带 ����, �������� ��¥ ��������
    items.sort(key=lambda x: (0 if x['src'] == 'Formula1.com' else 1,
                              x['ord'] if x['src'] == 'Formula1.com' else 0,
                              '' if x['src'] == 'Formula1.com' else x['date']),
               reverse=False)
    others = sorted([x for x in items if x['src'] != 'Formula1.com'],
                    key=lambda x: x['date'], reverse=True)
    ordered = [x for x in items if x['src'] == 'Formula1.com'] + others
    for x in ordered:
        key = x['url'].split('?')[0]
        if key in seen:
            continue
        seen.add(key)
        out.append({k: x[k] for k in ('en', 'url', 'src', 'date')})
        if len(out) >= limit:
            break
    return out


def fetch_news_ko(limit=12):
    """���� ���� RSS(�ѱ���)���� F1 ���� ��縦 ������.

    �����ϸ� �� ����Ʈ�� �����ְ�, ȣ��ΰ� ���� ���� �����Ѵ�.
    ���� ���� �׸��� ������ '��� ���� - ��л�' ���̰� ��л�� <source> ���� ����ִ�.
    """
    items, seen_t = [], set()
    for q in NEWS_KO_QUERIES:
        url = GNEWS.format(urllib.parse.quote(q))
        raw = get(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f'  ! �ѱ� RSS �Ľ� ���� ({q}): {e}', file=sys.stderr)
            continue
        n = 0
        for it in root.iter('item'):
            title = text(it.find('title'))
            link = text(it.find('link'))
            if not title or not link.startswith('http'):
                continue
            if NEWS_KO_SKIP.search(title) or not NEWS_KO_KEEP.search(title):
                continue
            src = text(it.find('source'))
            # '���� - ��л�' ���� ���� ��л縦 �����
            if src and title.endswith(' - ' + src):
                title = title[: -(len(src) + 3)].strip()
            elif ' - ' in title:
                title, _, tail = title.rpartition(' - ')
                src = src or tail.strip()
            key = re.sub(r'\s+', '', title)
            if key in seen_t:
                continue
            seen_t.add(key)
            date = ''
            pd = it.find('pubDate')
            if pd is not None and pd.text:
                m = re.search(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', pd.text)
                if m:
                    mon = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
                           'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}.get(m.group(2))
                    if mon:
                        date = f'{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}'
            items.append(dict(ko=title, url=link, src=src or '���� ����', date=date))
            n += 1
            if n >= limit:
                break
        print(f'  �� �ѱ�({q}): {n}��')

    items.sort(key=lambda x: x['date'], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------- main
def validate_snapshot(snapshot, previous=None):
    if not isinstance(snapshot, dict):
        raise DataUnavailable('���� �����Ͱ� ��ü�� �ƴմϴ�')
    for key in ('drivers', 'constructors'):
        rows = snapshot.get(key)
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or 'id' not in r or 'pts' not in r for r in rows):
            raise DataUnavailable(f'{key}: ��ȿ�� ���� ����')
    results = snapshot.get('results')
    if not isinstance(results, dict) or not results:
        raise DataUnavailable('��ȿ�� ��� ��� ����')
    if max(map(int, results)) != snapshot.get('roundsDone'):
        raise DataUnavailable('���� ����� ��� ����ġ')
    for key in ('results', 'sprints'):
        races = snapshot.get(key)
        if not isinstance(races, dict):
            raise DataUnavailable(f'{key}: ��� ��ü ����')
        for rd, rows in races.items():
            positions = sorted(r['p'] for r in rows)
            if not rows or positions != list(range(1, len(rows) + 1)) or len({r['d'] for r in rows}) != len(rows):
                raise DataUnavailable(f'{key}: {rd}���� ��� �ҿ���')
        for rd, rows in (previous or {}).get(key, {}).items():
            if len(races.get(rd, [])) < len(rows):
                raise DataUnavailable(f'{key}: ���� {rd}���� ��� ����')


def report(message, warning=False):
    print(('::warning::' if warning else '') + message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(message + '\n')


def atomic_write(live):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(LIVE), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(live, f, ensure_ascii=False, indent=1)
            f.write('\n')
        os.replace(tmp, LIVE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    with open(STATIC, encoding='utf-8') as f:
        static = json.load(f)
    prev = {}
    if os.path.exists(LIVE):
        with open(LIVE, encoding='utf-8') as f:
            prev = json.load(f)
    prev_news = {n['url']: n for n in prev.get('news', [])}

    print('�� ����/��� ����')
    try:
        rounds_done, drivers, constructors, winners, last_podium, race_results, sprint_results = fetch_season()
        candidate = dict(roundsDone=rounds_done, drivers=drivers, constructors=constructors,
                         results=race_results, sprints=sprint_results)
        validate_snapshot(candidate, prev)
    except (DataUnavailable, KeyError, IndexError, TypeError, ValueError) as e:
        # A valid saved snapshot is the fallback, never an empty/partial API response.
        try:
            validate_snapshot(prev)
        except (DataUnavailable, KeyError, IndexError, TypeError, ValueError):
            report(f'���� ����: {e}; ����� �� �ִ� ���� �����͵� �����ϴ�', warning=True)
            return 1
        report(f'���� ����: {e}. ���� �����Ϳ� ���� �ð�({prev.get("updated", "�� �� ����")})�� �״�� �����մϴ�.', warning=True)
        return 0

    print('�� ���� �ð�ǥ ����')
    try:
        sessions = {**prev.get('sessions', {}), **fetch_schedule()}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        report(f'���� �ð�ǥ ����: {e}', warning=True)
        sessions = prev.get('sessions', {})

    # �ѱ� �̸����������޸� static.json ���� ���δ�
    ko_name, ko_nat, nat_flag = static['koName'], static['koNat'], static['natFlag']
    for d in drivers:
        d['ko'] = ko_name.get(d['id'], f"{d['first']} {d['last']}")
        d['nat'] = ko_nat.get(d['nationality'], d['nationality'])
        d['flag'] = nat_flag.get(d['nationality'], 'un')
        d['note'] = static.get('notes', {}).get(d['id'], '')
        d.pop('nationality', None)

    print('�� ���� ����')
    news = fetch_news()
    # ������ ����� �ٿ��� �ѱ��� ����/�±װ� ������ ����
    for n in news:
        p = prev_news.get(n['url'])
        if p:
            if p.get('ko'):
                n['ko'] = p['ko']
            if p.get('tag'):
                n['tag'] = p['tag']
    if not news:
        print('  ! ������ �������� ���� ���� ������ �����մϴ�', file=sys.stderr)
        news = prev.get('news', [])

    print('�� �ѱ� ���� ����')
    news_ko = fetch_news_ko()
    if not news_ko:
        print('  ! �ѱ� ������ �������� ���� ���� ���� �����մϴ�', file=sys.stderr)
        news_ko = prev.get('newsKo', [])

    live = dict(
        updated=datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        roundsDone=rounds_done,
        drivers=drivers,
        constructors=constructors,
        winners=winners,
        podium=last_podium or prev.get('podium', {}),
        results=race_results,
        sprints=sprint_results,
        sessions=sessions,
        news=news,
        newsKo=news_ko,
    )

    def sig(o):
        c = dict(o); c.pop('updated', None); return json.dumps(c, sort_keys=True, ensure_ascii=False)

    if prev and sig(prev) == sig(live):
        print('���� ���� ? ������ �ٽ� ���� �ʽ��ϴ�.')
        return 0

    atomic_write(live)
    report('��������� ���� �� ������ ���� �Ϸ�')
    print(f'���� �Ϸ�: {rounds_done}���� ���� �� ����̹� {len(drivers)}�� �� '
          f'��� {len(race_results)}R �� ������Ʈ {len(sprint_results)}R �� ���� {len(news)}�� �� �ѱ� {len(news_ko)}��')
    return 0


if __name__ == '__main__':
    sys.exit(main())

