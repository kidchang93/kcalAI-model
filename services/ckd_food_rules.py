"""신장병(CKD) 식이 규칙 — 대한신장학회 지침을 코드화한 단일 근거 모듈.

경고 판정(`nutrition_service.get_record_warnings`)과 식단 추천
(`recommendation_service`)이 **공유**하는 CKD 도메인 지식이다. 두 곳이 서로 다른
기준을 쓰지 않도록 여기 한 곳에만 둔다.

출처 (전부 무료 공개 자료):
- 대한신장학회 「제1권: 투석 전 단계의 만성콩팥병 환자를 위한 영양-식생활 관리」
  (이하 KSN1) — 단백질 p99, 염분 p101·105, 과일 p107, 채소 p108, 간식 p110.
- 대한신장학회 「제2권: 혈액투석 환자를 위한 영양-식생활 관리」
  (이하 KSN2) — 단백질 1.2 g/kg, 열량, 나트륨 3,000 mg, 인 800–1,000 mg(p141),
  과일·채소 칼륨 3단계 분류.
- 신장질환 식품교환표(1997) · 농촌진흥청 제9개정판 표준식품성분표 (칼륨 3단계 분류의 원 출처).
- 질병관리청 국가건강정보포털 '만성콩팥병'·'투석환자의 식이요법' (복막투석 보조).

⚠️ 이것은 **처방이 아니라 지침의 상대적 분류**다. 실제 제한 여부·목표량은 병기·혈액검사·
투석 방식에 따라 개별화되며 의료진·영양사 상담이 필요하다. 사용자 노출 시 항상 고지문을 붙인다.
칼륨·인 제한은 **진행된 병기·고칼륨혈증·고인산혈증에서** 적용된다 (초기 CKD엔 과도한 제한이 오히려 해롭다, KSN1 서문).
"""

from __future__ import annotations

# ── 병기(투석 방식) ─────────────────────────────────────────────────────────
# 단백질 제한 방향이 병기에서 정반대로 뒤집힌다: 비투석은 제한, 투석은 증량 (KSN1 서문, KSN2).
CKD_STAGE_NONDIALYSIS = "nondialysis"  # 투석 전(보존기) CKD
CKD_STAGE_HEMODIALYSIS = "hemodialysis"  # 혈액투석
CKD_STAGE_PERITONEAL = "peritoneal"  # 복막투석

CKD_STAGE_LABELS: dict[str, str] = {
    CKD_STAGE_NONDIALYSIS: "투석 전(보존기)",
    CKD_STAGE_HEMODIALYSIS: "혈액투석",
    CKD_STAGE_PERITONEAL: "복막투석",
}

# 병기별 하루 목표. (min, max) 튜플은 범위, 단일 상한은 *_max.
# 처방이 아니라 지침 권장 범위다 — g/kg 는 표준체중(IBW) 기준.
STAGE_TARGETS: dict[str, dict] = {
    CKD_STAGE_NONDIALYSIS: {
        "protein_g_per_kg": (0.6, 0.8),  # KSN1 p99 (매우 저하 시 0.3–0.5, 저알부민 없으면 ~0.8)
        "sodium_mg_max": 2000,  # 소금 5 g (KSN1 p101·105)
        "phosphorus_mg_max": 1000,  # 진행 병기에서 (일반 800–1,000)
        "potassium_restricted": False,  # 고칼륨혈증 있을 때만 (KSN1)
        "energy_kcal_per_kg": (30, 35),  # KSN1 p97
        "source": "KSN1 p97–101 · 국가건강정보포털",
    },
    CKD_STAGE_HEMODIALYSIS: {
        "protein_g_per_kg": (1.2, 1.2),  # 증량 — 투석 중 아미노산 손실 보충 (KSN2)
        "sodium_mg_max": 3000,  # KSN2
        "phosphorus_mg_max": 1000,  # 800–1,000 mg 또는 17 mg/kg (KSN2 p141)
        "potassium_restricted": True,  # 지속적 제한 (KSN2)
        "energy_kcal_per_kg": (30, 35),  # 60세 미만 35, 60세 이상 30–35 (KSN2)
        "source": "KSN2 (단백질 1.2 g/kg · 인 p141)",
    },
    CKD_STAGE_PERITONEAL: {
        "protein_g_per_kg": (1.2, 1.3),  # 증량 (복막으로 단백 손실) — 국가건강정보포털/KDIGO
        "sodium_mg_max": 3000,
        "phosphorus_mg_max": 1000,
        "potassium_restricted": True,
        "energy_kcal_per_kg": (30, 35),  # 투석액 포도당 흡수분 감안
        "source": "국가건강정보포털 · KDIGO 2024 (본 지침서 2권 범위 밖)",
    },
}

