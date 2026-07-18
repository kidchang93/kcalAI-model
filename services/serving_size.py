"""serving_desc 문자열에서 1인분 무게(serving_size_g)를 뽑는 공용 헬퍼.

serving_size_g 의 의미: 이 음식 1인분(= serving_desc 가 가리키는 1회 제공량)이 몇 g 인가.
앱은 serving_ratio = 사용자입력g ÷ serving_size_g 로 kcal 을 재환산한다 (DATA_MODEL.md 12·19장).

- `ml` 은 밀도≈1 로 g 과 동일 수치 취급(국·죽·면 국물류) — 숫자만 뽑아 그대로 쓴다.
- g/ml 뒤에 단어 경계가 있어야 매칭한다 — "100g당"(per-100g 기준)은 '당'이 word char 라
  경계가 없어 매칭되지 않고 None 이 된다. 원물의 "100g당" 은 1회 제공량이 아니라 기준량이라
  serving_size_g 를 남기지 않는 것이 옳다(앱은 인분 모드로 폴백).
- "1그릇"·"반 모"·"6개"처럼 무게가 없으면 None.

import_mfds_food.py 는 이 헬퍼를 쓰지 않는다 — 그쪽은 원본 '식품중량' 필드(parse_amount)의
숫자를 직접 serving_size_g 로 넣는다. 이 헬퍼는 serving_desc 텍스트만 가진 경로
(correct_common_foods·seed_curated_foods·llm 추정)에서 쓴다.
"""

import re
from decimal import Decimal

# "약 200g" · "(50g)" · "200ml" · "500ml" 등에서 숫자만. g/ml 뒤 단어 경계 필수("100g당" 제외).
_SERVING_G_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|ml)\b", re.IGNORECASE)


def parse_serving_size_g(serving_desc: str | None) -> Decimal | None:
    """serving_desc 에서 1인분 무게(g, 소수 1자리)를 뽑는다. 못 뽑으면 None. ml 은 g 과 동일 수치."""
    if not serving_desc:
        return None
    match = _SERVING_G_PATTERN.search(serving_desc)
    if match is None:
        return None
    value = Decimal(match.group(1)).quantize(Decimal("0.1"))
    if value <= 0:
        return None
    return value
