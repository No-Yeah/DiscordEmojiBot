# Discord 개인 이모티콘 봇

`/e` 하나로 개인 이모티콘을 **이름 · 키워드 · #감정**으로 검색해서 Discord 대화에 보내는 봇입니다.
서버 채널, 1:1 DM, 그룹 DM 어디서나 동작합니다.

- 검색 패널은 **나에게만 보이고**, 고른 이모티콘만 채팅에 PNG로 올라갑니다.
- 이모티콘은 **URL만 넣으면** 이미지가 자동 추출되어 512×512 투명 PNG로 정규화됩니다.
- 하나의 이모티콘에 여러 감정 태그를 붙일 수 있고, `#무덤덤`으로 찾으면 `귀찮음·체념` 같은 **비슷한 감정**도 함께 나옵니다.
- 검증 환경: Ubuntu 26.04 LTS (Python 3.14). Python 3.11 이상이면 동작합니다.

> Discord API로 가능한 것과 불가능한 것은 [`docs/DISCORD_FEASIBILITY.md`](docs/DISCORD_FEASIBILITY.md)에 정리되어 있습니다.
> 요약: **봇은 사용자 이름으로 메시지를 보낼 수 없습니다.** 고른 이모티콘은 앱 메시지로 전송되고 `{사용자} used /e`로 표시됩니다.

---

## 목차

