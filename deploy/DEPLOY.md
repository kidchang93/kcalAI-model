# Lightsail 배포 가이드 (kcalAI-model)

FastAPI 서버(Gemini 비전 + 식약처 DB)를 **AWS Lightsail Ubuntu**에 올린다. Postgres는 같은
인스턴스에 동거, uvicorn은 **systemd**로 상시 구동, HTTPS는 **Caddy**(자동 Let's Encrypt).
배포 브랜치는 **`release`**.

- 스택: Ubuntu 22.04/24.04 · Python venv(경량 requirements, torch 없음 ~200MB) · Postgres 16 · systemd · Caddy
- 인스턴스: **2GB RAM, 서울 리전(ap-northeast-2)** 권장. (torch 제거로 2GB면 충분.)

---

## ⚠️ 0. 배포 전 반드시 결정할 것 — OTP(인증번호) 전달

운영 게이트가 `APP_ENV=production`에서 **`AUTH_INCLUDE_DEV_CODE=false`를 강제**한다(`true`면 기동 실패).
그런데 **SMS 발송이 아직 연동되지 않아**, `false`면 인증번호가 사용자에게 **전달될 경로가 없다**.
즉 **production으로 띄우면 서버는 뜨지만 로그인/가입이 불가능**하다.

선택지(배포 전 정해야 함):
- **(권장) SMS를 먼저 연동한다** — 그 후 운영 배포. 가장 깔끔.
- **폐쇄 테스트라면** 임시로 `APP_ENV=development`로 서버를 띄운다. 단 이때 운영 fail-fast 게이트가
  꺼지고 `dev_code`가 API 응답에 노출되므로 **공개 서비스로 쓰면 안 된다**(누구나 로그인 가능).

이 결정 전에는 "일반 사용자 로그인"이 되는 배포가 성립하지 않는다. 아래 절차는 서버 인프라를
세우는 것이고, OTP 전달은 위 결정에 달려 있다.

---

## 1. 콘솔에서 직접 해야 하는 것 (수동)

CLI로 대신할 수 없는 단계다.

1. **인스턴스 생성** — Lightsail 콘솔 > Create instance:
   - 리전: **서울(ap-northeast-2)**
   - 플랫폼: Linux, 블루프린트: **Ubuntu 22.04 LTS** (또는 24.04)
   - 플랜: **2GB RAM / 2 vCPU** 이상
   - SSH 키: 새로 만들거나 기존 키 사용(다운로드한 .pem 보관)
2. **고정 IP(Static IP) 할당** — Networking > Create static IP > 인스턴스에 attach.
   재부팅해도 IP가 유지된다. (도메인 A 레코드가 이 IP를 가리킨다.)
3. **방화벽 포트** — 인스턴스 > Networking > IPv4 Firewall:
   - `22`(SSH), `80`(HTTP), `443`(HTTPS) **열기**
   - `8000`은 **열지 않는다** — uvicorn은 127.0.0.1에만 바인딩되고 Caddy 뒤에 있다.
   - `5432`(Postgres)도 **열지 않는다** — 로컬 동거.
4. **도메인 / DNS** (HTTPS에 필요):
   - 보유 도메인의 **A 레코드**를 위 고정 IP로 설정. (예: `api.example.com → 1.2.3.4`)
   - 도메인이 없으면 Let's Encrypt HTTPS를 못 받는다 → HTTP로만 테스트하거나 도메인을 먼저 확보.
5. **Gemini API 키** — Google AI Studio/Cloud 콘솔에서 발급. provision 때 입력한다(스크립트에 하드코딩 금지).
6. **스냅샷** — 프로비저닝이 끝나 정상 동작하면 인스턴스 스냅샷을 찍어 둔다(복구 지점).

---

## 2. 서버 접속 & repo 배치

```bash
ssh -i <your-key>.pem ubuntu@<STATIC_IP>

# repo를 /opt/kcalAI-model 에 release 브랜치로 clone
sudo mkdir -p /opt/kcalAI-model && sudo chown ubuntu:ubuntu /opt/kcalAI-model
git clone -b release <REPO_URL> /opt/kcalAI-model
```

> `<REPO_URL>`은 이 서버 repo의 원격 주소. private면 배포 키/토큰이 필요하다.

---

## 3. 초기 프로비저닝

`deploy/provision.sh`가 시스템 패키지·Postgres·venv·.env·마이그레이션·systemd를 한 번에 세운다.

```bash
cd /opt/kcalAI-model
# DB_PASSWORD·GEMINI_API_KEY는 환경변수로 주거나(권장), 안 주면 프롬프트로 입력받는다.
sudo -E env APP_USER=ubuntu APP_DIR=/opt/kcalAI-model DOMAIN=https://api.example.com \
  bash deploy/provision.sh
```

수행 내용:
- apt: `python3-venv postgresql caddy(별도)` 등 설치
- Postgres 유저(`kcal`)·DB(`kcal`)·`pg_trgm` 확장 생성
- 경량 venv + `pip install -r requirements.txt`
- **`.env` 생성** — `AUTH_CODE_PEPPER`·`HEALTH_ENCRYPTION_KEY`를 난수로 생성, `GEMINI_API_KEY`·DB 비번은 입력값
- `alembic upgrade head`
- `kcalai` systemd 서비스 등록·기동(재부팅 자동복구, 127.0.0.1:8000)

> ⚠️ **`HEALTH_ENCRYPTION_KEY`를 안전한 곳에 백업**한다. 분실하면 저장된 민감정보(혈액형·Rh)를 복호화할 수 없다.
> `.env`는 커밋 금지(gitignore).

헬스체크:
```bash
curl -sf http://127.0.0.1:8000/openapi.json >/dev/null && echo OK
systemctl status kcalai
```

---

## 4. HTTPS (Caddy)

도메인 A 레코드가 고정 IP를 가리키고 80/443이 열려 있어야 한다.

```bash
# Caddy 설치 (공식 저장소)
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy

# 설정: deploy/Caddyfile.example 을 참고해 도메인을 넣고 배치
sudo cp /opt/kcalAI-model/deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo sed -i 's/your.domain.com/api.example.com/' /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Caddy가 인증서를 자동 발급·갱신한다. 확인: `https://api.example.com/openapi.json`.

> nginx+certbot를 선호하면: nginx 설치 → `proxy_pass http://127.0.0.1:8000;` server 블록 → `certbot --nginx -d api.example.com`. Caddy가 설정이 더 단순해 권장.

---

## 5. 재배포 (코드 업데이트 시)

`release` 브랜치에 새 커밋이 올라간 뒤:

```bash
cd /opt/kcalAI-model
bash deploy/redeploy.sh
```

`release` pull → `pip install` → `alembic upgrade head` → `systemctl restart kcalai` → 헬스체크.

> 배포 흐름: 로컬에서 개발/커밋 → `release` 브랜치를 갱신(예: `git checkout release && git merge master && git push`)
> → 서버에서 `redeploy.sh`. (GitHub Actions 자동 배포는 현재 미구성 — `deploy.yml`은 NCP/dev용 레거시.)

---

## 6. 운영 · 트러블슈팅

| 작업 | 명령 |
|------|------|
| 로그 | `journalctl -u kcalai -f` |
| 재시작 | `sudo systemctl restart kcalai` |
| 상태 | `systemctl status kcalai` |
| 애플리케이션 로그 | `tail -f /opt/kcalAI-model/task-logs/info_log.txt` (구조적 request/predict 로그) |
| DB 백업 | `sudo -u postgres pg_dump kcal > backup.sql` (정기 cron 권장) |
| 만료 인증 정리 | `venv/bin/python scripts/purge_expired_auth.py` (cron 권장, 무한 누적 방지) |

- 서버가 안 뜨면 `journalctl -u kcalai -n 50` — production 게이트(pepper/암호화키/`AUTH_INCLUDE_DEV_CODE=false`/`GEMINI_API_KEY`)를 확인한다.
- 이미지 인식이 503이면 Gemini 키·쿼터·네트워크 확인(`predict fail backend=gemini` 로그).

---

## 7. 앱(k-calAI-RN) 연결 — 별개 배포

앱은 Lightsail이 아니라 **Expo로 별도 배포**(EAS/로컬 빌드 → TestFlight/App Store). 서버 배포 후
앱이 이 서버를 바라보게 하려면 앱 `.env`에 프로덕션 URL을 지정한다:

```
EXPO_PUBLIC_AUTH_API_URL=https://api.example.com/api/auth
EXPO_PUBLIC_CALORIE_API_URL=https://api.example.com/api/predict
# ... (나머지 EXPO_PUBLIC_*_API_URL, k-calAI-RN/.env.example 참고)
```

앱 repo에도 `release` 브랜치를 두지만(브랜치 컨벤션 통일), 여기 배포 스크립트는 서버 전용이다.
