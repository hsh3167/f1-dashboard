#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F1 2026 패독 — 데이터 자동 갱신 스크립트
표준 라이브러리만 사용한다 (외부 패키지 설치 불필요).

  python3 scripts/update.py

data/live.json 을 새로 쓴다. data/static.json 은 건드리지 않는다.
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
NEWS_KO_QUERIES = [
    '"F1" (그랑프리 OR 예선 OR 결승 OR 드라이버) when:10d',
    '포뮬러1 OR 포뮬러원 when:10d',
    'F1 (레드불 OR 페라리 OR 메르세데스 OR 맥라렌) when:10d',
]

# 뉴스에서 제외할 제목 패턴 (베팅/광고성)
NEWS_SKIP = re.compile(r'\b(betting|bet builder|odds|bet365|promo|sweepstake|giveaway)\b', re.I)
# 베팅/광고 + 레이스와 무관한 협찬·상품·마케팅 기사
NEWS_KO_SKIP = re.compile(
    r'(베팅|배당|프로모션|이벤트 응모|쿠폰|할인'
    r'|사이니지|공급|납품|부티크|컬렉션|에디션 출시|한정판'
    r'|스폰서십 체결|후원 계약|MOU|업무협약'
    r'|시계|향수|주류|카지노|호텔 패키지)')
# 제목에 F1/모터스포츠 맥락이 반드시 있어야 한다
NEWS_KO_KEEP = re.compile(r'(F1|에프원|포뮬러|그랑프리|\bGP\b|퀄리파잉|예선|결승|포디엄|드라이버|팀 리뷰)', re.I)


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
            print(f'  ! 요청 {i + 1}/{tries}: {url} ({e})', file=sys.stderr)
            if not retryable or i == tries - 1:
                print(f'  ! 실패: {url} ({e})', file=sys.stderr)
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


# ---------------------------------------------------------------- 순위/결과
PAGE = 100          # jolpica 는 limit 을 100 으로 잘라낸다. 반드시 나눠 받아야 한다.


def fetch_paged(path, key, label):
    """결과 계열 엔드포인트를 페이지 단위로 모아 라운드별로 합친다. {라운드: [결과, ...]}

    jolpica/Ergast 는 limit 최대치가 100 이라 limit=1000 을 보내도 100건만 온다.
    한 레이스의 결과가 페이지 경계에 걸쳐 쪼개지므로 라운드별로 이어붙인다.
    """
    races, offset, total = {}, 0, None
    while True:
        rs = getjson(f'{API}/{path}?limit={PAGE}&offset={offset}')
        if rs is None:
            raise DataUnavailable(f'{label}: offset={offset} 수집 실패')
        md = rs['MRData']
        page_total = int(md['total'])
        if total is not None and total != page_total:
            raise DataUnavailable(f'{label}: 페이지 수집 중 total 변경')
        total = page_total
        before = sum(len(v) for v in races.values())
        for race in md['RaceTable']['Races']:
            races.setdefault(int(race['round']), []).extend(race.get(key, []))
        count = sum(len(v) for v in races.values()) - before
        if count == 0 and offset < total:
            raise DataUnavailable(f'{label}: 빈 중간 페이지')
        offset += count
        if offset >= total:
            break
    if total is not None:
        got = sum(len(v) for v in races.values())
        print(f'  · {label} {got}/{total}건 · {len(races)}개 라운드')
        if got != total:
            raise DataUnavailable(f'{label}: 불완전한 페이지 {got}/{total}')
    return races


def fetch_results():
    return fetch_paged('results.json', 'Results', '결승 결과')


def fetch_sprints():
    """스프린트 결과. 결승과 별도 엔드포인트라 이걸 빼면 누적 포인트가 어긋난다."""
    return fetch_paged('sprint.json', 'SprintResults', '스프린트 결과')


# 세션 키 → 화면 표기. 순서가 곧 주말 진행 순서다.
SESSION_KEYS = [
    ('FirstPractice', 'FP1'),
    ('SecondPractice', 'FP2'),
    ('ThirdPractice', 'FP3'),
    ('SprintQualifying', '스프린트 예선'),
    ('Sprint', '스프린트'),
    ('Qualifying', '예선'),
]