# ── 칼륨 3단계 분류 (신장질환 식품교환표 1997 / 농진청 9개정판, KSN1 p107–108 · KSN2) ──
# 이름 부분일치(substring)로 라벨에 매칭한다 — meta_service.match_exclude_keyword 와 같은 규약.

# 채소: 두 지침(KSN1·KSN2) 동일.
# ⚠️ 1글자 토큰(김·무)은 부분일치라 오탐(김→김치, 무→오이무침)이 커서 제외했다 —
#    저칼륨 '누락'은 안전(과잉 주의 안 함)하지만 오탐은 잘못된 경고를 만든다. 무청은 유지.
VEGETABLE_K_LOW: tuple[str, ...] = (
    "풋고추", "더덕", "오이", "배추", "달래", "당근", "양상추", "대파", "치커리",
    "마늘쫑", "피망", "팽이버섯", "표고버섯", "양파", "양배추", "냉이", "무청",
    "가지", "숙주", "고사리", "고비", "콩나물", "깻잎", "아스파라거스", "죽순",
)
VEGETABLE_K_MID: tuple[str, ...] = (
    "도라지", "두릅", "상추", "샐러리", "셀러리", "케일", "연근", "우엉", "풋마늘",
    "열무", "고구마줄기", "느타리버섯", "애호박",
)
VEGETABLE_K_HIGH: tuple[str, ...] = (
    "아욱", "근대", "머위", "미나리", "부추", "쑥", "시금치", "취나물", "미역",
    "단호박", "늙은 호박", "늙은호박", "쑥갓", "고춧잎",
)

# 과일: 비투석(KSN1)은 다소 관대, 혈액투석(KSN2)은 더 엄격(귤·포도가 저→중으로 강등).
# 아래는 **투석(엄격) 기준**을 기본으로 인코딩한다 — 과잉 주의는 안전 측 오류다.
# 비투석 완화가 필요하면 fruit_potassium_tier(on_dialysis=False) 로 사과·귤·포도를 저칼륨으로 본다.
FRUIT_K_LOW: tuple[str, ...] = (
    "사과", "단감", "연시", "레몬", "자두", "파인애플", "금귤", "딸기", "블루베리", "통조림",
)
# ⚠️ "배"(1글자)는 배추(저칼륨 채소)와 충돌해 제외했다 — 배(pear) 미분류는 안전 측 오류.
FRUIT_K_MID: tuple[str, ...] = (
    "귤", "백도", "복숭아", "황도", "살구", "수박", "자몽", "포도", "거봉", "오렌지",
    "망고", "아보카도",
)
FRUIT_K_HIGH: tuple[str, ...] = (
    "곶감", "멜론", "바나나", "앵두", "참외", "천도복숭아", "방울토마토", "토마토", "키위",
)
# 비투석(KSN1)에서 저칼륨으로 분류되는 과일 (투석 기준 중칼륨에서 완화).
FRUIT_K_LOW_NONDIALYSIS_EXTRA: tuple[str, ...] = ("귤", "포도")

