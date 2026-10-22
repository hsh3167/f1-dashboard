# F1 2026 패독 — 자동 갱신 대시보드

2026 F1 시즌의 드라이버·컨스트럭터 순위, 남은 일정과 실제 서킷 도면, 드라이버 프로필,
팀별 머신 기술 정보, 최신 뉴스를 한 페이지에 모은 정적 웹사이트입니다.

**GitHub Pages에 한 번 올려두면 그 뒤로는 사람이 손대지 않아도 매일 스스로 갱신됩니다.**

---

## 갱신이 이루어지는 두 가지 경로

| 경로 | 무엇이 갱신되나 | 언제 |
|---|---|---|
| **① 브라우저 실시간 호출** | 드라이버·컨스트럭터 순위 | 방문자가 페이지를 열 때마다 |
| **② GitHub Actions** | 순위 + 레이스 결과 + 포디엄 + 뉴스 | 3시간마다 17분 (한국시간 00/03/06/09/12/15/18/21시) |

①이 막히더라도(브라우저 CORS 정책 등) ②가 만들어 둔 `data/live.json` 으로 항상 정상 동작합니다.
어느 쪽도 Claude를 필요로 하지 않습니다.

---

## 설치 (10분)

### 1. GitHub 저장소 만들기
1. https://github.com/new 접속
2. **Repository name**: `f1-2026` (원하는 이름 아무거나)
3. **Public** 선택 — *Private으로 하면 GitHub Pages 무료 사용이 안 됩니다*
4. **Create repository** 클릭

### 2. 파일 올리기
받은 폴더의 **내용물 전체**를 저장소 최상단에 올립니다.

```
f1-2026/
├── index.html
├── data/
│   ├── static.json
│   └── live.json
├── scripts/
│   └── update.py
├── .github/workflows/update.yml
└── README.md
```

> **주의**: 웹 화면에서 드래그로 올릴 때 `.github` 폴더는 숨김 폴더라 누락되기 쉽습니다.
> 누락되면 자동 갱신이 동작하지 않습니다. 아래 git 명령을 쓰면 확실합니다.
>
> ```bash
> cd f1-2026
> git init
> git add -A
> git commit -m "F1 2026 패독 대시보드"
> git branch -M main
> git remote add origin https://github.com/<사용자명>/f1-2026.git
> git push -u origin main
> ```

### 3. GitHub Pages 켜기
저장소 → **Settings** → 왼쪽 메뉴 **Pages**
- **Source**: `Deploy from a branch`
- **Branch**: `main` / `/ (root)` → **Save**

1~2분 뒤 주소가 나옵니다:
```
https://<사용자명>.github.io/f1-2026/
```
이 주소를 누구에게든 공유하면 됩니다.

### 4. 자동 갱신 켜기
저장소 → **Actions** 탭 → 초록 버튼 **I understand my workflows, go ahead and enable them**

바로 확인하고 싶다면 **Actions → F1 데이터 자동 갱신 → Run workflow** 로 즉시 한 번 돌려보세요.

---

## 관리 요령

**갱신 시각 바꾸기** — `.github/workflows/update.yml` 의 `cron: '17 */3 * * *'`.
UTC 기준이므로 한국시간에서 9를 빼면 됩니다. (예: 한국시간 07:20 → `20 22 * * *`)

**드라이버 한글 이름 / 팀 정보 / 서킷 설명 고치기** — `data/static.json`
`koName`(한글 이름), `notes`(부상·대체 출전 같은 메모), `teams`, `cars`, `calendar` 를 직접 수정하면 됩니다.
자동 갱신은 이 파일을 절대 건드리지 않습니다.

**시즌이 끝나고 2027년이 되면** — `scripts/update.py` 의 `SEASON = 2026` 을 바꾸고,
`data/static.json` 의 `calendar`(일정과 서킷 도면)를 새 시즌 것으로 교체하세요.

**뉴스 제목이 영어로 나오는 이유** — 자동 수집은 RSS 원문을 그대로 가져옵니다.
`data/live.json` 의 각 뉴스 항목에 `"ko": "한국어 제목"` 을 직접 넣으면 그 항목은 한국어로 표시되고,
다음 자동 갱신 때도 그 번역이 유지됩니다.

---

## 알아둘 점: 60일 규칙

GitHub은 **공개 저장소에 60일간 아무 활동이 없으면 예약 워크플로우를 자동으로 중지**시킵니다.
뉴스가 매일 바뀌므로 봇 커밋은 계속 쌓이지만, 봇 커밋만으로는 이 타이머가 초기화되지 않습니다.

- 중지되기 전에 GitHub이 메일을 보내며, 메일이나 Actions 탭에서 **버튼 한 번**으로 다시 켤 수 있습니다.
- 아예 신경 쓰기 싫다면: 저장소에 두 달에 한 번쯤 아무 커밋이나 하면 됩니다
  (README에 점 하나 찍고 저장해도 충분합니다).

---

## API 장애 처리와 검증

- 네트워크 오류, HTTP 408/429/5xx(530 포함), 잘못된 JSON은 최대 3회 재시도합니다.
  재시도 사이에는 지수 백오프와 임의 지연을 적용하며 숫자형 Retry-After를 최대 30초까지 반영합니다.
- 결승·스프린트는 모든 페이지 수집이 완료되어야 사용합니다. 중간 실패, 건수 불일치,
  기존 라운드 결과 누락은 전체 순위/결과 갱신을 보류합니다.
- 장애 시 유효한 기존 `data/live.json`이 있으면 파일과 갱신 시각을 그대로 보존하고
  Actions warning 및 실행 요약에 보류 사유를 기록합니다. 이는 최신 데이터 수집 성공을 뜻하지 않습니다.
  유효한 기존 데이터도 없으면 실패로 종료합니다.
- 정상 데이터는 임시 파일 작성 후 원자적으로 교체합니다. 뉴스와 시간표의 기존 보존 동작도 유지합니다.
- 업데이트 코드/테스트/워크플로 변경 시 main에서 자동 검증 및 갱신을 실행합니다.
  수동 실행은 Actions → F1 데이터 자동 갱신 → Run workflow를 사용하세요.
- 회귀 테스트: `python3 -m unittest discover -s tests -v` (외부 패키지 및 네트워크 불필요).

## 데이터 출처

- 순위·일정·결과: [Jolpica-F1 API](https://api.jolpi.ca/) (Ergast 호환, 무료)
- 뉴스: Formula1.com · Autosport · Motorsport.com 공식 RSS
- 서킷 도면: [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) GeoJSON 좌표를 메르카토르 투영해 SVG로 변환
- 국기: [lipis/flag-icons](https://github.com/lipis/flag-icons) (MIT)
- 드라이버 이미지는 공식 사진이 저작권 대상이라, 팀 컬러를 입힌 헬멧 일러스트를 코드로 그려 넣었습니다.

