#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F1 2026 패독 — 데이터 자동 갱신 스크립트
표준 라이브러리만 사용한다 (외부 패키지 설치 불필요).

  python3 scripts/update.py

data/live.json 을 새로 쓴다. data/static.json 은 건드리지 않는다.
"""
import json, os, re, sys, html, urllib.request, urllib.error
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
# 뉴스에서 제외할 제목 패턴 (베팅/광고성)
NEWS_SKIP = re.compile(r'\b(betting|odds|bet365|promo|sweepstake|giveaway)\b', re.I)


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
def fetch_season():
    ds = getjson(f'{API}/driverstandings.json')
    cs = getjson(f'{API}/constructorstandings.json')
    rs = getjson(f'{API}/results.json?limit=1000')
    dv = getjson(f'{API}/drivers.json?limit=100')
    if not (ds and cs and rs):
        raise SystemExit('순위/결과 API를 가져오지 못했습니다. 나중에 다시 시도하세요.')

    dl = ds['MRData']['StandingsTable']['StandingsLists'][0]
    cl = cs['MRData']['StandingsTable']['StandingsLists'][0]
    rounds_done = int(dl['round'])

    # 드라이버 메타(생년월일/국적/번호)
    meta = {}
    for d in (dv or {}).get('MRData', {}).get('DriverTable', {}).get('Drivers', []):
        meta[norm(d['driverId'])] = d

    # 레이스 결과에서 포디엄/최고순위/라운드 우승자 계산
    podiums, best, winners, last_podium = {}, {}, {}, {}
    races = rs['MRData']['RaceTable']['Races']
    for race in races:
        rd = int(race['round'])
        top = {}
        for res in race['Results']:
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

    live = dict(
        updated=datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        roundsDone=rounds_done,
        drivers=drivers,
        constructors=constructors,
        winners=winners,
        podium=last_podium or prev.get('podium', {}),
        news=news,
    )

    def sig(o):
        c = dict(o); c.pop('updated', None); return json.dumps(c, sort_keys=True, ensure_ascii=False)

    if prev and sig(prev) == sig(live):
        print('변경 없음 — 파일을 다시 쓰지 않습니다.')
        return 0

    with open(LIVE, 'w', encoding='utf-8') as f:
        json.dump(live, f, ensure_ascii=False, indent=1)
    print(f'갱신 완료: {rounds_done}라운드 종료 · 드라이버 {len(drivers)}명 · 뉴스 {len(news)}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