# ── 인(P) 고함량 — 제한 대상 (KSN1 p110, KSN2 p141) ──────────────────────────
# 살코기·생선·달걀 같은 '필수 단백질원'은 제외한다 — 인이 있어도 끊으면 안 되는 음식이라
# 인결합제로 관리한다. 여기엔 **줄일 수 있는 초과·첨가 인 공급원**만 담는다.
HIGH_PHOSPHORUS_KEYWORDS: tuple[str, ...] = (
    # 유제품
    "우유", "치즈", "요구르트", "요플레", "연유", "분유", "아이스크림",
    # 견과류
    "아몬드", "땅콩", "호두", "잣", "캐슈", "피스타치오", "해바라기씨", "견과",
    # 잡곡·통곡
    "잡곡", "현미", "보리", "귀리", "오트밀", "통밀",
    # 탄산음료·초콜릿·코코아
    "콜라", "사이다", "탄산", "초콜릿", "초코", "코코아",
    # 가공식품(첨가 인)
    "햄", "소시지", "베이컨", "어묵", "가공",
    # 뼈째 먹는 생선
    "멸치", "뱅어포",
)

# ── 나트륨(Na) 고함량 — 제한 대상 (KSN1 p101·105 저염 식사) ──────────────────
# 기존 condition_types.exclude_keywords(ckd)="젓갈·장아찌·라면" 3개를 지침 근거로 확장.
# 김치·국·장류는 한식 주류라 과잉 경고를 피하려 넣지 않는다 — 대신 '저염' 조리를 안내한다.
HIGH_SODIUM_KEYWORDS: tuple[str, ...] = (
    "젓갈", "젓", "장아찌", "자반", "라면", "어묵", "햄", "소시지", "베이컨",
    "단무지", "절임", "짠지", "장조림", "명란", "김치", "깍두기", "총각김치",
)

# ── 저칼륨·저인 권장 간식/과일 (KSN1 p110 '어떤 간식을 먹을 수 있을까요') ──────
LOW_K_SNACKS: tuple[str, ...] = (
    "모닝빵", "식빵", "카스테라", "카스텔라", "팬케익", "팬케이크",
    "백설기", "절편", "가래떡", "사탕", "젤리",
)

# ── 칼륨 저감 조리법 안내 (KSN1 p108, KSN2) ──────────────────────────────────
POTASSIUM_REDUCTION_TIPS: tuple[str, ...] = (
    "칼륨이 많은 껍질과 줄기를 제거하세요.",
    "얇게 썰어 10배 이상의 물에 2시간 이상 담갔다가 헹궈 조리하세요.",
    "끓는 물에 데친 뒤 여러 번 헹궈 드세요.",
    "잡곡밥 대신 흰쌀밥을 드세요 (칼륨이 낮습니다).",
    "말린 과일은 칼륨이 2배 이상 높으니 신선·통조림 과일을 고르세요(시럽 제외).",
)
# 나트륨·인 저감 한 줄 안내 (KSN1 p101·110, KSN2 p141).
SODIUM_REDUCTION_TIP = "국물은 적게, 젓갈·장아찌·가공식품을 줄이면 나트륨을 낮출 수 있어요."
PHOSPHORUS_REDUCTION_TIP = "유제품·견과류·잡곡·탄산음료·가공식품은 인이 높으니 주의하세요."

# 전분질(곡류) 고칼륨 — KSN 채소/과일 3단계 분류엔 없지만 곡류로서 칼륨이 높다.
# KSN "잡곡밥 대신 흰쌀밥"(칼륨) 지침과 표준식품성분표 실측(고구마 100g당 ~370mg, 1인분 800mg+)에 근거.
# 1글자(밤·마)는 오탐이 커서 제외하고 2글자 이상 distinctive 만.
STARCHY_K_HIGH: tuple[str, ...] = ("고구마", "감자", "토란")

# 후보 풀 사전 제거용 — 고칼륨(채소+과일+전분질) 통합 키워드. 고→제한이라 병기 무관 동일.
POTASSIUM_HIGH_KEYWORDS: tuple[str, ...] = VEGETABLE_K_HIGH + FRUIT_K_HIGH + STARCHY_K_HIGH

# 1인분 실측 칼륨 상한 (mg). 이 값을 넘는 후보는 신장병 추천에서 배제한다.
# 근거: 신장질환 식품교환표 고칼륨 기준 >200 mg/교환단위(~70g 채소)를 한 끼 제공량(≈250~300g)으로
# 환산한 보수적 값. 고칼륨혈증은 급성 심정지 위험(KSN2)이라 정렬이 아닌 **하드 배제**로 다룬다.
# ⚠️ 이 상한은 지침의 절대 컷오프가 아니라 우리 정책값이다 — 조정 가능(docs/CKD_NUTRITION.md §4).
POTASSIUM_SERVING_HIGH_MG = 600

