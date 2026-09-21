# Discord 개인 이모티콘 봇

`/e` 하나로 개인 이모티콘을 **이름 / 키워드 / #감정**으로 검색해서 Discord 대화에 보내는 봇.
서버 채널, 1:1 DM, 그룹 DM 모두에서 동작한다. (사용자 설치 앱)

- 검색 패널은 **나만 보이고(ephemeral)**, 고른 이모티콘만 채널에 **PNG 첨부로 공개 전송**된다.
- 이모티콘은 **URL만 넣으면** 이미지가 자동 추출되어 512×512 투명 PNG로 정규화된다.
- 대상 환경: **Ubuntu 26.04 LTS (Python 3.14)**. Python 3.11 이상이면 동작한다.

먼저 읽을 것: [`docs/DISCORD_FEASIBILITY.md`](docs/DISCORD_FEASIBILITY.md) — Discord API에서
무엇이 되고 무엇이 안 되는지 정리한 문서. 특히 **봇은 사용자 이름으로 메시지를 보낼 수 없다**.

---

## 1. 빠른 시작 (Ubuntu 26.04)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

git clone <이 저장소> discord-emoticon-bot
cd discord-emoticon-bot

# Ubuntu는 시스템 파이썬에 직접 설치하지 못한다(PEP 668). 반드시 venv를 쓴다.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
$EDITOR .env          # DISCORD_BOT_TOKEN 입력

alembic upgrade head  # 테이블 생성
python -m app.main    # 봇 실행
```

## 2. Discord 앱 만들기 / 설치

1. <https://discord.com/developers/applications> → **New Application**
2. 왼쪽 **Bot** → **Reset Token** → 토큰을 `.env`의 `DISCORD_BOT_TOKEN`에 넣는다.
   - Privileged Intents는 **하나도 켤 필요 없다** (Message Content 미사용).
3. 왼쪽 **Installation**
   - Installation Contexts: **User Install**과 **Guild Install** 둘 다 체크
     - User Install: 내 계정에 추가 → 내가 있는 모든 서버·DM·그룹DM에서 `/e` 사용
     - Guild Install: 특정 서버에 추가 → 그 서버에서 공개 응답이 확실히 보장됨
   - Default Install Settings
     - User Install → scopes: `applications.commands`
     - Guild Install → scopes: `applications.commands`, `bot` / permissions: `Send Messages`
       (서버 커스텀 이모지까지 쓰려면 `Create Expressions` 추가)
   - Install Link의 **Discord Provided Link**를 열어 본인 계정에 설치한다.
4. 개발 중에는 `.env`의 `DISCORD_DEV_GUILD_ID`에 테스트 서버 ID를 넣으면 커맨드가 즉시 반영된다.
   비워두면 글로벌 등록이라 반영까지 시간이 걸린다.

> 서버에서 `Use External Apps` 권한이 꺼져 있고 봇이 그 서버에 설치되어 있지 않으면,
> 전송한 이모티콘이 **본인에게만** 보인다. 그 서버에 앱을 설치하면 해결된다.

## 3. 이모티콘 등록

### 3-1. Discord 안에서 (앱 소유자만)

```
/emoticon preview url:https://e.kakao.com/t/noorung-anyway-3
  → 후보 이미지 목록과 번호 표시

/emoticon add url:https://e.kakao.com/t/noorung-anyway-3
            name:누룽이_아무튼
            index:3
            emotions:#어이없음 #황당 #체념
            keywords:아무튼 누룽이
```

### 3-2. 터미널에서

```bash
python -m app.cli preview https://e.kakao.com/t/noorung-anyway-3
python -m app.cli add https://e.kakao.com/t/noorung-anyway-3 누룽이_아무튼 \
    --index 3 --emotions "황당,체념,어이없음" --keywords "아무튼,누룽이"

python -m app.cli list 아무튼
python -m app.cli search "#무덤덤"     # 검색 점수 확인
python -m app.cli tag 누룽이_아무튼 --emotions "귀찮음,체념"
python -m app.cli delete 누룽이_아무튼
```

등록 파이프라인: `URL → 페이지 분석 → 이미지 후보 추출 → 다운로드 → 위장 검사 →
첫 프레임 추출 → 투명 여백 제거 → 비율 유지 정사각 패딩 → 512×512 PNG → 해시 중복 검사 → 저장`

원본은 `data/images/original/`, 가공본은 `processed/`, 미리보기(128px)는 `preview/`에 남는다.

> 저작권: 카카오 이모티콘 등 유료/저작권 있는 이미지는 개인적인 사용 범위를 넘어
> 재배포·공유하지 않도록 주의한다.

## 4. 사용법

| 입력 | 동작 |
|---|---|
| `/e` | 최근 사용 · 즐겨찾기 + [😐 감정으로 찾기] 버튼 |
| `/e 아무튼` | 이름·키워드 검색 |
| `/e #황당` | 감정 태그 검색 (**유사 감정까지** 함께 나옴) |
| `/e 귀찮음` | 키워드이자 감정 태그로도 같이 검색 |

`/e` 입력 중에는 Autocomplete로 등록된 이름과 `#감정` 목록이 뜬다.

검색 결과 패널(나만 보임) → 드롭다운에서 선택 → 채널에 PNG로 전송된다.
`[◀ 이전] [▶ 다음]`으로 페이지를 넘기고 `[✖ 닫기]`로 닫는다.

