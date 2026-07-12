import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.account_schema import AccountDeleteResponse, AccountError
from services import account_service

router = APIRouter()

error_logger = setup_level_logger(logging.ERROR)


@router.delete(
    "/me",
    response_model=AccountDeleteResponse,
    responses={401: {"model": AccountError}, 500: {"model": AccountError}},
)
def delete_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        account_service.delete_account(db, current_user)
    except Exception as error:
        # 파기는 트랜잭션 하나다 — commit 전 실패는 세션 종료와 함께 전체 롤백된다.
        error_logger.error(f"회원 탈퇴 실패 user_id={current_user.id}: {error!r}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회원 탈퇴 처리에 실패했습니다. 잠시 후 다시 시도해주세요.",
        ) from error

    return {"message": "회원 탈퇴가 완료되었습니다. 모든 개인 데이터가 파기되었습니다."}
