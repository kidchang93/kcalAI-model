from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.consent_schema import (
    AllergiesPutRequest,
    AllergiesResponse,
    ConditionsPutRequest,
    ConditionsResponse,
    ConsentCreateRequest,
    ConsentError,
    ConsentResponse,
    ConsentRevokeRequest,
    HealthProfileResponse,
    HealthProfileUpsertRequest,
    MessageResponse,
)
from services import consent_service

router = APIRouter()


def require_sensitive_consent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    # 401(미로그인)은 get_current_user 가 처리한다. 여기는 로그인된 사용자의 동의 여부만 본다.
    if not consent_service.has_active_consent(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="건강 민감정보 이용 동의가 필요합니다. 동의 후 다시 시도해주세요.",
        )
    return current_user


# ---- 동의 ----

@router.get(
    "/me/consents",
    response_model=list[ConsentResponse],
    responses={401: {"model": ConsentError}},
)
def read_consents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return consent_service.list_consents(db, current_user.id)


@router.post(
    "/me/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ConsentError}},
)
def create_consent(
    request: ConsentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return consent_service.create_consent(db, current_user.id, request.kind, request.version)


@router.post(
    "/me/consents/revoke",
    response_model=MessageResponse,
    responses={401: {"model": ConsentError}, 404: {"model": ConsentError}},
)
def revoke_consent(
    request: ConsentRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        consent_service.revoke_consent(db, current_user.id, request.kind)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return {"message": "동의를 철회했습니다."}


# ---- 건강 프로필 (혈액형·Rh) ----

@router.get(
    "/me/health-profile",
    response_model=HealthProfileResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}, 404: {"model": ConsentError}},
)
def read_health_profile(
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    try:
        return consent_service.get_health_profile(db, current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.put(
    "/me/health-profile",
    response_model=HealthProfileResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}},
)
def update_health_profile(
    request: HealthProfileUpsertRequest,
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    return consent_service.upsert_health_profile(
        db,
        current_user.id,
        blood_type=request.blood_type,
        rh=request.rh,
    )


# ---- 질병 ----

@router.get(
    "/me/conditions",
    response_model=ConditionsResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}},
)
def read_conditions(
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    return {"conditions": consent_service.list_conditions(db, current_user.id)}


@router.put(
    "/me/conditions",
    response_model=ConditionsResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}},
)
def replace_conditions(
    request: ConditionsPutRequest,
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    conditions = consent_service.replace_conditions(db, current_user.id, list(request.conditions))
    return {"conditions": conditions}


# ---- 알러지 ----

@router.get(
    "/me/allergies",
    response_model=AllergiesResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}},
)
def read_allergies(
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    return {"allergies": consent_service.list_allergies(db, current_user.id)}


@router.put(
    "/me/allergies",
    response_model=AllergiesResponse,
    responses={401: {"model": ConsentError}, 403: {"model": ConsentError}},
)
def replace_allergies(
    request: AllergiesPutRequest,
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    allergies = consent_service.replace_allergies(
        db,
        current_user.id,
        [allergy.model_dump() for allergy in request.allergies],
    )
    return {"allergies": allergies}