1. [Discord 앱 만들기](#1-discord-앱-만들기)
2. [설치](#2-설치)
3. [실행](#3-실행)
4. [이모티콘 등록](#4-이모티콘-등록)
5. [감정 태깅 웹페이지 (권장)](#5-감정-태깅-웹페이지-권장)
6. [사용법](#6-사용법)
7. [명령어 전체 목록](#7-명령어-전체-목록)
8. [감정 태그](#8-감정-태그)
9. [24시간 운영](#9-24시간-운영)
10. [설정 항목](#10-설정-항목)
11. [문제 해결](#11-문제-해결)
12. [프로젝트 구조](#12-프로젝트-구조)
13. [개발](#13-개발)

---

## 1. Discord 앱 만들기

봇을 실행하기 전에 Discord에서 앱을 먼저 만들어야 합니다.

1. <https://discord.com/developers/applications> 접속 → **New Application** → 이름 입력
2. 왼쪽 **Bot** 메뉴
   - **Reset Token** → 표시되는 문자열 복사 (비밀번호입니다. 외부에 노출 금지)
   - Privileged Gateway Intents는 **하나도 켜지 않아도 됩니다** (일반 메시지를 읽지 않습니다)
3. 왼쪽 **Installation** 메뉴
   - **Installation Contexts**: `User Install`, `Guild Install` 둘 다 체크

     | 설치 방식 | 효과 |
     |---|---|
     | User Install | 내 계정에 추가. 내가 있는 **모든 서버 · DM · 그룹 DM**에서 `/e` 사용 가능 |
     | Guild Install | 특정 서버에 추가. 그 서버에서 **공개 전송이 확실히 보장**됨 |

   - **Default Install Settings**
     - User Install → Scopes: `applications.commands`
     - Guild Install → Scopes: `applications.commands`, `bot` / Permissions: `Send Messages`
       (서버 커스텀 이모지 기능까지 쓰려면 `Create Expressions` 추가)
   - **Install Link**의 `Discord Provided Link`를 복사해 브라우저로 열고 본인 계정에 설치

---

## 2. 설치

Ubuntu는 시스템 Python에 패키지를 직접 설치할 수 없습니다(PEP 668). 반드시 가상환경을 사용합니다.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

git clone https://github.com/<사용자>/discord-emoticon-bot.git
cd discord-emoticon-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

설정 파일을 만들고 토큰을 넣습니다.

```bash
cp .env.example .env
nano .env
```

```ini
DISCORD_BOT_TOKEN=1번에서_복사한_토큰
DISCORD_DEV_GUILD_ID=테스트서버_ID   # 선택. 넣으면 명령어가 즉시 반영됨
```

> 서버 ID는 Discord 설정 → 고급 → 개발자 모드를 켠 뒤 서버 아이콘 우클릭 → `서버 ID 복사`로 얻습니다.
> 비워두면 글로벌 등록이라 명령어가 나타나기까지 최대 1시간 걸립니다.

---

## 3. 실행

```bash
alembic upgrade head    # 데이터베이스 테이블 생성 (최초 1회, 업데이트 후에도 실행)
python -m app.main      # 봇 실행
```

로그에 `logged in as ...` 와 `synced N commands` 가 보이면 정상입니다.
이 터미널을 닫으면 봇도 멈춥니다. 계속 켜두려면 [8. 24시간 운영](#8-24시간-운영)을 참고하세요.

---

## 4. 이모티콘 등록

이모티콘은 **이미지 하나 = DB 한 개** 단위로 등록됩니다. 한 팩(예: 24종)을 넣는 방법은 두 가지입니다.

- **팩 통째로 (권장)**: `add-pack` 으로 감정 없이 전부 등록 → [태깅 페이지](#5-감정-태깅-웹페이지-권장)에서 이미지를 보며 감정을 개별로 답니다.
- **하나씩**: `add` 로 후보 번호를 골라 등록하면서 감정까지 함께 답니다.

> 감정은 팩 전체에 일괄로 붙는 게 아니라 **이모티콘마다 따로** 답니다. 그래서 팩 등록(`add-pack`)은 감정을 받지 않습니다.

### 팩 통째로 등록 (add-pack)

```
/emoticon add-pack
  url:https://e.kakao.com/t/noorung-anyway-3
  name:누룽이
  keywords:누룽이
```

→ 찾은 이미지가 `누룽이_1`, `누룽이_2`, … 로 감정 없이 한꺼번에 등록됩니다.
완전히 같은 이미지(중복)와 내려받기 실패는 자동으로 건너뛰고 결과를 알려줍니다.
등록 후 태깅 페이지에서 각 이미지에 감정을 답니다.

터미널에서도 같습니다.

```bash
python -m app.cli add-pack https://e.kakao.com/t/noorung-anyway-3 누룽이 --keywords "누룽이" --limit 30
```

| 항목 | 설명 |
|---|---|
| `url` | 이모티콘 묶음(팩) 페이지 주소 (필수) |
| `name` | 이름 접두어. `누룽이` → `누룽이_1`, `누룽이_2` … (필수) |
| `keywords` | 모든 항목에 공통으로 붙일 키워드 |
| `limit` | 최대 등록 개수 (기본: 전부) |

### 하나씩 등록 (add)

먼저 URL에 어떤 이미지들이 들어 있는지 확인합니다.

```
/emoticon preview url:https://e.kakao.com/t/noorung-anyway-3
```

번호가 붙은 후보 목록이 나옵니다. 원하는 번호를 골라 등록합니다.

```
/emoticon add
  url:https://e.kakao.com/t/noorung-anyway-3
  name:누룽이_아무튼
  index:3
  emotions:#어이없음 #황당 #체념
  keywords:아무튼 누룽이
```

| 항목 | 설명 |
|---|---|
| `url` | 이모티콘 페이지 주소 또는 이미지 주소 (필수) |
| `name` | 이모티콘 이름. 검색에 쓰입니다 (필수) |
| `index` | preview에서 본 후보 번호. 기본 1 |
| `emotions` | 감정 태그. 공백이나 쉼표로 구분 |
| `keywords` | 검색용 키워드. 공백이나 쉼표로 구분 |

### 터미널에서 등록

여러 개를 한 번에 넣을 때 편합니다.

```bash
source .venv/bin/activate

python -m app.cli preview https://e.kakao.com/t/noorung-anyway-3
python -m app.cli add https://e.kakao.com/t/noorung-anyway-3 누룽이_아무튼 \
    --index 3 --emotions "황당,체념,어이없음" --keywords "아무튼,누룽이"

python -m app.cli list 아무튼          # 목록 보기
python -m app.cli search "#무덤덤"      # 검색 결과와 점수 확인
python -m app.cli tag 누룽이_아무튼 --emotions "귀찮음,체념"
python -m app.cli delete 누룽이_아무튼
```

### 등록 과정에서 일어나는 일

```
URL 입력 → 페이지 분석 → 이미지 후보 추출 → 다운로드 → 위장 파일 검사
→ 첫 프레임 추출 → 투명 여백 제거 → 비율 유지한 채 정사각 패딩
→ 512×512 투명 PNG → 해시 중복 검사 → 저장
```

원본은 `data/images/original/`, 가공본은 `processed/`, 미리보기는 `preview/`에 저장됩니다.
같은 이미지를 다른 URL로 등록하면 중복으로 걸러집니다.

> **저작권 주의**: 카카오 이모티콘 등 저작권이 있는 이미지는 개인적인 사용 범위를 넘어 재배포·공유하지 마세요.

---

## 5. 감정 태깅 웹페이지 (권장)

터미널에서는 이미지가 보이지 않아 어떤 이모티콘에 무슨 감정을 달지 알기 어렵습니다.
그래서 등록된 이모티콘을 **썸네일 격자로 띄우고 클릭으로 감정을 다는 로컬 웹페이지**를 제공합니다.
새 의존성 없이 파이썬 표준 라이브러리로 동작하며, **이 컴퓨터에서만(localhost)** 열립니다.

### 추천 작업 흐름

1. `/emoticon add-pack` (또는 CLI `add-pack`)으로 팩을 **감정 없이** 한꺼번에 등록해 둔다.
2. 태깅 페이지를 켠다.

   ```bash
   source .venv/bin/activate
   python -m app.tagging.server          # http://127.0.0.1:8000
   # 포트를 바꾸려면: python -m app.tagging.server --port 9000
   ```

3. 브라우저로 <http://127.0.0.1:8000> 접속.
4. 각 이모티콘 카드 아래의 **감정 칩을 눌러** 태깅한다. **누르는 즉시 저장**된다.

### 화면

```
┌───────────────────────────────────────────────────────────┐
│ 이모티콘 감정 태깅   4/4개   [이름 검색] ☐감정 없는 것만    │
│                                   [새 감정 추가 후 Enter]  │
├───────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐           │
│  │  (이미지)  │  │  (이미지)  │  │  (이미지)  │           │
│  │ 누룽이_아무튼│  │ 누룽이_웃음 │  │ 누룽이_피곤 │          │
│  │ 😀기쁨 😂웃김│  │ 😀기쁨 😂웃김│  │ 😀기쁨 …    │          │
│  │ 😐무덤덤 …  │  │ …          │  │             │          │
│  └────────────┘  └────────────┘  └────────────┘           │
└───────────────────────────────────────────────────────────┘
```

- 칩이 **켜진 색**이면 그 감정이 달린 상태. 다시 누르면 해제됩니다.
- **감정 없는 것만** 체크: 아직 태깅하지 않은 이모티콘만 남겨 집중 작업할 수 있습니다.
- **이름 검색**: 이름·키워드로 격자를 좁힙니다.
- **새 감정 추가**: 기본 18종에 없는 태그(예: `뿌듯`)를 입력하면 모든 카드에 칩으로 나타나고, 카드에서 누르면 그 이모티콘에 적용됩니다.

여기서 단 감정은 봇의 `/e #감정` 검색에 곧바로 반영됩니다(같은 데이터베이스).

> 봇을 systemd/Docker로 계속 돌리는 중에도 태깅 페이지를 함께 켜도 됩니다(SQLite WAL로 동시 접근 가능).
> 인증이 없으므로 `--host 0.0.0.0` 같은 외부 공개는 하지 마세요.

---

## 6. 사용법


| 입력 | 결과 |
|---|---|
| `/e` | 최근 사용 · 즐겨찾기 + `[😐 감정으로 찾기]` 버튼 |
| `/e 아무튼` | 이름과 키워드로 검색 |
| `/e #황당` | 감정 태그로 검색 (비슷한 감정까지 함께) |
| `/e 귀찮음` | 키워드이자 감정 태그로 동시 검색 |

`/e` 를 입력하는 동안 등록된 이름과 `#감정` 목록이 자동완성으로 뜹니다.

검색하면 이런 패널이 **나에게만** 표시됩니다.

```
┌──────────────────────────────────────────┐
│ 검색 결과: 아무튼 · 12개 (페이지 1/2)      │
├──────────────────────────────────────────┤
│  🖼️   🖼️   🖼️   🖼️                       │
│  🖼️   🖼️   🖼️   🖼️                       │
│                                          │
│  1. 누룽이_아무튼  #황당 #체념             │
│  2. 아무튼_그래    #무덤덤                 │
├──────────────────────────────────────────┤
│  [ 보낼 이모티콘을 고르세요  ▾ ]           │
│  [◀ 이전] [▶ 다음] [✖ 닫기]               │
└──────────────────────────────────────────┘
```

드롭다운에서 하나를 고르면 그 이모티콘이 채팅에 PNG로 올라갑니다.

---

## 7. 명령어 전체 목록

| 명령어 | 설명 | 권한 |
|---|---|---|
| `/e [검색어]` | 이모티콘 검색 후 전송 | 누구나 |
| `/emoticon favorite <이름>` | 즐겨찾기 등록/해제 | 누구나 |
| `/emoticon stats` | 등록 현황 보기 | 누구나 |
| `/emoticon preview <url>` | URL의 이미지 후보 확인 | 앱 소유자 |
| `/emoticon add <url> <이름> ...` | 이모티콘 하나 등록 | 앱 소유자 |
| `/emoticon add-pack <url> <접두어> ...` | 팩 전체를 감정 없이 등록 | 앱 소유자 |
| `/emoticon tag <이름> ...` | 이름·감정·키워드 수정 | 앱 소유자 |
| `/emoticon delete <이름>` | 삭제 | 앱 소유자 |
| `/emoticon sync-emojis` | 앱 이모지 일괄 등록 | 앱 소유자 |

CLI: `init-db` · `preview` · `add` · `add-pack` · `list` · `tag` · `delete` · `search`
(`python -m app.cli <명령> --help`)

---

## 8. 감정 태그

첫 실행 시 기본 태그 18종이 자동으로 들어갑니다.

```
기쁨 웃김 슬픔 분노 황당 어이없음 체념 무덤덤 귀찮음
놀람 당황 감동 축하 동의 거절 의문 생각 피곤
```

하나의 이모티콘에 여러 감정을 붙일 수 있고(N:M), 감정끼리 유사도가 연결되어 있습니다.

```
무덤덤 ─┬─ 귀찮음 (0.7)
        ├─ 체념   (0.7)
        └─ 어이없음 (0.5)
```

`/e #무덤덤` 으로 검색하면 `무덤덤`이 위에, 유사 감정이 아래에 표시됩니다.
태그와 유사도 정의는 `app/emotion/tags.py`에서 수정합니다. 없는 태그는 등록할 때 자동 생성됩니다.

**검색 정렬 점수**

| 조건 | 점수 |
|---|---|
| 이름 완전 일치 | 100 |
| 이름 시작 일치 | 70 |
| 이름 부분 일치 | 50 |
| 감정 태그 일치 | 80 × 유사도 |
| 키워드 완전 / 부분 일치 | 60 / 40 |
| 최근 사용 보너스 | 최대 +12 |

---

## 9. 24시간 운영

### Docker

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f bot
```

### systemd

```bash
sudo useradd --system --create-home --home-dir /opt/discord-emoticon-bot emoticon
sudo cp -r . /opt/discord-emoticon-bot
cd /opt/discord-emoticon-bot

sudo -u emoticon python3 -m venv .venv
sudo -u emoticon .venv/bin/pip install -r requirements.txt
sudo chown emoticon:emoticon .env && sudo chmod 600 .env

sudo cp deploy/emoticon-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now emoticon-bot

journalctl -u emoticon-bot -f     # 로그 확인
```

### PostgreSQL로 옮기기

```bash
pip install "asyncpg>=0.30"
# .env 수정
# DATABASE_URL=postgresql+asyncpg://emoticon:password@localhost:5432/emoticon
alembic upgrade head
```

---

## 10. 설정 항목

`.env` 파일에서 바꿉니다. 전체 목록은 `.env.example` 참고.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_BOT_TOKEN` | — | 봇 토큰 (필수) |
| `DISCORD_DEV_GUILD_ID` | 비어 있음 | 테스트 서버 ID. 넣으면 명령어 즉시 반영 |
| `SEND_STYLE` | `image` | `image` = PNG 첨부(크게) / `emoji` = 앱 이모지(작게) |
| `APP_EMOJI_ENABLED` | `false` | 켜면 검색 드롭다운에 썸네일 아이콘 표시 |
| `DATABASE_URL` | SQLite | PostgreSQL로 교체 가능 |
| `STORAGE_DIR` | `./data/images` | 이미지 저장 위치 |
| `IMAGE_SIZE` | `512` | 정규화 이미지 한 변 |
| `SEARCH_PAGE_SIZE` | `8` | 한 페이지에 보여줄 개수 (최대 10) |
| `ALLOW_PRIVATE_NETWORK` | `false` | **운영에서 켜지 마세요.** SSRF 방어가 해제됩니다 |
| `LOG_LEVEL` | `INFO` | 로그 수준 |

---

## 11. 문제 해결

**`/e` 가 Discord에 나타나지 않습니다**
글로벌 명령은 반영에 시간이 걸립니다. `.env`에 `DISCORD_DEV_GUILD_ID`를 넣고 재시작하면 즉시 반영됩니다.
Discord 클라이언트를 `Ctrl+R`로 새로고침해 보세요.

**전송했는데 나에게만 보입니다**
그 서버에서 `Use External Apps` 권한이 꺼져 있고 봇이 서버에 설치되어 있지 않은 경우입니다.
Install Link로 **그 서버에도** 봇을 추가하면 해결됩니다.

**`/emoticon preview` 에서 후보가 안 나옵니다**
사이트가 자바스크립트로 이미지를 그리는 경우입니다. 이미지 주소를 직접 복사해서 `url`에 넣으면 등록됩니다.
(브라우저에서 이미지 우클릭 → `이미지 주소 복사`)

**`externally-managed-environment` 오류**
가상환경을 활성화하지 않은 상태입니다. `source .venv/bin/activate` 후 다시 시도하세요.

**`DISCORD_BOT_TOKEN이 설정되지 않았습니다`**
`.env` 파일이 없거나 토큰이 비어 있습니다. `cp .env.example .env` 후 토큰을 넣으세요.

**`Improper token has been passed`**
토큰이 잘못되었습니다. Developer Portal에서 Reset Token으로 새로 발급받으세요.

---

## 12. 프로젝트 구조

```
app/
├── main.py              실행 진입점
├── cli.py               관리 CLI
├── config.py            환경변수 설정
├── db/                  모델 · 세션
├── crawler/             fetcher(SSRF 방어) · base(Adapter) · kakao · generic
├── image/               validator(위장 파일 방어) · processor(정규화 · 해시)
├── emoticon/            repository(DB) · service(등록 파이프라인)
├── emotion/             tags(정의) · service(seed · 유사도 확장)
├── search/              service(질의 파싱 · 스코어링)
├── storage/             base(Protocol) · local(파일)
├── discordbot/
│   ├── bot.py           Bot · 커맨드 동기화
│   ├── emoji_sync.py    Application-Owned Emoji 등록
│   ├── commands/        search(/e) · emoticon(/emoticon ...)
│   └── views/           search(결과 패널) · emotion(감정 선택)
└── tagging/
    └── server.py        감정 태깅 웹페이지 (표준 라이브러리)

migrations/              Alembic 마이그레이션
tests/                   pytest (42개)
docs/                    Discord API 조사 문서
deploy/                  systemd 유닛
```

새 사이트를 지원하려면 `app/crawler/`에 파서를 하나 추가하고 `base.py`의 `get_parser()` 목록에 넣으면 됩니다.
다른 코드는 수정할 필요가 없습니다.

---

## 13. 개발

```bash
pip install -r requirements-dev.txt
pytest -q

# 모델을 수정했을 때
alembic revision --autogenerate -m "설명"
alembic upgrade head
```

테스트는 로컬 HTTP 서버를 띄워 등록 전체 경로(추출 → 다운로드 → 변환 → 중복 검사 → 저장)를 검증하고,
Discord 연결 없이 Components V2 페이로드와 커맨드 설치 컨텍스트도 확인합니다.

### 보안 설계

- 토큰은 `.env`로만 주입하고 커밋하지 않습니다. `discord.http` 디버그 로그도 차단합니다.
- URL 다운로드는 스킴·포트 화이트리스트, 사설·루프백·링크로컬 IP 차단(클라우드 메타데이터 `169.254.169.254` 포함),
  리다이렉트 매 홉 재검사, 크기 상한, 타임아웃을 적용합니다.
- 이미지는 Content-Type을 신뢰하지 않고 디코딩 결과로 판정합니다. HTML/JS 위장과 decompression bomb을 차단합니다.
- 저장 경로는 루트를 벗어나는 경로를 거부합니다.
- `/emoticon` 변경 명령은 앱 소유자만, 검색 패널은 실행한 본인만 조작할 수 있습니다.

### 아직 없는 기능

- **AI 감정 분석 자동 추천** — 문장에서 감정을 추정하는 함수만 추가하면 기존 검색 경로를 그대로 사용합니다.
- **관리자 Web UI** — 등록·수정·삭제는 `/emoticon` 명령과 CLI로 처리합니다. (감정 태깅은 [5번](#5-감정-태깅-웹페이지-권장) 웹페이지 제공)
- **S3 저장소** — `app/storage/base.py`의 Protocol만 구현하면 교체됩니다.
- **애니메이션 이모티콘** — 현재는 첫 프레임만 정적 PNG로 저장합니다.
