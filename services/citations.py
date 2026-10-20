"""출처 링크 — 화면에 보이는 근거 문장에서 문헌을 찾아 원문 링크를 붙인다.

2026-10-20 App Store 1.4.1 반려: 의료 정보에는 **사용자가 쉽게 찾을 수 있는 출처 링크**가 있어야
한다. 근거 문장(가이드 `sources`·검사 `source`·나트륨 `basis`·고지문)은 이미 문헌 이름을 담고
있으므로 문장은 그대로 두고, 그 이름으로 이 목록에서 링크를 찾는다 (DATA_MODEL 34장).

**근거 문장에 새 문헌을 쓰면 여기에도 넣는다.** 링크를 못 찾는 근거 문장은
`tests/test_citations.py` 가 잡는다 — 출처 텍스트만 있고 링크가 없는 상태가 이번 반려 사유다.

URL 은 2026-10-20 에 하나씩 열어 확인했다. 학회 PDF 는 주소가 자주 바뀌니, 깨지면 문헌 이름이
아니라 이 표의 `url` 만 고친다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    code: str
    title: str
    publisher: str
    url: str
    # 근거 문장에서 이 문헌을 알아보는 표기. 문장마다 쪽수·약칭이 달라 여러 개다.
    aliases: tuple[str, ...]


# 대한신장학회 e북은 파일 이름이 한글이라 퍼센트 인코딩해 둔다(앱이 그대로 연다).
_KSN_EBOOK = "https://ksn.or.kr/upload/general/ebook/"

CITATIONS: tuple[Citation, ...] = (
    Citation(
        code="ksn1",
        title="투석 전 단계의 만성콩팥병 환자를 위한 영양-식생활 관리 (1권)",
        publisher="대한신장학회",
        url=_KSN_EBOOK
        + "1%EA%B6%8C%20%ED%88%AC%EC%84%9D%20%EC%A0%84%20%EB%8B%A8%EA%B3%84%EC%9D%98%20"
        "%EB%A7%8C%EC%84%B1%EC%BD%A9%ED%8C%A5%EB%B3%91%20%ED%99%98%EC%9E%90%EB%A5%BC%20"
        "%EC%9C%84%ED%95%9C%20%EC%98%81%EC%96%91-%EC%8B%9D%EC%83%9D%ED%99%9C%20%EA%B4%80%EB%A6%AC.pdf",
        # "대한신장학회 지침 분류"는 칼륨·인 등급 고지(TIER_NOTICE)의 표기다 — 1·2권이 함께 근거다.
        aliases=("투석 전 단계의 만성콩팥병", "영양-식생활 관리 1권", "대한신장학회 지침 분류"),
    ),
    Citation(
        code="ksn2",
        title="혈액투석 환자를 위한 영양-식생활 관리 (2권)",
        publisher="대한신장학회",
        url=_KSN_EBOOK
        + "2%EA%B6%8C%20%ED%98%88%EC%95%A1%ED%88%AC%EC%84%9D%20%ED%99%98%EC%9E%90%EB%A5%BC%20"
        "%EC%9C%84%ED%95%9C%20%EC%98%81%EC%96%91-%EC%8B%9D%EC%83%9D%ED%99%9C%20%EA%B4%80%EB%A6%AC.pdf",
        # "…1권 p101·105, 2권 p114" 처럼 2권이 이름 없이 이어 붙는 표기가 있다.
        aliases=("혈액투석 환자를 위한 영양-식생활", "영양-식생활 관리 2권", "2권 p", "대한신장학회 지침 분류"),
    ),
    Citation(
        code="kdigo2024",
        title="KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD",
        publisher="KDIGO",
        url="https://kdigo.org/guidelines/ckd-evaluation-and-management/",
        aliases=("KDIGO 2024",),
    ),
    Citation(
        code="kdoqi2020",
        title="KDOQI Clinical Practice Guideline for Nutrition in CKD: 2020 Update",
        publisher="Am J Kidney Dis (NKF)",
        url="https://pubmed.ncbi.nlm.nih.gov/32829751/",
        aliases=("KDOQI 2020",),
    ),
    Citation(
        code="kdca_dialysis_diet",
        title="투석환자의 식이요법",
        publisher="질병관리청 국가건강정보포털",
        url="https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=5796",
        aliases=("국가건강정보포털",),
    ),
    Citation(
        code="ksh2026",
        title="2026 고혈압 진료지침 (제6판)",
        publisher="대한고혈압학회",
        url="https://www.koreanhypertension.org/reference/guide",
        aliases=("대한고혈압학회 진료지침 2026",),
    ),
    Citation(
        code="kda2025",
        title="당뇨병 진료지침 제9판 (2025)",
        publisher="대한당뇨병학회",
        url="https://diabetes.or.kr/bbs/?code=guide",
        aliases=("대한당뇨병학회 진료지침 2025",),
    ),
    Citation(
        code="kdri2025",
        title="2025 한국인 영양소 섭취기준",
        publisher="보건복지부·한국영양학회",
        url="https://www.kns.or.kr/FileRoom/FileRoom.asp?BoardID=Kdr",
        aliases=("한국인 영양소 섭취기준 2025",),
    ),
)

# 질환 → 그 질환의 식이 판정(경고·추천 등급·식이 도움말)이 기대는 문헌. 근거 문장 없이
# 판정만 내려가는 응답(경고 문장·추천 등급)에 붙인다. 근거 문서가 없는 질환은 넣지 않는다.
_CONDITION_CITATIONS: dict[str, tuple[str, ...]] = {
    "ckd": ("ksn1", "ksn2"),
    "hypertension": ("ksh2026",),
    "diabetes": ("kda2025",),
}

def _link(citation: Citation) -> dict:
    return {"title": citation.title, "publisher": citation.publisher, "url": citation.url}


def find(*texts: str | None) -> list[dict]:
    """근거 문장들에 나오는 문헌의 링크. 문장에 처음 나온 순서대로, 같은 문헌은 한 번만."""
    joined = "\n".join(text for text in texts if text)
    found: list[tuple[int, Citation]] = []

    for citation in CITATIONS:
        positions = [joined.find(alias) for alias in citation.aliases if alias in joined]

        if positions:
            found.append((min(positions), citation))

    # 안정 정렬이라 같은 자리(1·2권이 함께 걸린 표기)는 목록 순서를 따른다.
    found.sort(key=lambda item: item[0])

    return [_link(citation) for _, citation in found]


def for_conditions(codes: list[str]) -> list[dict]:
    """질환 코드들의 판정 근거 문헌. 순서는 문헌 목록 순서다."""
    wanted = {code for condition in codes for code in _CONDITION_CITATIONS.get(condition, ())}

    return [_link(citation) for citation in CITATIONS if citation.code in wanted]


def merge(*groups: list[dict]) -> list[dict]:
    """여러 링크 목록을 순서를 지키며 합친다. 같은 URL 은 한 번만."""
    seen: set[str] = set()
    merged: list[dict] = []

    for group in groups:
        for link in group:
            if link["url"] not in seen:
                seen.add(link["url"])
                merged.append(link)

    return merged


def all_links() -> list[dict]:
    """서버가 쓰는 문헌 전체 — 앱의 '근거와 출처' 화면이 그린다."""
    return [_link(citation) for citation in CITATIONS]
