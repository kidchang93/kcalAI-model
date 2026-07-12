#!/usr/bin/env bash
#
# 로컬 주도 배포 — 개발 머신에서 한 번에 (선택)웹빌드 → rsync 업로드 → 원격 재시작.
# 서버가 git pull 하지 않는다. 로컬 작업 트리를 그대로 서버에 밀어넣는다.
#
# 사용:
#   SSH_HOST=ubuntu@1.2.3.4 SSH_KEY=~/.ssh/lightsail.pem \
#     bash deploy/local_deploy.sh [--web] [--migrate] [--provision]
#
#   (기본)       코드 rsync → 원격 pip install → 서비스 재시작 → 헬스체크
#   --web        Expo 웹 번들 빌드(build-web.sh) 후 webapp/ 도 업로드
#   --migrate    원격에서 alembic upgrade head 실행
#   --provision  최초 1회: 코드 올린 뒤 원격에서 provision.sh 실행(대화형, secret 입력)
#
# secret은 스크립트에 없다. 서버의 .env는 rsync에서 제외되어 보존된다(운영 키 유실 방지).
set -euo pipefail

# ---- 배포 설정 로드: deploy/deploy.local.env 가 있으면 읽는다. ----
# (export된 환경변수가 파일값보다 우선한다. DEPLOY_ENV_FILE 로 경로를 바꿀 수 있다.)
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${DEPLOY_ENV_FILE:-$_SCRIPT_DIR/deploy.local.env}"
if [ -f "$CONFIG" ]; then
  _pre_host="${SSH_HOST:-}"; _pre_key="${SSH_KEY:-}"; _pre_dir="${REMOTE_DIR:-}"
  set -a; source "$CONFIG"; set +a
  [ -n "$_pre_host" ] && SSH_HOST="$_pre_host"
  [ -n "$_pre_key" ] && SSH_KEY="$_pre_key"
  [ -n "$_pre_dir" ] && REMOTE_DIR="$_pre_dir"
fi

SSH_HOST="${SSH_HOST:?SSH_HOST 필요 — deploy/deploy.local.env 에 넣거나 환경변수로 export}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/lightsail.pem}"
SSH_KEY="${SSH_KEY/#\~/$HOME}"   # 앞의 ~ 를 $HOME 으로 확장(ssh는 ~를 안 펴줌)
REMOTE_DIR="${REMOTE_DIR:-/opt/kcalAI-model}"

WANT_WEB=0; WANT_MIGRATE=0; WANT_PROVISION=0
for arg in "$@"; do
  case "$arg" in
    --web) WANT_WEB=1 ;;
    --migrate) WANT_MIGRATE=1 ;;
    --provision) WANT_PROVISION=1 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

log() { echo -e "\n\033[1;34m[local-deploy]\033[0m $*"; }
SSH=(ssh -i "$SSH_KEY" "$SSH_HOST")
RSH="ssh -i $SSH_KEY"

# repo 루트 = 이 스크립트의 상위. 워크스페이스 루트 = 그 상위(build-web.sh 위치).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
cd "$REPO_ROOT"

# ---- 1. (선택) 웹 번들 빌드 ----
if [ "$WANT_WEB" -eq 1 ]; then
  log "웹 번들 빌드 (build-web.sh → webapp/)"
  [ -x "$WS_ROOT/build-web.sh" ] || { echo "build-web.sh 없음: $WS_ROOT" >&2; exit 1; }
  ( cd "$WS_ROOT" && ./build-web.sh )
fi

# ---- 2. (--provision) 최초 프로비저닝 준비: 원격 디렉토리 소유권 ----
if [ "$WANT_PROVISION" -eq 1 ]; then
  log "원격 디렉토리 준비($REMOTE_DIR)"
  "${SSH[@]}" "sudo mkdir -p '$REMOTE_DIR' && sudo chown \$(whoami): '$REMOTE_DIR'"
fi

# ---- 3. 코드 rsync (서버의 .env·venv·로그·git·webapp은 제외/보존) ----
log "코드 업로드 (rsync, --delete)"
rsync -az --delete \
  --exclude='.env' --exclude='venv/' --exclude='.venv/' --exclude='.git/' \
  --exclude='__pycache__/' --exclude='task-logs/' --exclude='webapp/' \
  --exclude='.DS_Store' --exclude='.idea/' --exclude='.vscode/' --exclude='.pytest_cache/' \
  -e "$RSH" ./ "$SSH_HOST:$REMOTE_DIR/"

# ---- 3b. (--web) webapp 별도 업로드 (기본 rsync에선 제외했으므로) ----
if [ "$WANT_WEB" -eq 1 ]; then
  log "webapp/ 업로드"
  rsync -az --delete -e "$RSH" webapp/ "$SSH_HOST:$REMOTE_DIR/webapp/"
fi

# ---- 4. 최초 프로비저닝이면 원격 provision.sh(대화형) 실행하고 종료 ----
if [ "$WANT_PROVISION" -eq 1 ]; then
  log "원격 provision.sh 실행 (secret은 서버에서 프롬프트로 입력)"
  ssh -t -i "$SSH_KEY" "$SSH_HOST" \
    "cd '$REMOTE_DIR' && sudo -E env APP_DIR='$REMOTE_DIR' bash deploy/provision.sh"
  log "프로비저닝 완료."
  exit 0
fi

# ---- 5. 원격: 의존성 갱신 + (선택)마이그레이션 + 재시작 + 헬스체크 ----
MIGRATE_CMD=""
[ "$WANT_MIGRATE" -eq 1 ] && MIGRATE_CMD="./venv/bin/alembic upgrade head"
log "원격 갱신·재시작"
"${SSH[@]}" bash -s <<REMOTE
set -e
cd "$REMOTE_DIR"
./venv/bin/pip install -q -r requirements.txt
$MIGRATE_CMD
sudo systemctl restart kcalai
sleep 2
if curl -sf -o /dev/null http://127.0.0.1:8000/openapi.json; then
  echo "[remote] 헬스체크 OK"
else
  echo "[remote] 헬스체크 실패 — journalctl -u kcalai -n 50" >&2
  exit 1
fi
REMOTE

log "배포 완료: $SSH_HOST"
