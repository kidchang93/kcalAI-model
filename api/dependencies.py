from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.auth_model import User
from services import consent_service
from services.auth_service import get_user_by_session_token


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        return None

    return token.strip()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = extract_bearer_token(authorization)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_session_token(db, token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었거나 유효하지 않습니다. 다시 로그인해주세요.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_sensitive_consent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    # 401(미로그인)은 get_current_user 가 처리한다. 여기는 로그인된 사용자의 동의 여부만 본다.
    # 버전이 낡은 동의도 403 이다 — 판정과 문구는 서비스가 정한다(ensure_sensitive_consent).
    consent_service.ensure_sensitive_consent(db, current_user.id)
    return current_user


# 라우트 시그니처용 별칭: `def read_goal(current_user: CurrentUser, db: DB):`
CurrentUser = Annotated[User, Depends(get_current_user)]
ConsentedUser = Annotated[User, Depends(require_sensitive_consent)]
DB = Annotated[Session, Depends(get_db)]
