from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.consent_api import require_sensitive_consent
from database import get_db
from models.auth_model import User
from models.health_model import LabResult
from schemas.lab_schema import (
    LabPanelListResponse,
    LabPanelOption,
    LabResultListResponse,
    LabResultRequest,
    LabResultResponse,
)
from services import lab_panels, lab_service, meta_service

router = APIRouter()

# 검사 수치는 **민감정보**다 — 질병·알러지와 같은 등급이라 `sensitive_health` 동의를 요구한다.
# 가이드(`/api/guides`)가 동의 없이 열리는 것과 대비된다: 그쪽은 학회 지침을 옮긴 공개
# 정보이고 사용자의 값을 읽지 않는다. 여기는 사용자 본인의 검사 결과다.

_NOTICE = (
    "입력하신 수치는 그대로 보관하며, 저희가 정상 여부를 판단하지 않습니다. "
    "함께 표시되는 범위는 학회 지침의 일반 기준이고 실제 목표는 병기·나이·동반질환에 따라 "
    "다르므로 담당 의료진과 확인하세요."
)


def _to_response(row: LabResult) -> LabResultResponse:
    definition = lab_panels.get_panel(row.panel)

    return LabResultResponse(
        id=row.id,
        measured_on=row.measured_on,
        panel=row.panel,
        # 정의가 사라진 항목(코드 정리 등)도 저장값은 남아 있어야 한다 — 코드를 그대로 보인다.
        label=definition.label if definition is not None else row.panel,
        value=float(row.value),
        unit=row.unit,
        reference=definition.reference if definition is not None else None,
        source_note=definition.source if definition is not None else "",
        note=row.note,
        created_at=row.created_at,
    )


@router.get("/me/lab-panels", response_model=LabPanelListResponse)
def list_lab_panels(
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    """입력 가능한 검사 항목·단위·정상범위. **앱이 의학 용어와 수치를 갖지 않게 한다.**"""
    mine = {row.code for row in meta_service.list_user_condition_types(db, current_user.id)}

    options = [
        LabPanelOption(
            code=panel.code,
            label=panel.label,
            unit=panel.unit,
            reference=panel.reference,
            source=panel.source,
            conditions=list(panel.conditions),
            decimals=panel.decimals,
            is_mine=bool(mine & set(panel.conditions)),
        )
        for panel in lab_panels.PANELS
    ]

    # 내 질환 항목을 앞에 둔다. 14개를 다 훑게 하면 입력 자체를 포기한다.
    options.sort(key=lambda option: not option.is_mine)

    return LabPanelListResponse(panels=options, notice=_NOTICE)


@router.post("/me/labs", response_model=LabResultResponse, status_code=201)
def create_lab_result(
    request: LabResultRequest,
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    try:
        row = lab_service.save_result(
            db,
            user_id=current_user.id,
            measured_on=request.measured_on,
            panel=request.panel,
            value=request.value,
            note=request.note,
        )
    except (lab_service.UnknownPanelError, lab_service.ValueOutOfRangeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return _to_response(row)


@router.get("/me/labs", response_model=LabResultListResponse)
def list_lab_results(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    panel: str | None = Query(default=None, max_length=30),
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    rows = lab_service.list_results(
        db, current_user.id, start_date=start_date, end_date=end_date, panel=panel
    )

    return LabResultListResponse(
        results=[_to_response(row) for row in rows],
        notice=_NOTICE,
    )


@router.delete("/me/labs/{result_id}", status_code=204)
def delete_lab_result(
    result_id: int,
    current_user: User = Depends(require_sensitive_consent),
    db: Session = Depends(get_db),
):
    if not lab_service.delete_result(db, current_user.id, result_id):
        # 남의 것과 없는 것을 구분하지 않는다 (다른 삭제 라우트와 같은 존재 은닉 규칙).
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
