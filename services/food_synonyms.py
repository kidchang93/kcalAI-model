"""음식명 동의어·표기 변형 — estimate 조회 전 검색 후보를 넓힌다 (DATA_MODEL.md 13장).

pg_trgm 은 동의어를 잡지 못한다("계란찜" vs "달걀찜"). 식약처 DB 에는 양쪽
표기가 공존하므로(계란 9행·달걀 34행) 파괴적 치환이 아니라 **변형 후보를
전부 만들어 조회하고 최적을 고르는** 방식을 쓴다. 선택은 nutrition_service 가 한다.
"""

# 표기 변형 규칙 (from → to). 순서는 결정성에 영향 없다 — 후보 집합만 만든다.
# 양쪽 표기가 DB 에 공존하면 양방향, 한쪽이 0건이면 단방향만 둔다(2026-07-11 실측).
# "무우"→"무" 같은 짧은 단어의 역방향은 오폭(무침→무우침)이라 넣지 않는다.
_SUBSTITUTION_RULES: tuple[tuple[str, str], ...] = (
    ("계란", "달걀"),
    ("달걀", "계란"),
    ("쇠고기", "소고기"),  # DB 에 쇠고기 0건
    ("낚지", "낙지"),  # 낚지는 오기 — DB 에 없음
    ("쭈꾸미", "주꾸미"),
    ("주꾸미", "쭈꾸미"),
    ("소세지", "소시지"),
    ("소시지", "소세지"),
    ("야끼", "야키"),
    ("야키", "야끼"),
    ("후라이", "프라이"),
    ("프라이", "후라이"),
    ("브로컬리", "브로콜리"),
    ("케사디야", "퀘사디아"),
    ("퀘사디아", "케사디야"),
)

# 라벨 전체 별칭 — 표기 변형으로는 못 잇는 동일 음식의 다른 이름.
# 값(대상)이 DB 에 실재하는지 확인한 것만 추가한다 (2026-07-11 실측).
# 일반명→특정 음식 매핑(생선구이→고등어구이 등)은 넣지 않는다 — 다른 음식이다.
_LABEL_ALIASES: dict[str, str] = {
    "스시": "초밥",
    "생선초밥": "초밥",
    "후렌치후라이": "감자튀김",
    "왕돈가스": "돈가스",
    "왕만두": "만두",
    "컵라면": "라면",
    "밥": "쌀밥",
    "나가사끼짬뽕": "짬뽕",
    "찜닭": "닭찜",
    "동그랑땡": "완자전",
    "커리": "카레라이스",  # "카레↔커리" 치환은 떡볶이_카레로 오폭해서 별칭으로만 잇는다
    "치킨카레": "카레라이스",
    "버터쿠키": "쿠키",  # trgm 은 "버터"(가공식품 일반 항목)로 오폭한다
    "아이스커피": "액상커피",  # trgm 은 "아이스티"로 오폭한다
    "아이스라떼": "액상커피",
    "요구르트": "발효유",
    "액상요구르트": "유산균음료",
}

# 폭주 방지 상한. 규칙이 겹쳐도 실제 후보는 라벨당 2~4개 수준이다.
_MAX_VARIANTS = 8


def expand_variants(label: str) -> list[str]:
    """검색 후보 목록을 만든다. 원 라벨이 항상 첫 번째다 (선택 우선순위의 기준).

    별칭·치환 규칙을 후보 집합이 더 자라지 않을 때까지 반복 적용한다
    ("계란후라이" → 달걀후라이·계란프라이·달걀프라이 조합까지 도달).
    """
    variants = [label]

    alias = _LABEL_ALIASES.get(label)
    if alias is not None:
        variants.append(alias)

    changed = True
    while changed and len(variants) < _MAX_VARIANTS:
        changed = False
        for variant in list(variants):
            for source, target in _SUBSTITUTION_RULES:
                if source not in variant:
                    continue
                produced = variant.replace(source, target)
                if produced not in variants:
                    variants.append(produced)
                    changed = True
                    if len(variants) >= _MAX_VARIANTS:
                        return variants

    return variants
