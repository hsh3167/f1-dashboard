#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F1 2026 패독 — 데이터 자동 갱신 스크립트
표준 라이브러리만 사용한다 (외부 패키지 설치 불필요).

  python3 scripts/update.py

data/live.json 을 새로 쓴다. data/static.json 은 건드리지 않는다.
"""
import json, os, re, sys, html, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'data', 'static.json')
LIVE   = os.path.join(ROOT, 'data', 'live.json')
SEASON = 2026
API    = f'https://api.jolpi.ca/ergast/f1/{SEASON}'
UA     = 'f1-paddock-updater/1.0 (+github pages static site)'
KST    = timezone(timedelta(hours=9))

# jolpica 드라이버 id → 이 사이트에서 쓰는 id
ALIAS = {'max_verstappen': 'verstappen', 'arvid_lindblad': 'lindblad'}
TEAM_ALIAS = {'sauber': 'audi'}

NEWS_FEEDS = [
    ('Formula1.com', 'https://www.formula1.com/content/fom-website/en/latest/all.xml'),
    ('Autosport',    'https://www.autosport.com/rss/f1/news/'),
    ('Motorsport',   'https://www.motorsport.com/rss/f1/news/'),
]
# 한국어 뉴스: 구글 뉴스 RSS 검색 (언어 ko, 지역 KR)
GNEWS = 'https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko'
NEWS_KO_QUERIES = ['F1 그랑프리', '포뮬러1', 'F1 머신 OR 드라이버 when:14d']

# 뉴스에서 제외할 제목 패턴 (베팅/광고성)
NEWS_SKIP = re.compile(r'\b(betting|bet builder|odds|bet365|promo|sweepstake|giveaway)\b', re.I)
NEWS_KO_SKIP = re.compile(r'(베팅|배당|프로모션|이벤트 응모|쿠폰)')


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                print(f'  ! 실패: {url} ({e})', file=sys.stderr)
                return None
    return None


def getjson(url):
    b = get(url)
    return json.loads(b.decode('utf-8')) if b else None


def norm(did):
    return ALIAS.get(did, did)


# ---------------------------------------------------------------- 순위/결과
PAGE = 100          # jolpica 는 limit 을 100 으로 잘라낸다. 반드시 나눠 받아야 한다.


def fetch_results():
    """시즌 전체 레이스 결과를 라운드별로 모은다. {라운드: [결과, ...]}

    jolpica/Ergast 는 limit 최대치가 100 이라 limit=1000 을 보내도 100건만 온다.
    한 레이스의 결과가 페이지 경계에 걸쳐 쪼개지므로 라운드별로 이어붙인다.
    """
    races, offset, total = {}, 0, None
    while True:
        rs = getjson(f'{API}/results.json?limit={PAGE}&offset={offset}')
        if not rs:
            break
        md = rs['MRData']
        total = int(md['total'])
        for race in md['RaceTable']['Races']:
            races.setdefault(int(race['round']), []).extend(race['Results'])
        offset += PAGE
        if offset >= total:
            break
    if total is not None:
        got = sum(len(v) for v in races.values())
        print(f'  · 결과 {got}/{total}건 · {len(races)}개 라운드')
    return races


def fetch_season():
    ds = getjson(f'{API}/driverstandings.json')
    cs = getjson(f'{API}/constructorstandings.json')
    races_by_rd = fetch_results()
    dv = getjson(f'{API}/drivers.json?limit=100')
    if not (ds and cs and races_by_rd):
        raise SystemExit('순위/결과 API를 가져오지 못했습니다. 나중에 다시 시도하세요.')

    dl = ds['MRData']['StandingsTable']['StandingsLists'][0]
    cl = cs['MRData']['StandingsTable']['StandingsLists'][0]
    # 순위 API 의 round 는 '다음 라운드'를 가리키는 경우가 있어 신뢰하지 않는다.
    # 실제로 결과가 존재하는 마지막 라운드를 종료 라운드로 본다.
    rounds_done = max(races_by_rd)

    # 드라이버 메타(생년월일/국적/번호)
    meta = {}
    for d in (dv or {}).get('MRData', {}).get('DriverTable', {}).get('Drivers', []):
        meta[norm(d['driverId'])] = d

    # 레이스 결과에서 포디엄/최고순위/라운드 우승자 계산
    podiums, best, winners, last_podium = {}, {}, {}, {}
    for rd in sorted(races_by_rd):
        top = {}
        for res in races_by_rd[rd]:
            did = norm(res['Driver']['driverId'])
            pos = int(res['position'])
            best[did] = min(best.get(did, 99), pos)
            if pos <= 3:
                podiums[did] = podiums.get(did, 0) + 1
                top[pos] = did
            if pos == 1:
                winners[str(rd)] = did
        if rd == rounds_done:
            last_podium = {str(rd): [top.get(1), top.get(2), top.get(3)]}

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

    return rounds_done, drivers, constructors, winners, last_podium


# ---------------------------------------------------------------- 뉴스
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
            print(f'  ! RSS 파싱 실패 {src}: {e}', file=sys.stderr)
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
        print(f'  · {src}: {sum(1 for x in items if x["src"]==src)}건')

    seen, out = set(), []
    # 공식 피드를 먼저, 나머지는 날짜 내림차순
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
    """구글 뉴스 RSS(한국어)에서 F1 관련 기사를 모은다.

    실패하면 빈 리스트를 돌려주고, 호출부가 이전 값을 유지한다.
    구글 뉴스 항목의 제목은 '기사 제목 - 언론사' 꼴이고 언론사는 <source> 에도 들어있다.
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
            print(f'  ! 한글 RSS 파싱 실패 ({q}): {e}', file=sys.stderr)
            continue
        n = 0
        for it in root.iter('item'):
            title = text(it.find('title'))
            link = text(it.find('link'))
            if not title or not link.startswith('http'):
                continue
            if NEWS_KO_SKIP.search(title):
                continue
            src = text(it.find('source'))
            # '제목 - 언론사' 에서 뒤쪽 언론사를 떼어낸다
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
            items.append(dict(ko=title, url=link, src=src or '구글 뉴스', date=date))
            n += 1
            if n >= limit:
                break
        print(f'  · 한글({q}): {n}건')

    items.sort(key=lambda x: x['date'], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------- main
def main():
    static = json.load(open(STATIC, encoding='utf-8'))
    prev = {}
    if os.path.exists(LIVE):
        prev = json.load(open(LIVE, encoding='utf-8'))
    prev_news = {n['url']: n for n in prev.get('news', [])}

    print('· 순위/결과 수집')
    rounds_done, drivers, constructors, winners, last_podium = fetch_season()

    # 한글 이름·국적·메모를 static.json 에서 붙인다
    ko_name, ko_nat, nat_flag = static['koName'], static['koNat'], static['natFlag']
    for d in drivers:
        d['ko'] = ko_name.get(d['id'], f"{d['first']} {d['last']}")
        d['nat'] = ko_nat.get(d['nationality'], d['nationality'])
        d['flag'] = nat_flag.get(d['nationality'], 'un')
        d['note'] = static.get('notes', {}).get(d['id'], '')
        d.pop('nationality', None)

    print('· 뉴스 수집')
    news = fetch_news()
    # 이전에 사람이 붙여둔 한국어 제목/태그가 있으면 유지
    for n in news:
        p = prev_news.get(n['url'])
        if p:
            if p.get('ko'):
                n['ko'] = p['ko']
            if p.get('tag'):
                n['tag'] = p['tag']
    if not news:
        print('  ! 뉴스를 가져오지 못해 기존 뉴스를 유지합니다', file=sys.stderr)
        news = prev.get('news', [])

    print('· 한글 뉴스 수집')
    news_ko = fetch_news_ko()
    if not news_ko:
        print('  ! 한글 뉴스를 가져오지 못해 기존 값을 유지합니다', file=sys.stderr)
        news_ko = prev.get('newsKo', [])

    live = dict(
        updated=datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        roundsDone=rounds_done,
        drivers=drivers,
        constructors=constructors,
        winners=winners,
        podium=last_podium or prev.get('podium', {}),
        news=news,
        newsKo=news_ko,
    )

    def sig(o):
        c = dict(o); c.pop('updated', None); return json.dumps(c, sort_keys=True, ensure_ascii=False)

    if prev and sig(prev) == sig(live):
        print('변경 없음 — 파일을 다시 쓰지 않습니다.')
        return 0

    with open(LIVE, 'w', encoding='utf-8') as f:
        json.dump(live, f, ensure_ascii=False, indent=1)
    print(f'갱신 완료: {rounds_done}라운드 종료 · 드라이버 {len(drivers)}명 · '
          f'뉴스 {len(news)}건 · 한글 뉴스 {len(news_ko)}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