# 1인분 실측 인 상한 (mg). 초과 후보는 신장병 추천에서 배제한다 (예: 돼지 간 409 mg 같은 내장육).
# 칼륨보다 관대하게 둔다 — 인은 만성 위험이고 인결합제로 관리되며 필수 단백질원(생선·살코기 ~150~300 mg)을
# 지나치게 잘라내면 안 되기 때문이다(KSN2 p141). 하루 800~1,000 mg을 3~4끼로 나눈 몫보다 조금 위.
# ⚠️ 정책값 — 조정 가능. 추천을 인이 낮은 단백질원으로 유도하되 단백질 자체를 막지 않는 선.
PHOSPHORUS_SERVING_HIGH_MG = 400

# ── 1인분 실측값 → 상대 등급 (표시 전용) ────────────────────────────────────
#
# 추천 카드에 "칼륨 320 mg"만 띄우면 환자는 그게 높은지 낮은지 알 수 없다. 아래 경계로
# 저/중/고를 붙여 **상대 위치**만 보여준다 — 목표량 제시(처방)가 아니다.
# ⚠️ 지침에 1인분 절대 컷오프는 없다. 아래는 근거를 밝힌 우리 정책값이다 (docs/CKD_NUTRITION.md §4).
#
# 칼륨: 신장질환 식품교환표의 고칼륨 기준 >200 mg/교환단위를 그대로 1교환(=mid 시작)으로 두고,
#       2교환(400)부터 high. 600 초과는 애초에 추천에서 배제된다(POTASSIUM_SERVING_HIGH_MG).
POTASSIUM_TIER_MID_MG = 200
POTASSIUM_TIER_HIGH_MG = 400

# 인: 하루 800~1,000 mg(KSN2)을 3끼로 나눈 몫 ≈ 270~330 을 high 경계로, 그 절반을 mid 경계로.
PHOSPHORUS_TIER_MID_MG = 150
PHOSPHORUS_TIER_HIGH_MG = 300

# 등급 강도 — 두 근거(지침 이름 분류 · 실측 수치)가 엇갈리면 더 엄격한 쪽을 취한다.
TIER_ORDER: dict[str, int] = {"low": 0, "mid": 1, "high": 2}

# 등급을 노출할 때 함께 내려보내는 고지. 등급이 절대 기준이 아니라는 것과, 목표량은 병기·검사에
# 달렸다는 것을 반드시 같이 알린다 (docs/CKD_NUTRITION.md 3-4 노출 원칙). 앱은 이 문구를 그대로 쓴다.
TIER_NOTICE = (
    "낮음·보통·높음은 대한신장학회 지침 분류와 1인분 실측값을 기준으로 한 상대 안내예요. "
    "제한 여부와 목표량은 병기·검사 결과에 따라 다르니 의료진·영양사와 상담하세요."
)

# 경고 판정 축 — dietary_tag → (영양소 코드, 표시명). 경고 항목의 nutrient 필드에 실린다.
WARNING_AXES: tuple[tuple[str, str, str], ...] = (
    ("low_sodium", "sodium", "나트륨"),
    ("low_potassium", "potassium", "칼륨"),
    ("low_phosphorus", "phosphorus", "인"),
)
NUTRIENT_LABELS: dict[str, str] = {code: label for _tag, code, label in WARNING_AXES}

# 병기별 단백질 방향 안내 문구 (단백질 반전 — 코드가 헷갈리지 않게 문장으로도 남긴다).
PROTEIN_DIRECTION_NOTE: dict[str, str] = {
    CKD_STAGE_NONDIALYSIS: "투석 전에는 단백질을 0.6–0.8 g/kg로 제한합니다 (신장 부담 완화).",
    CKD_STAGE_HEMODIALYSIS: "혈액투석 중에는 단백질을 1.2 g/kg로 충분히 드세요 (투석으로 손실됨).",
    CKD_STAGE_PERITONEAL: "복막투석 중에는 단백질을 1.2–1.3 g/kg로 충분히 드세요.",
}


