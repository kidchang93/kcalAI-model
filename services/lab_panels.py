"""검사 항목의 단일 진실 — 코드·단위·정상범위·출처.

`docs/CARE_LOOP.md` §4-1. **우리가 고른 목록이 아니다.** 대한신장학회 e북 1권
I-20 「병원정기검사에서 확인해야 할 항목들」(p47–49)이 항목·정상범위·목표치를 이미
정리해 두었고, 이 모듈은 그것을 옮긴 것이다.

## 지키는 것

- **단위는 서버가 정한다.** 사용자가 고르지 않는다 — mg/dL 과 mmol/L 을 섞어 받으면
  추이가 무의미해진다.
- **범위는 있는 것만 적는다.** 혈압은 KSN 자료의 대상이 아니고
  `CHRONIC_NUTRITION_SOURCES.md` 에도 목표 수치가 정리돼 있지 않다 → `reference=None`.
  근거를 찾기 전에는 쓰지 않는다.
- **달성/미달을 판정하지 않는다.** 범위를 나란히 놓는 것과 "정상입니다"라고 말하는 것은
  다르다. 후자는 진단이다 (`CKD_NUTRITION.md` §'노출 원칙').

## 식이 상한과 혈액 목표는 다른 값이다

칼륨에 "하루 상한이 없다"(KDOQI 2020)는 것은 **식이 칼륨** 이야기다. 같은 학회 자료가
**혈청 칼륨에는 3.5–5.5 mEq/L 와 "5 이하가 안전"을 명시한다.** 둘을 섞으면 안 된다 —
우리가 게이지를 그리지 않기로 한 것은 앞의 것이고, 여기 있는 것은 뒤의 것이다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LabPanel:
    code: str
    label: str
    unit: str
    # 정상범위·목표를 사람이 읽는 문장으로. 수치 비교를 코드가 하지 않는 이유는
    # 병기·나이·동반질환에 따라 목표가 갈리기 때문이다(인이 대표적이다).
    reference: str | None
    source: str
    # 어느 질환에서 주로 보는가. 앱이 사용자 질환에 맞는 항목을 앞에 두는 데 쓴다.
    conditions: tuple[str, ...]
    # 소수점 자리. 입력 검증과 표시에 함께 쓴다.
    decimals: int = 1


_KSN1_P47 = "대한신장학회 「투석 전 단계의 만성콩팥병 환자를 위한 영양-식생활 관리」 p47"
_KSN1_P48 = "대한신장학회 「투석 전 단계의 만성콩팥병 환자를 위한 영양-식생활 관리」 p48"
_KSN1_P49 = "대한신장학회 「투석 전 단계의 만성콩팥병 환자를 위한 영양-식생활 관리」 p49"

PANELS: tuple[LabPanel, ...] = (
    LabPanel(
        code="egfr",
        label="사구체여과율(eGFR)",
        unit="mL/min",
        reference="정상 90–120 mL/분. 콩팥이 1분 동안 걸러 주는 혈액의 양입니다.",
        source=_KSN1_P47,
        conditions=("ckd",),
    ),
    LabPanel(
        code="creatinine",
        label="혈청 크레아티닌",
        unit="mg/dL",
        reference="사구체여과율을 계산하는 입력값입니다. 높을수록 여과율은 낮게 계산됩니다.",
        source=_KSN1_P47,
        conditions=("ckd",),
        decimals=2,
    ),
    LabPanel(
        code="potassium",
        label="혈청 칼륨",
        unit="mEq/L",
        reference="정상 3.5–5.5 mEq/L. 5 mEq/L 이하로 유지하는 것이 안전합니다.",
        source=_KSN1_P48,
        conditions=("ckd",),
    ),
    LabPanel(
        code="phosphorus",
        label="혈청 인",
        unit="mg/dL",
        reference="콩팥병 3–4단계는 2.4–4.5 mg/dL, 5단계는 3.5–5.5 mg/dL로 조절합니다.",
        source=_KSN1_P48,
        conditions=("ckd",),
    ),
    LabPanel(
        code="calcium",
        label="칼슘",
        unit="mg/dL",
        reference="정상 8.4–10.2 mg/dL. 고칼슘혈증에 유의합니다.",
        source=_KSN1_P48,
        conditions=("ckd",),
    ),
    LabPanel(
        code="bicarbonate",
        label="중탄산염",
        unit="mEq/L",
        reference="22 mEq/L 이상인지 확인합니다. 낮으면 대사성 산증을 의심합니다.",
        source=_KSN1_P48,
        conditions=("ckd",),
    ),
    LabPanel(
        code="hemoglobin",
        label="혈색소",
        unit="g/dL",
        reference="목표 10.5–12.5 g/dL. 남자 13 미만, 여자 12 미만이면 빈혈로 진단합니다.",
        source=_KSN1_P47,
        conditions=("ckd",),
    ),
    LabPanel(
        code="albumin",
        label="혈청 알부민",
        unit="g/dL",
        reference="정상 3.5–5.2 g/dL. 영양 상태를 반영하는 지표라 낮은 정상 범위 이상을 유지합니다.",
        source=_KSN1_P47,
        conditions=("ckd",),
        decimals=2,
    ),
    LabPanel(
        code="acr",
        label="요알부민–크레아티닌비",
        unit="µg/mg",
        reference="30–299는 미세알부민뇨, 300 이상은 현성단백뇨입니다. 소변으로 새는 단백질의 양입니다.",
        source=_KSN1_P49,
        conditions=("ckd",),
    ),
    LabPanel(
        code="hba1c",
        label="당화혈색소(HbA1c)",
        unit="%",
        reference="일반적으로 7.0% 이내로 유지합니다. 콩팥기능이 많이 감소했거나 고령이면 목표를 완화할 수 있습니다.",
        source=_KSN1_P48,
        conditions=("diabetes", "ckd"),
    ),
    LabPanel(
        code="glucose_fasting",
        label="공복혈당",
        unit="mg/dL",
        reference="식전 90–130 mg/dL 사이를 목표로 합니다.",
        source=_KSN1_P48,
        conditions=("diabetes",),
        decimals=0,
    ),
    LabPanel(
        code="ldl",
        label="LDL 콜레스테롤",
        unit="mg/dL",
        reference="당뇨가 있거나 콩팥병 3–4단계라면 100 mg/dL 미만으로 조절합니다.",
        source=_KSN1_P49,
        conditions=("ckd", "diabetes"),
        decimals=0,
    ),
    # 혈압은 KSN 자료의 대상이 아니고 우리 근거 문서에도 목표 수치가 정리돼 있지 않다.
    # **기록만 받고 범위는 비운다** — 근거를 찾기 전에는 쓰지 않는다.
    LabPanel(
        code="bp_systolic",
        label="수축기 혈압",
        unit="mmHg",
        reference=None,
        source="사용자 입력(가정 혈압계·진료 측정값)",
        conditions=("hypertension", "ckd"),
        decimals=0,
    ),
    LabPanel(
        code="bp_diastolic",
        label="이완기 혈압",
        unit="mmHg",
        reference=None,
        source="사용자 입력(가정 혈압계·진료 측정값)",
        conditions=("hypertension", "ckd"),
        decimals=0,
    ),
)

_BY_CODE: dict[str, LabPanel] = {panel.code: panel for panel in PANELS}

# 입력 상한. 오타(85 를 850 으로)를 걸러 내는 방어선이지 의학적 판정이 아니다 —
# 그래서 넉넉하게 잡는다. 음수는 어떤 항목에서도 의미가 없다.
_MAX_VALUE: dict[str, float] = {
    "egfr": 300,
    "creatinine": 50,
    "potassium": 15,
    "phosphorus": 30,
    "calcium": 30,
    "bicarbonate": 60,
    "hemoglobin": 30,
    "albumin": 10,
    "acr": 30000,
    "hba1c": 30,
    "glucose_fasting": 1000,
    "ldl": 500,
    "bp_systolic": 300,
    "bp_diastolic": 200,
}


def get_panel(code: str) -> LabPanel | None:
    return _BY_CODE.get(code)


def max_value(code: str) -> float:
    """오타 방어용 상한. 정의가 없으면 넉넉한 기본값."""
    return _MAX_VALUE.get(code, 100000)
