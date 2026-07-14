"""만료 인증코드·세션 정리 배치.

사용법 (저장소 루트에서):
    venv/bin/python scripts/purge_expired_auth.py

정기 실행(cron/systemd timer)을 권장한다 — kakao_link_codes·auth_sessions가
무한 누적되지 않도록. 보존창은 services/auth_service.py 상단 상수 참조. 멱등하다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from services.auth_service import purge_expired_auth  # noqa: E402


def main() -> None:
    session = SessionLocal()
    try:
        result = purge_expired_auth(session)
        print(f"정리 완료 — 코드 {result['codes']}건, 세션 {result['sessions']}건 삭제.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