기타 명령: `/emoticon favorite <이름>`(즐겨찾기 토글), `/emoticon stats`,
`/emoticon tag`, `/emoticon delete`, `/emoticon sync-emojis`.

## 5. 감정 태그

기본 태그 18종(`기쁨 웃김 슬픔 분노 황당 어이없음 체념 무덤덤 귀찮음 놀람 당황 감동 축하 동의 거절 의문 생각 피곤`)이
최초 실행 시 자동으로 들어간다. 하나의 이모티콘에 여러 감정을 붙일 수 있다(N:M).

감정 간 유사도 그래프가 있어서 `#무덤덤`으로 찾으면 `귀찮음(0.7) 체념(0.7) 어이없음(0.5)`도
낮은 점수로 함께 나온다. 정의 위치: `app/emotion/tags.py`.

검색 정렬 점수: 이름 완전일치 100 / 시작일치 70 / 부분일치 50 / 감정 80×유사도 /
키워드 60·40 / 최근 사용 보너스 최대 +12.

## 6. 운영 배포

### Docker

```bash
cp .env.example .env && $EDITOR .env
docker compose up -d --build
docker compose logs -f bot
```

### systemd

```bash
sudo useradd --system --create-home --home-dir /opt/discord-emoticon-bot emoticon
sudo cp -r . /opt/discord-emoticon-bot && cd /opt/discord-emoticon-bot
sudo -u emoticon python3 -m venv .venv
sudo -u emoticon .venv/bin/pip install -r requirements.txt
sudo chmod 600 .env && sudo chown emoticon:emoticon .env

sudo cp deploy/emoticon-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now emoticon-bot
journalctl -u emoticon-bot -f
```

### PostgreSQL로 옮기기

```bash
pip install "asyncpg>=0.30"
# .env
DATABASE_URL=postgresql+asyncpg://emoticon:password@localhost:5432/emoticon
alembic upgrade head
```

## 7. 개발

```bash
pip install -r requirements-dev.txt
pytest -q                  # 42 tests

# 스키마를 바꿨을 때
alembic revision --autogenerate -m "설명"
alembic upgrade head
```

테스트는 로컬 HTTP 서버를 띄워 등록 전체 경로(추출→다운로드→변환→중복검사→저장)까지 검증한다.
Discord 게이트웨이 연결 없이 Components V2 페이로드와 커맨드 설치 컨텍스트도 검사한다.

## 8. 프로젝트 구조

```
app/
├── main.py              실행 진입점
├── cli.py               관리 CLI (등록/수정/삭제/검색)
├── config.py            환경변수 설정
├── db/                  SQLAlchemy 모델 · 세션
├── crawler/             fetcher(SSRF 방어) · base(Adapter) · kakao · generic
├── image/               validator(위장·폭탄 방어) · processor(정규화·해시)
├── emoticon/            repository(DB) · service(등록 파이프라인)
├── emotion/             tags(정의) · service(seed·유사도 확장)
├── search/              service(질의 파싱·스코어링)
├── storage/             base(Protocol) · local(파일)
└── discordbot/
    ├── bot.py           Bot · 커맨드 동기화
    ├── emoji_sync.py    Application-Owned Emoji 등록
    ├── commands/        search(/e) · emoticon(/emoticon ...)
    └── views/           search(결과 패널) · emotion(감정 선택)
migrations/              Alembic
tests/                   pytest
docs/DISCORD_FEASIBILITY.md
deploy/emoticon-bot.service
```

새 사이트 지원을 추가하려면 `app/crawler/`에 파서 하나를 만들고
`app/crawler/base.py`의 `get_parser()` 목록에 넣으면 된다. 다른 코드는 건드리지 않는다.

## 9. 보안

- 토큰은 `.env`로만 주입하고 커밋하지 않는다(`.gitignore`). `discord.http` 디버그 로그도 꺼 둔다.
- URL 다운로드는 스킴·포트 화이트리스트, **사설/루프백/링크로컬 IP 차단**(클라우드 메타데이터 169.254.169.254 포함),
  리다이렉트 매 홉 재검사, 크기 상한, 타임아웃을 적용한다.
- 이미지는 Content-Type을 믿지 않고 디코딩 결과로 판정한다. HTML/JS 위장과 decompression bomb을 막는다.
- 저장 경로는 루트 밖으로 나가는 경로를 거부한다.
- `/emoticon` 변경 계열 명령은 앱 소유자만 실행할 수 있고, 검색 패널은 실행한 본인만 조작할 수 있다.
- `ALLOW_PRIVATE_NETWORK=true`는 로컬 테스트 전용이다. **운영에서 켜지 말 것** (SSRF 방어가 꺼진다).

## 10. 지금 구현되지 않은 것

- AI 감정 분석 자동 추천: `app/search/service.py`와 `app/emotion/service.py`가 분리되어 있어,
  문장 → 감정 태그 추정 함수만 추가하면 기존 검색 경로를 그대로 쓸 수 있다.
- 관리자 Web UI: 등록·수정·삭제는 `/emoticon` 명령과 CLI로 처리한다.
- S3 저장소: `app/storage/base.py`의 Protocol만 구현하면 교체된다.
- 애니메이션 이모티콘: 현재는 첫 프레임만 정적 PNG로 저장한다.
