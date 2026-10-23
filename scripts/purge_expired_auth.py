"""만료 인증코드·세션 정리 배치 + 보존 기간이 지난 탈퇴 회원의 결제 기록 파기.

사용법 (저장소 루트에서):
    venv/bin/python scripts/purge_expired_auth.py

정기 실행(cron/systemd timer)을 권장한다 — kakao_link_codes·auth_sessions가
무한 누적되지 않도록. 보존창은 services/auth_service.py 상단 상수 참조. 멱등하다.
결제 기록(store_transactions)은 처리방침 8항이 약속한 '5년 뒤 파기'를 이행한다 — cron 줄을 새로 만들지 않고
이미 매일 도는 이 배치에 얹었다(DATA_MODEL 35-4).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from services.auth_service import purge_expired_auth  # noqa: E402
from services.subscription_service import purge_expired_store_transactions  # noqa: E402


def main() -> None:
    with SessionLocal() as session:
        result = purge_expired_auth(session)
        ledger = purge_expired_store_transactions(session)
        print(f"정리 완료 — 코드 {result['codes']}건, 세션 {result['sessions']}건, 보존 기간 지난 결제 기록 {ledger}건 삭제.")


if __name__ == "__main__":
    main()
