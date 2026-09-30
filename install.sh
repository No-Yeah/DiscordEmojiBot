#!/usr/bin/env bash
# 디스코드 이모티콘 봇 + 관리자 웹 설치 (Ubuntu 26.04)
#   git clone ... && cd emoji-bot && sudo ./install.sh
# 다시 실행하면 코드만 갱신하고 기존 토큰, DB, 이미지, 관리자 계정은 유지한다.
set -euo pipefail

APP=/opt/emoji-bot
DATA=/var/lib/emoji-bot
CONF=/etc/emoji-bot
ENV_FILE=$CONF/emoji-bot.env
SVC_USER=emojibot
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "관리자 권한이 필요합니다: sudo ./install.sh"; exit 1; }

say() { printf '\n\033[1;35m▶ %s\033[0m\n' "$*"; }

say "필수 패키지 설치"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl rsync tzdata >/dev/null

# ---- 입력 ----
OLD_TOKEN=""
[[ -f $ENV_FILE ]] && OLD_TOKEN=$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)

while true; do
  if [[ -n $OLD_TOKEN ]]; then
    read -rsp "디스코드 봇 토큰 (Enter = 기존 토큰 유지): " TOKEN; echo
    TOKEN=${TOKEN:-$OLD_TOKEN}
  else
    read -rsp "디스코드 봇 토큰: " TOKEN; echo
  fi
  TOKEN=$(printf '%s' "$TOKEN" | tr -d '[:space:]')
  # 토큰이 프로세스 목록에 보이지 않도록 헤더를 표준입력으로 넘긴다
  if ME=$(curl -fsS -H @- https://discord.com/api/v10/users/@me <<<"Authorization: Bot $TOKEN" 2>/dev/null); then
    break
  fi
  echo "토큰을 확인하지 못했습니다. 개발자 포털의 Bot → Reset Token 값을 다시 붙여넣으세요."
done
APP_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$ME")
BOT_NAME=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])' <<<"$ME")
echo "봇 확인: $BOT_NAME ($APP_ID)"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
OLD_PORT=$( [[ -f $ENV_FILE ]] && grep -E '^WEB_PORT=' "$ENV_FILE" | cut -d= -f2- || true )
OLD_URL=$( [[ -f $ENV_FILE ]] && grep -E '^WEB_BASE_URL=' "$ENV_FILE" | cut -d= -f2- || true )
PORT=${OLD_PORT:-8080}
BASE_URL=${OLD_URL:-http://${IP:-localhost}:$PORT}
read -rp "관리자 웹 주소 [$BASE_URL]: " IN_URL
BASE_URL=${IN_URL:-$BASE_URL}
PORT=$(python3 -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(p.port or (443 if p.scheme=="https" else 80))' "$BASE_URL")
[[ -n $OLD_URL && $BASE_URL == "$OLD_URL" ]] && PORT=${OLD_PORT:-$PORT}

OLD_IMG=$( [[ -f $ENV_FILE ]] && grep -E '^EMOJI_IMG_DIR=' "$ENV_FILE" | cut -d= -f2- || true )
DEFAULT_IMG=${OLD_IMG:-$DATA/images}
while true; do
  read -rp "이모티콘 이미지 저장 폴더 [$DEFAULT_IMG]: " IMG_DIR
  IMG_DIR=${IMG_DIR:-$DEFAULT_IMG}
  IMG_DIR=${IMG_DIR%/}
  if [[ $IMG_DIR != /* || $IMG_DIR == *" "* ]]; then
    echo "공백 없는 절대 경로(/로 시작)로 입력하세요."; continue
  fi
  case "$IMG_DIR/" in
    /|/bin/*|/boot/*|/dev/*|/etc/*|/lib*|/proc/*|/run/*|/sbin/*|/sys/*|/usr/*|"$APP"/*|"$CONF"/*)
      echo "시스템 폴더나 프로그램 폴더($APP)는 쓸 수 없습니다. 다른 경로를 입력하세요."; continue ;;
  esac
  break
done

# ---- 코드와 가상환경 ----
say "프로그램 설치 ($APP)"
id "$SVC_USER" &>/dev/null || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SVC_USER"
install -d -m 755 "$APP"
rsync -a --delete --exclude .git --exclude .venv "$SRC/" "$APP/"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
install -d -m 750 -o "$SVC_USER" -g "$SVC_USER" "$DATA"
install -d -m 750 -o "$SVC_USER" -g "$SVC_USER" "$IMG_DIR"
if ! sudo -u "$SVC_USER" test -w "$IMG_DIR"; then
  echo "서비스 계정($SVC_USER)이 $IMG_DIR 에 쓸 수 없습니다. 상위 폴더 권한을 확인하세요 (예: chmod o+x 상위폴더)."
  exit 1
fi
if [[ -n $OLD_IMG && $OLD_IMG != "$IMG_DIR" && -d $OLD_IMG ]]; then
  COUNT=$(find "$OLD_IMG" -maxdepth 1 -type f | wc -l)
  if [[ $COUNT -gt 0 ]]; then
    rsync -a "$OLD_IMG/" "$IMG_DIR/" && chown -R "$SVC_USER:$SVC_USER" "$IMG_DIR"
    echo "기존 이미지 ${COUNT}개를 $IMG_DIR 로 복사했습니다. (원래 폴더 $OLD_IMG 는 확인 후 직접 지우세요)"
  fi
fi
cd "$APP"

# ---- 설정 파일 (토큰은 여기에만 저장, 소유자 root / 그룹 emojibot 읽기) ----
say "설정 저장 ($ENV_FILE)"
install -d -m 750 -o root -g "$SVC_USER" "$CONF"
SECRET=$( [[ -f $ENV_FILE ]] && grep -E '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true )
SECRET=${SECRET:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}
umask 027
cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$TOKEN
SECRET_KEY=$SECRET
WEB_PORT=$PORT
WEB_BASE_URL=$BASE_URL
EMOJI_DATA=$DATA
EMOJI_IMG_DIR=$IMG_DIR
EMOJI_SIZE=180
TZ=Asia/Seoul
PYTHONUNBUFFERED=1
EOF
umask 022
chown root:"$SVC_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# ---- 관리자 계정 (처음 설치할 때만) ----
run_as_app() {
  # 설정 파일 값을 환경변수로 넘겨 서비스 계정으로 실행 (ADMIN_* 는 명령줄에 노출되지 않게 환경으로만 전달)
  sudo -u "$SVC_USER" --preserve-env=ADMIN_USER,ADMIN_PW \
    bash -c 'set -a; . "$0"; set +a; exec "$@"' "$ENV_FILE" "$@"
}
HAS_ADMIN=$(run_as_app "$APP/.venv/bin/python" -c 'from emojibot import db; db.init()
with db.conn() as c: print(1 if c.execute("SELECT 1 FROM admin").fetchone() else 0)' 2>/dev/null || echo 0)
GEN_PW=""
if [[ $HAS_ADMIN != 1 ]]; then
  say "관리자 웹 계정 만들기"
  read -rp "관리자 아이디 [admin]: " ADMIN_USER; ADMIN_USER=${ADMIN_USER:-admin}
  while true; do
    read -rsp "관리자 비밀번호 (8자 이상, Enter = 자동 생성): " ADMIN_PW; echo
    if [[ -z $ADMIN_PW ]]; then GEN_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))'); ADMIN_PW=$GEN_PW; break; fi
    [[ ${#ADMIN_PW} -ge 8 ]] && break
    echo "8자 이상으로 입력하세요."
  done
  export ADMIN_USER ADMIN_PW
  run_as_app "$APP/.venv/bin/python" -m emojibot.admin
  unset ADMIN_PW
  say "봇 프로필 사진·배너 설정"
  run_as_app "$APP/.venv/bin/python" -m emojibot.set_profile || true
fi

# ---- systemd ----
say "서비스 등록"
# 서비스는 DB 폴더와 고른 이미지 폴더에만 쓸 수 있다. /home 아래를 고르면 ProtectHome 을 끈다.
HOME_PROTECT=true
[[ $IMG_DIR == /home/* || $IMG_DIR == /root/* ]] && HOME_PROTECT=false
for unit in emoji-bot emoji-web; do
  sed -e "s|^ReadWritePaths=.*|ReadWritePaths=$DATA $IMG_DIR|" \
      -e "s|^ProtectHome=.*|ProtectHome=$HOME_PROTECT|" \
      "$APP/systemd/$unit.service" > "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
systemctl enable --now emoji-bot.service emoji-web.service
systemctl restart emoji-bot.service emoji-web.service

if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" >/dev/null && echo "방화벽(ufw)에 $PORT/tcp를 열었습니다."
fi

sleep 3
say "설치 완료"
systemctl --no-pager --lines=0 status emoji-bot.service emoji-web.service | grep -E '●|Active:' || true
cat <<EOF

관리자 웹:   $BASE_URL
이미지 폴더: $IMG_DIR
관리자 ID:   ${ADMIN_USER:-(기존 계정 유지)}
EOF
[[ -n $GEN_PW ]] && echo "관리자 비밀번호(자동 생성, 지금 한 번만 표시): $GEN_PW"
cat <<EOF

서버에 봇 초대:
  https://discord.com/oauth2/authorize?client_id=$APP_ID&scope=bot+applications.commands&permissions=51200
내 계정에 설치 (1:1 DM에서 사용):
  https://discord.com/oauth2/authorize?client_id=$APP_ID&integration_type=1&scope=applications.commands

다음 할 일: 디스코드에서 /e help 를 한 번 입력 → 관리자 웹 '디스코드 유저'에서 봇 사용 허용
로그: journalctl -u emoji-bot -f  /  journalctl -u emoji-web -f
EOF
