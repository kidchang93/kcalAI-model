"""서비스 예외 — `main.py` 의 전역 핸들러가 `{"detail": str(error)}` 로 바꾼다.

BadRequestError → 400 · ForbiddenError → 403 · NotFoundError → 404.

- 메시지는 **사용자에게 그대로 보인다.** 서비스가 만든 한국어 문구만 담는다(내부 예외 원문 금지).
- 내장 예외의 서브클래스라 기존 `except ValueError`·`pytest.raises(LookupError)` 가 그대로 잡는다.
- 내장 `ValueError`·`LookupError` 자체는 매핑하지 않는다 — `KeyError`·pydantic `ValidationError`
  같은 버그까지 4xx 로 덮이기 때문이다.
- 상태코드가 402(`PlanLimitError`)·502·503 처럼 다르거나, 라우트마다 문구·로깅이 달라야 하면
  여기 넣지 않고 라우트가 변환한다.
"""


class BadRequestError(ValueError):
    pass


class ForbiddenError(PermissionError):
    pass


class NotFoundError(LookupError):
    pass
