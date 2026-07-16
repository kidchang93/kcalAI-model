#!/usr/bin/env bash
#
# 재배포(대안 경로) — 서버가 직접 git pull 해서 의존성·마이그레이션 갱신 후 서비스 재시작.
# 서버에서 실행: bash deploy/redeploy.sh   (필요 시 APP_DIR·BRANCH 지정)
#
# **현재 운영 배포는 이 스크립트가 아니라 `deploy/local_deploy.sh`다** (로컬 작업 트리를 rsync).
# 이 경로는 서버에 repo clone + git 원격 접근이 있어야 쓸 수 있다. 자세한 절차는 deploy/DEPLOY.md.
#
# 2026-07-16: BRANCH 를 `release` → `master` 로 고쳤다. release 브랜치가 2026-07-12 이후 갱신되지
# 않아(master보다 22커밋 뒤) 이 스크립트를 쓰면 **낡은 코드가 배포되는** 상태였다. master 는
# origin/HEAD 이자 실제 배포 기준이다.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/kcalAI-model}"
SERVICE_NAME="kcalai"
# 배포 기준 브랜치. 다른 브랜치를 올리려면 BRANCH=... 로 덮어쓴다.
BRANCH="${BRANCH:-master}"

log() { echo -e "\n\033[1;34m[redeploy]\033[0m $*"; }
cd "$APP_DIR"

log "$BRANCH 브랜치 최신으로 갱신"
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

log "헬스체크 (기동 대기, 최대 ~30초 폴링)"
ok=0
for _ in $(seq 1 15); do
  if curl -sf -o /dev/null http://127.0.0.1:8000/openapi.json; then ok=1; break; fi
  sleep 2
done
if [ "$ok" = 1 ]; then
  log "OK — 서버 응답 정상"
else
  log "⚠️ 헬스체크 실패(약 30초) — journalctl -u ${SERVICE_NAME} -n 50 확인"
  exit 1
fi
