#!/usr/bin/env bash
#
# 재배포 — release 브랜치 최신을 받아 의존성·마이그레이션 갱신 후 서비스 재시작.
# 서버에서 실행: bash deploy/redeploy.sh   (필요 시 APP_DIR 지정)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/kcalAI-model}"
SERVICE_NAME="kcalai"
BRANCH="release"

log() { echo -e "\n\033[1;34m[redeploy]\033[0m $*"; }
cd "$APP_DIR"

log "release 브랜치 최신으로 갱신"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

log "의존성 갱신(경량 requirements)"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

log "DB 마이그레이션"
./venv/bin/alembic upgrade head

log "서비스 재시작"
sudo systemctl restart "$SERVICE_NAME"
sleep 2
sudo systemctl --no-pager --lines=5 status "$SERVICE_NAME" || true

log "헬스체크"
if curl -sf -o /dev/null http://127.0.0.1:8000/openapi.json; then
  log "OK — 서버 응답 정상"
else
  log "⚠️ 헬스체크 실패 — journalctl -u ${SERVICE_NAME} -n 50 확인"
  exit 1
fi
