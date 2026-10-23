"""메일로 받은 회원 탈퇴 요청 처리 — 운영자가 손으로 실행한다(2026-10-23).

Google Play 계정 삭제 요건 때문에 고객 지원 페이지가 "앱 없이도 메일로 탈퇴를 요청할 수 있고, 늦어도 10일 안에
처리한다"고 약속한다(앱 docs/PLAY_STORE_SUBMISSION.md §1-②). 앱의 회원 탈퇴(DELETE /api/me)와 **같은 함수**
(`account_service.delete_account` — 파기·결제 원장 처리·카카오 연결 끊기·Apple 토큰 폐기)를 부른다.
본인 확인은 사람이 한다: 요청 메일의 주소·로그인 방법·닉네임이 아래에 보이는 회원과 맞는지 보고 --yes 를 붙인다.

사용법 (저장소 루트에서, 운영은 sudo -u kcalai):
    venv/bin/python scripts/delete_member.py --find "닉네임 또는 가입 이메일"   # 후보만 보여 준다
    venv/bin/python scripts/delete_member.py --user-id 21                      # 지울 회원을 보여 준다
    venv/bin/python scripts/delete_member.py --user-id 21 --yes                # 실제로 탈퇴 처리(되돌릴 수 없다)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import engine  # noqa: E402
from models.auth_model import User  # noqa: E402
from services import account_service  # noqa: E402


def describe(user: User) -> str:
    methods = [
        name
        for name, value in (("카카오", user.kakao_id), ("Apple", user.apple_sub), ("이메일", user.email))
        if value
    ]
    return (
        f"회원 {user.id} · 닉네임 '{user.nickname}' · 이메일 {user.email or '-'} · "
        f"로그인 {'·'.join(methods) or '-'} · 가입 {user.created_at:%Y-%m-%d}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="메일로 받은 회원 탈퇴 요청을 처리한다")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--find", help="닉네임 또는 가입 이메일(정확히 일치)")
    target.add_argument("--user-id", type=int)
    parser.add_argument("--yes", action="store_true", help="실제로 탈퇴 처리한다(--user-id 와 함께)")
    args = parser.parse_args()

    with Session(engine) as session:
        if args.find is not None:
            # 닉네임은 카카오 회원끼리 겹칠 수 있다 — 후보를 모두 보여 주고 지우기는 --user-id 로만 한다.
            users = session.scalars(
                select(User).where(or_(User.nickname == args.find, User.email == args.find.lower()))
            ).all()
            for user in users:
                print(describe(user))
            print(f"{len(users)}명. 지우려면 --user-id <번호> 로 다시 실행하세요.")
            return 0

        user = session.get(User, args.user_id)

        if user is None:
            print(f"회원 {args.user_id} 이 없습니다.")
            return 1

        print(describe(user))

        if not args.yes:
            print("요청한 사람이 이 회원이 맞으면 --yes 를 붙여 다시 실행하세요. 되돌릴 수 없습니다.")
            return 0

        account_service.delete_account(session, user)
        print("탈퇴 처리했습니다. 요청자에게 결과를 회신하세요.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
