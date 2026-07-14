# Lightsail 배포 가이드 (kcalAI-model)

FastAPI 서버(Gemini 비전 + 식약처 DB)를 **AWS Lightsail Ubuntu**에 올린다. Postgres는 같은
인스턴스에 동거, uvicorn은 **systemd**로 상시 구동, HTTPS는 **Caddy**(자동 Let's Encrypt).
배포 브랜치는 **`release`**.

- 스택: Ubuntu 22.04/24.04 · Python venv(경량 requirements, torch 없음 ~200MB) · Postgres 16 · systemd · Caddy
- 인스턴스: **2GB RAM, 서울 리전(ap-northeast-2)** 권장. (torch 제거로 2GB면 충분.)

---

## ⚠️ 0. 배포 전 반드시 끝내야 할 것 (2026-07-14 갱신)

### 0-1. 카카오 로그인 — **유일한 인증 수단**이다

SMS(휴대폰 OTP)는 제거됐다. `APP_ENV=production`에서 카카오 키가 없으면 **기동 자체가 실패**한다
(`ensure_production_kakao_config`). 코드는 완성돼 있고, 남은 것은 **콘솔 설정**이다:

1. [developers.kakao.com](https://developers.kakao.com) 앱 생성 (개인·비사업자 가능, **무료·심사 없음**)
2. **카카오 로그인 [사용 설정] ON**
3. **Redirect URI 등록** ([앱] > [플랫폼 키] > [REST API 키] > [리다이렉트 URI]) — `.env`의
   `KAKAO_REDIRECT_URI`와 **문자 단위로 같아야** 한다 (다르면 `KOE006`).
   - 로컬: `http://localhost:8000/api/auth/kakao/callback`
   - 운영: `https://<도메인>/api/auth/kakao/callback`
   - ⚠️ **커스텀 스킴(`kcalairn://`)은 등록할 수 없다** — 카카오는 http/https만 받는다. 그래서 콜백을
     서버가 받고 앱으로 딥링크를 되돌려주는 구조다.
4. **동의항목**: `profile_nickname`(닉네임)만 켠다. 회원번호는 동의 없이 항상 온다.
5. **클라이언트 시크릿** — **[앱] > [플랫폼 키] > [REST API 키] > [클라이언트 시크릿]** 에 있다
   (어드민 키 옆이 아니라 **REST API 키에 딸려 있다**). 자동 활성화되어 발급되므로 값만 복사해
   `.env`의 `KAKAO_CLIENT_SECRET`에 넣는다. 없으면 토큰 교환이 실패한다.
6. **어드민 키** ([앱] > [어드민 키]) → `.env`의 `KAKAO_ADMIN_KEY`. 회원 탈퇴 시 연결 끊기(unlink)에
   쓰인다 — 카카오 로그인 서비스의 **의무**다.

> **이메일·전화번호가 필요해지면**: 이메일은 **비즈 앱 전환**(개인 개발자도 본인인증만으로 가능,
> 심사 없음)으로 받을 수 있다. **전화번호·CI는 사업자 정보가 등록된 비즈앱만 신청 가능**하고 심사가
> 3~5영업일 걸린다.

> ⚠️ **무료 티어 어뷰징 방어가 없다.** 카카오계정은 이메일만으로 만들 수 있어 Lite 3건/일은 계정
> 갈아타기로 우회된다. 감수한 트레이드오프다 (`docs/DATA_MODEL.md` 21장).

### 0-2. 요금제 결제 — 미연동 (운영 배포 블로커)

`PUT /api/me/subscription`이 **영수증 검증 없이** 플랜을 바꾼다. 지금 배포하면 **누구나 API 한 번으로
Premium이 된다.** 인앱결제(App Store / Play Billing) 영수증 검증을 붙이기 전까지는 유료 플랜이 사실상
무료다 (`docs/DATA_MODEL.md` 20장).

폐쇄 테스트라면 감수하고 띄울 수 있지만, **공개 서비스 전에는 반드시 막아야 한다.**

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

## 2. 배포 방식 — 로컬 주도 (권장)

**모든 작업을 개발 머신에서** 한다: 로컬에서 (선택)웹 빌드 → `rsync`로 서버에 코드/웹 업로드 →
원격 재시작. 서버는 git pull 하지 않는다. `deploy/local_deploy.sh`가 이걸 한 번에 처리한다.

준비 — **설정 파일에 한 번만 적어두면 매번 export 안 해도 된다**(권장):
```bash
cp kcalAI-model/deploy/deploy.local.env.example kcalAI-model/deploy/deploy.local.env
# deploy.local.env 를 열어 SSH_HOST/SSH_KEY/REMOTE_DIR 을 채운다. (gitignore 되므로 커밋 안 됨)
```
`local_deploy.sh`가 이 파일을 자동으로 읽는다. (일회성으로 다르게 쓰려면 `SSH_HOST=... bash ...`
처럼 환경변수를 주면 파일값보다 우선한다.)

배포 전 로컬에서 배포할 상태를 `release`로 맞춘다(작업 트리를 그대로 올리므로):
```bash
git checkout release && git merge master   # 배포할 코드를 release로
```

> `.env`·`venv/`·`task-logs/`·`.git/`는 rsync에서 **제외**된다 — 서버의 운영 `.env`(pepper·암호화 키)와
> 서버용 리눅스 venv가 보존된다. rsync는 `--delete`라 서버의 오래된 파일(구 코드 등)은 정리된다.

## 3. 최초 1회: 프로비저닝 (로컬에서 트리거)

인스턴스가 처음이면 `--provision`으로 코드를 올리고 서버에서 `provision.sh`를 실행한다
(시스템 패키지·Postgres·venv·`.env`·마이그레이션·systemd를 세팅. secret은 서버에서 프롬프트로 입력).

```bash
bash kcalAI-model/deploy/local_deploy.sh --provision
```

수행 내용(원격 provision.sh):
- apt: `python3-venv postgresql` 등, Postgres 유저(`kcal`)·DB(`kcal`)·`pg_trgm` 생성
- 경량 venv + `pip install -r requirements.txt`
- **`.env` 생성** — `AUTH_CODE_PEPPER`·`HEALTH_ENCRYPTION_KEY` 난수 생성, `GEMINI_API_KEY`·DB 비번은 프롬프트
- `alembic upgrade head`, `kcalai` systemd 등록·기동(재부팅 자동복구, 127.0.0.1:8000)

> ⚠️ **`HEALTH_ENCRYPTION_KEY`를 안전한 곳에 백업**한다(서버 `.env`에 있음). 분실 시 민감정보 복호화 불가.

헬스체크(로컬에서): `ssh -i $SSH_KEY $SSH_HOST 'curl -sf http://127.0.0.1:8000/openapi.json && echo OK'`

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

## 5. 재배포 (코드 업데이트 시) — 로컬에서 한 줄

프로비저닝 이후에는 로컬에서 이 한 줄이면 끝이다:

```bash
# (release 상태로 맞춘 뒤) 코드만 배포
bash kcalAI-model/deploy/local_deploy.sh

# 웹 프런트도 함께: 웹 빌드 + webapp/ 업로드
bash kcalAI-model/deploy/local_deploy.sh --web

# DB 스키마가 바뀐 배포: 원격 마이그레이션 포함
bash kcalAI-model/deploy/local_deploy.sh --web --migrate
```

`local_deploy.sh`가 하는 일: (`--web`이면)웹 번들 빌드 → rsync 업로드 →
원격 `pip install` → (`--migrate`면)`alembic upgrade` → `systemctl restart kcalai` → 헬스체크.

**웹 프런트 서빙**: `--web`을 주면 `build-web.sh`가 Expo 웹을 `webapp/`으로 내보내고 서버에 올린다.
FastAPI가 `webapp/`를 `/`로 서빙하므로, 서브도메인(`https://api.example.com`)에서 웹으로도 접속된다.

> **대안(서버 git pull 방식)**: 서버에 repo를 clone해 두고 `deploy/redeploy.sh`로 `release`를
> pull·재시작할 수도 있다. 로컬 주도 방식을 쓰면 서버에 git/원격 접근이 필요 없다.
> GitHub Actions 자동 배포는 미구성(`deploy.yml`은 NCP/dev용 레거시 — 건드리지 않음).

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

- 서버가 안 뜨면 `journalctl -u kcalai -n 50` — production 게이트(`AUTH_CODE_PEPPER`/`HEALTH_ENCRYPTION_KEY`/`GEMINI_API_KEY`/**카카오 키 4종**)를 확인한다. 카카오는 유일한 인증 수단이라 설정이 없으면 기동을 거부한다.
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