def fetch_schedule():
    """라운드별 세션 시각(UTC ISO). {'13': {'FirstPractice': '2026-09-04T10:30:00Z', ...}}

    스프린트 주말은 FP2/FP3 대신 SprintQualifying·Sprint 가 들어온다.
    """
    j = getjson(f'{API}.json?limit=30')
    out = {}
    if not j:
        print('  ! 세션 시간표를 가져오지 못했습니다', file=sys.stderr)
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
    print(f'  · 세션 시간표 {len(out)}개 라운드')
    return out


def fetch_season():
    ds = getjson(f'{API}/driverstandings.json')
    cs = getjson(f'{API}/constructorstandings.json')
    races_by_rd = fetch_results()
    if not (ds and cs and races_by_rd):
        raise DataUnavailable('순위/결과 API를 가져오지 못했습니다')

    dl = ds['MRData']['StandingsTable']['StandingsLists'][0]
    cl = cs['MRData']['StandingsTable']['StandingsLists'][0]
    # 순위 API 의 round 는 '다음 라운드'를 가리키는 경우가 있어 신뢰하지 않는다.
    # 실제로 결과가 존재하는 마지막 라운드를 종료 라운드로 본다.
    rounds_done = max(races_by_rd)

    # 레이스 결과에서 포디엄/최고순위/라운드 우승자 계산
    podiums, best, winners, last_podium = {}, {}, {}, {}
    race_results = {}          # 라운드별 전체 순위표
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
                # 완주자는 기록, 리타이어는 사유
                t=(res.get('Time') or {}).get('time') or res.get('status', ''),
            ))
        race_results[str(rd)] = sorted(rows, key=lambda x: x['p'])
        if rd == rounds_done:
            last_podium = {str(rd): [top.get(1), top.get(2), top.get(3)]}

    # 스프린트 결과 (포인트가 붙는 별도 경기)
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
            if NEWS_KO_SKIP.search(title) or not NEWS_KO_KEEP.search(title):
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
def validate_snapshot(snapshot, previous=None):
    if not isinstance(snapshot, dict):
        raise DataUnavailable('저장 데이터가 객체가 아닙니다')
    for key in ('drivers', 'constructors'):
        rows = snapshot.get(key)
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or 'id' not in r or 'pts' not in r for r in rows):
            raise DataUnavailable(f'{key}: 유효한 순위 없음')
    results = snapshot.get('results')
    if not isinstance(results, dict) or not results:
        raise DataUnavailable('유효한 결승 결과 없음')
    if max(map(int, results)) != snapshot.get('roundsDone'):
        raise DataUnavailable('종료 라운드와 결과 불일치')
    for key in ('results', 'sprints'):
        races = snapshot.get(key)
        if not isinstance(races, dict):
            raise DataUnavailable(f'{key}: 결과 객체 없음')
        for rd, rows in races.items():
            positions = sorted(r['p'] for r in rows)
            if not rows or positions != list(range(1, len(rows) + 1)) or len({r['d'] for r in rows}) != len(rows):
                raise DataUnavailable(f'{key}: {rd}라운드 결과 불완전')
        for rd, rows in (previous or {}).get(key, {}).items():
            if len(races.get(rd, [])) < len(rows):
                raise DataUnavailable(f'{key}: 기존 {rd}라운드 결과 누락')


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

    print('· 순위/결과 수집')
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
            report(f'갱신 실패: {e}; 사용할 수 있는 기존 데이터도 없습니다', warning=True)
            return 1
        report(f'갱신 보류: {e}. 기존 데이터와 갱신 시각({prev.get("updated", "알 수 없음")})을 그대로 유지합니다.', warning=True)
        return 0

    print('· 세션 시간표 수집')
    try:
        sessions = {**prev.get('sessions', {}), **fetch_schedule()}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        report(f'세션 시간표 유지: {e}', warning=True)
        sessions = prev.get('sessions', {})

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
        results=race_results,
        sprints=sprint_results,
        sessions=sessions,
        news=news,
        newsKo=news_ko,
    )

    def sig(o):
        c = dict(o); c.pop('updated', None); return json.dumps(c, sort_keys=True, ensure_ascii=False)

    if prev and sig(prev) == sig(live):
        print('변경 없음 — 파일을 다시 쓰지 않습니다.')
        return 0

    atomic_write(live)
    report('순위·결과 검증 및 데이터 갱신 완료')
    print(f'갱신 완료: {rounds_done}라운드 종료 · 드라이버 {len(drivers)}명 · '
          f'결과 {len(race_results)}R · 스프린트 {len(sprint_results)}R · 뉴스 {len(news)}건 · 한글 {len(news_ko)}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())

