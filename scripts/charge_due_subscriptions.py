"""자동결제 갱신 배치 — 청구 예정일이 지난 구독을 청구한다 (DATA_MODEL.md 24장).

사용법 (저장소 루트에서):
    venv/bin/python scripts/charge_due_subscriptions.py

정기 실행(cron/systemd timer)을 권장한다. 하루 1회면 충분하다 — 청구 예정일이 지난 건만
집으므로 실행이 늦어져도 건너뛰지 않는다.

**멱등하다.** 청구에 성공한 구독은 next_billing_at 이 한 달 뒤로 밀려 같은 날 다시 실행해도
대상에서 빠진다. 실패한 건은 다음날 재시도되며(past_due), 한 건의 실패가 배치를 멈추지 않는다.
TOSS_SECRET_KEY 가 없으면 청구가 전부 실패하므로 미설정 시 아예 실행하지 않는다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from services.billing_service import charge_due_subscriptions  # noqa: E402
from services.toss_client import is_configured  # noqa: E402


def main() -> int:
    if not is_configured():
        print("TOSS_SECRET_KEY·TOSS_CLIENT_KEY 가 설정되지 않아 중단합니다.")
        return 1

    session = SessionLocal()
    try:
        result = charge_due_subscriptions(session)
        print(
            f"갱신 배치 완료 — 대상 {result['due']}건, 성공 {result['charged']}건, "
            f"실패 {result['failed']}건, 건너뜀 {result['skipped']}건."
        )
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
