#!/usr/bin/env bash
#
# kcalAI-model 초기 프로비저닝 — Lightsail Ubuntu(2GB, 서울), Postgres 동거.
# 한 번 실행한다(재실행해도 대체로 안전: idempotent 하게 작성). sudo 권한 필요.
#
# 사용 전 아래 CONFIG를 확인/수정하거나 환경변수로 넘긴다:
#   APP_USER=ubuntu APP_DIR=/opt/kcalAI-model DB_PASSWORD=... GEMINI_API_KEY=... \
#   sudo -E bash deploy/provision.sh
#
# secret은 스크립트에 하드코딩하지 않는다. DB_PASSWORD·GEMINI_API_KEY는 환경변수 또는
# 프롬프트로 받고, AUTH_CODE_PEPPER·HEALTH_ENCRYPTION_KEY는 난수로 생성한다.
set -euo pipefail

# ---- CONFIG (환경변수로 덮어쓸 수 있음) ----
APP_USER="${APP_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/opt/kcalAI-model}"
DB_NAME="${DB_NAME:-kcal}"
DB_USER="${DB_USER:-kcal}"
SERVICE_NAME="kcalai"

log() { echo -e "\n\033[1;34m[provision]\033[0m $*"; }
die() { echo -e "\033[1;31m[provision] $*\033[0m" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "sudo(root)로 실행하세요."
[ -f "$APP_DIR/main.py" ] || die "$APP_DIR 에 repo가 없습니다. 먼저 release 브랜치를 clone 하세요 (DEPLOY.md 3단계)."

# ---- 1. 시스템 패키지 ----
log "시스템 패키지 설치"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-pip postgresql postgresql-contrib git curl ca-certificates

# ---- 2. Postgres: 유저·DB·확장 (idempotent) ----
log "Postgres 유저·DB 준비"
: "${DB_PASSWORD:=}"
if [ -z "$DB_PASSWORD" ]; then
  read -rsp "DB 비밀번호(kcal 유저)를 입력하세요: " DB_PASSWORD; echo
  [ -n "$DB_PASSWORD" ] || die "DB 비밀번호가 비어 있습니다."
fi
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  && sudo -u postgres psql -c "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';" >/dev/null \
  || sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';" >/dev/null
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
# pg_trgm은 슈퍼유저만 만들 수 있어 여기서 미리 생성한다(마이그레이션 0008 대비).
sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null

# ---- 3. 파이썬 venv + 의존성(경량) ----
log "Python venv + requirements 설치"
cd "$APP_DIR"
[ -d venv ] || sudo -u "$APP_USER" python3 -m venv venv
sudo -u "$APP_USER" ./venv/bin/pip install --quiet --upgrade pip
sudo -u "$APP_USER" ./venv/bin/pip install --quiet -r requirements.txt

# ---- 4. .env 생성 (이미 있으면 보존 — 키 분실 방지) ----
if [ -f "$APP_DIR/.env" ]; then
  log ".env 가 이미 있어 그대로 둡니다(암호화 키 보존)."
else
  log ".env 생성(pepper·암호화 키 난수 생성, GEMINI 키는 입력)"
  : "${GEMINI_API_KEY:=}"
  if [ -z "$GEMINI_API_KEY" ]; then
    read -rsp "GEMINI_API_KEY 를 입력하세요: " GEMINI_API_KEY; echo
    [ -n "$GEMINI_API_KEY" ] || die "GEMINI_API_KEY 가 비어 있습니다(운영 필수)."
  fi
  PEPPER="$(./venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(48))')"
  ENCKEY="$(./venv/bin/python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
  DOMAIN="${DOMAIN:-http://localhost}"
  umask 077
  cat > "$APP_DIR/.env" <<ENV
APP_ENV=production
DATABASE_URL=postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
AUTH_INCLUDE_DEV_CODE=false
AUTH_CODE_TTL_MINUTES=5
AUTH_SESSION_TTL_DAYS=30
AUTH_CODE_PEPPER=${PEPPER}
HEALTH_ENCRYPTION_KEY=${ENCKEY}
GEMINI_API_KEY=${GEMINI_API_KEY}
GEMINI_MODEL=gemini-flash-latest
CORS_ALLOW_ORIGINS=${DOMAIN}
PREDICT_MAX_UPLOAD_MB=10
ENV
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  log "⚠️  HEALTH_ENCRYPTION_KEY 를 안전한 곳에 백업하세요 — 분실 시 민감정보 복호화 불가."
fi

# ---- 5. DB 마이그레이션 ----
log "alembic upgrade head"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && ./venv/bin/alembic upgrade head"

# ---- 6. systemd 서비스 ----
log "systemd 서비스 등록·기동"
sed -e "s#__APP_USER__#${APP_USER}#g" -e "s#__APP_DIR__#${APP_DIR}#g" \
  "$APP_DIR/deploy/kcalai.service" > "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

# 기동 대기(최대 ~30초 폴링).
ok=0
for _ in $(seq 1 15); do
  if curl -sf -o /dev/null http://127.0.0.1:8000/openapi.json; then ok=1; break; fi
  sleep 2
done
systemctl --no-pager --lines=5 status "${SERVICE_NAME}" || true

if [ "$ok" = 1 ]; then
  log "완료. 서버 응답 정상 (http://127.0.0.1:8000)"
else
  log "⚠️ 기동 확인 실패(약 30초) — journalctl -u ${SERVICE_NAME} -n 50 확인"
fi
log "HTTPS는 DEPLOY.md의 Caddy 단계를 따르세요(도메인 필요)."