def _matches(label: str, keywords: tuple[str, ...]) -> str | None:
    """라벨에 키워드가 부분 문자열로 들어 있으면 그 키워드를 반환 (공백 무시)."""
    normalized = label.replace(" ", "")
    for keyword in keywords:
        if keyword.replace(" ", "") in normalized:
            return keyword
    return None


def potassium_tier(label: str, on_dialysis: bool = True) -> str | None:
    """음식 라벨의 칼륨 등급을 지침 분류로 판정한다.

    반환: "high" | "mid" | "low" | None(분류표에 없음).
    비투석(on_dialysis=False)이면 귤·포도를 저칼륨으로 완화한다 (KSN1).
    고→중→저 순으로 검사해 더 엄격한 등급이 이긴다.
    """
    if _matches(label, VEGETABLE_K_HIGH) or _matches(label, FRUIT_K_HIGH):
        return "high"
    if _matches(label, VEGETABLE_K_MID) or _matches(label, FRUIT_K_MID):
        if not on_dialysis and _matches(label, FRUIT_K_LOW_NONDIALYSIS_EXTRA):
            return "low"
        return "mid"
    if _matches(label, VEGETABLE_K_LOW) or _matches(label, FRUIT_K_LOW):
        return "low"
    return None


def potassium_high_match(label: str) -> str | None:
    """고칼륨(채소·과일·전분질) 식품이면 매칭 키워드를 반환한다 (경고 판정용)."""
    return _matches(label, POTASSIUM_HIGH_KEYWORDS)


def phosphorus_caution(label: str) -> str | None:
    """제한 대상 고인 식품이면 매칭 키워드를 반환한다."""
    return _matches(label, HIGH_PHOSPHORUS_KEYWORDS)


def sodium_caution(label: str) -> str | None:
    """제한 대상 고나트륨 식품이면 매칭 키워드를 반환한다."""
    return _matches(label, HIGH_SODIUM_KEYWORDS)


def _tier_by_mg(mg: float | None, mid_mg: float, high_mg: float) -> str | None:
    """1인분 실측 mg 을 저/중/고로 나눈다. 미측정(None)은 등급 없음."""
    if mg is None:
        return None
    if mg >= high_mg:
        return "high"
    if mg >= mid_mg:
        return "mid"
    return "low"


def _stricter(left: str | None, right: str | None) -> str | None:
    """두 등급 중 더 엄격한(높은) 쪽. 한쪽이 없으면 있는 쪽."""
    if left is None:
        return right
    if right is None:
        return left
    return left if TIER_ORDER[left] >= TIER_ORDER[right] else right


def potassium_display_tier(
    label: str,
    potassium_mg: float | None,
    on_dialysis: bool = True,
) -> str | None:
    """추천 카드에 띄울 칼륨 등급. 지침 이름 분류와 실측 등급 중 엄격한 쪽을 쓴다.

    근거가 하나도 없으면(분류표에 없고 미측정) None — 앱은 등급 배지를 숨긴다.
    """
    return _stricter(
        potassium_tier(label, on_dialysis),
        _tier_by_mg(potassium_mg, POTASSIUM_TIER_MID_MG, POTASSIUM_TIER_HIGH_MG),
    )


def phosphorus_display_tier(label: str, phosphorus_mg: float | None) -> str | None:
    """추천 카드에 띄울 인 등급. 고인 식품 이름에 걸리면 실측이 낮아도 high 로 본다.

    가공식품·유제품의 인은 흡수율이 높은 무기인(첨가물)이라 같은 mg 이라도 부담이 크다
    (KSN2 p141). 그래서 이름 근거를 실측보다 약하게 두지 않는다.
    """
    name_tier = "high" if phosphorus_caution(label) is not None else None
    return _stricter(
        name_tier,
        _tier_by_mg(phosphorus_mg, PHOSPHORUS_TIER_MID_MG, PHOSPHORUS_TIER_HIGH_MG),
    )


def stage_targets(stage: str) -> dict | None:
    """병기 코드의 하루 목표. 알 수 없는 병기는 None."""
    return STAGE_TARGETS.get(stage)
