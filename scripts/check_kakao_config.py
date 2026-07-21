"""카카오 로그인 설정 진단.

사용법 (저장소 루트에서):
    venv/bin/python scripts/check_kakao_config.py

카카오 로그인이 실패할 때 **어디가 틀렸는지**를 바로 알려준다. 서버 로그에는
`status=401` 만 남고 그 401 안에 원인이 여러 개(토큰 무효 / 앱 키 종류 / 허용 IP 미등록)
섞여 있어, 로그인 흐름을 다시 태우지 않고는 구분되지 않기 때문이다.

읽기 전용이다 — 카카오에 조회 요청만 보내고 아무것도 바꾸지 않는다.
비밀값은 출력하지 않는다(존재 여부와 길이만).
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# kakao_client 는 import 시점에 os.getenv 로 키를 읽는다. 그 전에 .env 를 올려야 한다
# (평소엔 database.py·crypto.py 가 부르지만 이 스크립트는 둘 다 import 하지 않는다).
# cwd 기준이므로 **저장소 루트에서** 실행해야 한다.
load_dotenv()

from services import kakao_client  # noqa: E402

# 어드민 키 전용 조회. 앱이 살아 있고 이 서버 IP 가 허용됐는지 확인하는 용도로만 쓴다.
USER_IDS_URL = "https://kapi.kakao.com/v1/user/ids"
TIMEOUT_SECONDS = 10


def _mask(name: str, value: str) -> str:
    return f"{name}: 설정됨(len={len(value)})" if value else f"{name}: **없음**"


def main() -> int:
    print("[1] 환경변수")
    for name, value in (
        ("KAKAO_REST_API_KEY", kakao_client.KAKAO_REST_API_KEY),
        ("KAKAO_CLIENT_SECRET", kakao_client.KAKAO_CLIENT_SECRET),
        ("KAKAO_ADMIN_KEY", kakao_client.KAKAO_ADMIN_KEY),
    ):
        print(f"  {_mask(name, value)}")
    print(f"  KAKAO_REDIRECT_URI: {kakao_client.KAKAO_REDIRECT_URI}")
    print(f"  APP_ENV: {os.getenv('APP_ENV', 'development')}")

    if not kakao_client.KAKAO_ADMIN_KEY:
        print("\n[2] 건너뜀 — KAKAO_ADMIN_KEY 가 없어 도달성을 확인할 수 없습니다.")
        return 1

    print("\n[2] kapi.kakao.com 도달성 (어드민 키로 조회)")
    try:
        response = requests.get(
            USER_IDS_URL,
            params={"limit": 1},
            headers={"Authorization": f"KakaoAK {kakao_client.KAKAO_ADMIN_KEY}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        print(f"  네트워크 실패: {error!r}")
        return 1

    if response.status_code == 200:
        print("  OK — 앱·키가 유효하고 이 서버 IP 가 허용돼 있습니다.")
        print("  로그인이 여전히 실패한다면 원인은 IP 가 아닙니다"
              " (동의항목·Redirect URI·연동 코드 만료를 보세요).")
        return 0

    payload = {}
    try:
        payload = response.json()
    except ValueError:
        pass
    msg = str(payload.get("msg", response.text[:200]))
    print(f"  status={response.status_code} code={payload.get('code')} msg={msg!r}")

    # 카카오는 원인이 다른 실패를 전부 code=-401 로 준다 — msg 로만 갈린다.
    if "ip mismatched" in msg:
        print("\n  ▶ 원인: **허용 IP 미등록**. 이 머신의 공인 IP 가 카카오 앱에 등록돼 있지 않습니다.")
        print("     조치: 카카오 개발자 콘솔 > 내 애플리케이션 > 앱 설정 > 보안 >")
        print("           '허용 IP 주소'에 위 msg 의 callerIp 를 추가하세요.")
        print("           (공인 IP 는 ISP 재할당으로 바뀔 수 있습니다. 로컬 개발용 앱을 따로")
        print("            만들어 IP 제한 없이 쓰는 편이 재발이 없습니다.)")
        print("     증상: 토큰 교환(kauth)은 성공하고 /v2/user/me(kapi)만 401 → 로그인 직전 실패.")
    elif "appKeyType" in msg:
        print("\n  ▶ 원인: **키 종류 혼동**. KAKAO_ADMIN_KEY 자리에 다른 키(REST/JavaScript)가 들어갔습니다.")
        print("     조치: 콘솔 > 앱 키 에서 어드민 키를 다시 복사하세요.")
    else:
        print("\n  ▶ 원인 미상. 위 msg 를 카카오 문서에서 확인하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
