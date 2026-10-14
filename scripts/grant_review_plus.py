"""스토어 심사용 계정에 플러스 붙이기 — 운영자가 손으로 실행한다(2026-10-14).

Google Play 로그인 세부정보는 유료 콘텐츠까지 볼 수 있는 계정을 요구하고, 검토자는 구매하지 못한다.
결제 없이 유료를 붙이는 유일한 경로라 API 로 열지 않고 이 스크립트만 둔다. 만료일이 있어 잊혀도 끝난다.

사용법:
    venv/bin/python scripts/grant_review_plus.py --user-id 14                # 지금 상태와 할 일만 보여 준다
    venv/bin/python scripts/grant_review_plus.py --user-id 14 --days 365 --yes
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from database import engine  # noqa: E402
from models.auth_model import User  # noqa: E402
from services import subscription_service  # noqa: E402
from timeutil import UTC  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="스토어 심사용 계정에 플러스를 붙인다")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--yes", action="store_true", help="실제로 적용한다")
    args = parser.parse_args()

    with Session(engine) as session:
        user = session.get(User, args.user_id)

        if user is None:
            print(f"회원 {args.user_id} 이 없습니다.")
            return 1

        current = subscription_service.get_subscription(session, args.user_id)
        until = datetime.now(UTC) + timedelta(days=args.days)
        print(f"회원 {user.id} '{user.nickname}': 지금 {current.plan_code} · provider={current.provider} "
              f"· 기간 {current.current_period_end}")
        print(f"→ plus · provider=review · {until:%Y-%m-%d}까지")

        if not args.yes:
            print("적용하려면 --yes 를 붙이세요.")
            return 0

        subscription_service.grant_review_plus(session, args.user_id, until)
        print("적용했습니다.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
