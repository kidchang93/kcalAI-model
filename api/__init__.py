"""api 패키지.

라우터는 각 서브모듈에서 **직접** import한다(`main.py`). 이 `__init__`을 비워 두는 이유:
예전엔 여기서 predict_router를 즉시 import해, `api.auth_api` 같은 가벼운 모듈을 import해도
predict_service(→YOLO/torch)가 딸려왔다. 이제 `api.auth_api`만 import하면 torch가 로드되지
않으므로, API 레이어 테스트가 특정 라우터만 가볍게 올릴 수 있다.
"""
