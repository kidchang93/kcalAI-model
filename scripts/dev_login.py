"""로컬 개발용 로그인 — 카카오 없이 세션을 발급한다.

사용법 (저장소 루트에서):
    venv/bin/python scripts/dev_login.py
    venv/bin/python scripts/dev_login.py --conditions ckd --label ckd
    venv/bin/python scripts/dev_login.py --origin http://localhost:8000

왜 필요한가: 카카오 앱에 **허용 IP 제한**이 걸려 있어 로컬(유동 공인 IP)에서는 카카오
로그인이 통과하지 못한다 (CLAUDE.md 알려진 문제 12). 운영은 정상이므로, 로컬 개발만
이 스크립트로 우회한다.

실제 가입·로그인 경로(`create_link_code` → `kakao_signup`/`kakao_login`)를 그대로 태운다 —
세션 발급을 흉내 내지 않으므로 약관 동의·요금제 행도 정상적으로 생긴다. 추가로 앱이 온보딩
화면으로 튕기지 않도록 신체 프로필·목표·민감정보 동의까지 채운다.

⚠️ `APP_ENV=production` 이면 실행을 거부한다. 이 스크립트는 임의 계정의 세션을 만들 수 있어
운영에서 실행되면 그 자체가 인증 우회다.
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# database 가 load_dotenv 를 부르지만, APP_ENV 를 import 전에 읽어야 해서 여기서도 올린다.
load_dotenv()

import os  # noqa: E402

from database import SessionLocal  # noqa: E402
from services import auth_service, consent_service, health_service  # noqa: E402

# 개발 계정임이 한눈에 보이는 접두사. 운영 데이터와 절대 섞이지 않게 한다.
KAKAO_ID_PREFIX = "local-dev"

# 온보딩 가드(app/(tabs)/_layout.tsx)는 GET /api/me/profile 이 404 면 동의 화면으로 보낸다.
# 그래서 최소 프로필·목표를 채워 둔다 — 값 자체는 개발 편의용 더미다.
DEFAULT_PROFILE = {
    "sex": "male",
    "birth_year": 1993,
    "height_cm": 175.0,
    "weight_kg": 70.0,
    "activity_level": "moderate",
}
DEFAULT_GOAL = {"goal_type": "maintain", "target_kcal": 2200, "target_weight_kg": 70.0}


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 개발용 세션 발급 (카카오 우회)")
    parser.add_argument("--label", default="dev", help="계정 구분자. kakao_id 는 local-dev:<label>")
    parser.add_argument(
        "--conditions",
        default="",
        help="쉼표로 구분한 질병 코드 (예: ckd,hypertension). 생략하면 질병 없음",
    )
    parser.add_argument(
        "--origin",
        default="http://localhost:8081",
        help="세션을 심을 앱 오리진. localStorage 는 오리진마다 따로다",
    )
    args = parser.parse_args()

    if os.getenv("APP_ENV", "development") == "production":
        print("거부: APP_ENV=production 에서는 실행할 수 없습니다 (인증 우회).", file=sys.stderr)
        return 1

    kakao_id = f"{KAKAO_ID_PREFIX}:{args.label}"
    conditions = [code.strip() for code in args.conditions.split(",") if code.strip()]

    db = SessionLocal()
    try:
        # 실제 로그인 경로를 그대로 탄다 — 연동 코드를 만들고 신규면 가입, 기존이면 로그인.
        raw_code, is_new = auth_service.create_link_code(db, kakao_id, f"로컬{args.label}")
        if is_new:
            user, _, token = auth_service.kakao_signup(
                db, raw_code, agreed_terms=True, agreed_privacy=True
            )
        else:
            user, _, token = auth_service.kakao_login(db, raw_code)

        # 민감정보 동의 — 추천·경고 API 가 요구한다 (없으면 403).
        if not consent_service.has_active_consent(db, user.id):
            consent_service.create_consent(
                db,
                user.id,
                consent_service.SENSITIVE_HEALTH,
                consent_service.SENSITIVE_HEALTH_VERSION,
            )

        consent_service.replace_conditions(db, user.id, conditions)
        health_service.upsert_profile(db, user.id, **DEFAULT_PROFILE)
        health_service.upsert_goal(db, user.id, **DEFAULT_GOAL)
        db.commit()

        session_payload = {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": _session_expiry(db, token),
            "user": {
                "id": user.id,
                "nickname": user.nickname,
                "created_at": user.created_at.isoformat(),
            },
        }
        user_id = user.id
    finally:
        db.close()

    print(f"user_id={user_id}  kakao_id={kakao_id}  질병={conditions or '없음'}")
    print(f"\n# 웹({args.origin}) — 브라우저 콘솔에 붙여넣으세요")
    raw = json.dumps(json.dumps(session_payload, ensure_ascii=False), ensure_ascii=False)
    print(f"localStorage.setItem('auth-session', {raw}); location.href='/';")
    print("\n# API 직접 호출용")
    print(f"export KCAL_TOKEN={token}")
    print('curl -H "Authorization: Bearer $KCAL_TOKEN" '
          f'{args.origin.replace("8081", "8000")}/api/me/summary')
    return 0


def _session_expiry(db, token: str) -> str:
    # 방금 만든 세션의 만료 시각. 앱이 만료를 스스로 판단하므로 정확한 값이 필요하다.
    user = auth_service.get_user_by_session_token(db, token)
    if user is None:  # 발급 직후라 정상 흐름에서는 일어나지 않는다.
        raise RuntimeError("세션 발급 직후 조회에 실패했습니다.")
    session = max(user.sessions, key=lambda item: item.created_at)
    return session.expires_at.isoformat()


if __name__ == "__main__":
    sys.exit(main())
