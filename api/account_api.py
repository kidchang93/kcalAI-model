from fastapi import APIRouter, HTTPException, status

from api.dependencies import DB, CurrentUser
from log_utils import get_logger
from schemas.common_schema import ErrorResponse, MessageResponse
from services import account_service

router = APIRouter()

logger = get_logger(__name__)


@router.delete(
    "/me",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def delete_me(current_user: CurrentUser, db: DB):
    try:
        account_service.delete_account(db, current_user)
    except Exception as error:
        # 파기는 트랜잭션 하나다 — commit 전 실패는 세션 종료와 함께 전체 롤백된다.
        logger.error(f"회원 탈퇴 실패 user_id={current_user.id}: {error!r}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="회원 탈퇴 처리에 실패했습니다. 잠시 후 다시 시도해주세요.",
        ) from error

    return {"message": "회원 탈퇴가 완료되었습니다. 모든 개인 데이터가 파기되었습니다."}
