
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from api.account_api import router as account_router
from api.auth_api import router as auth_router
from api.consent_api import router as consent_router
from api.group_api import router as group_router
from api.health_api import router as health_router
from api.meta_api import router as meta_router
from api.nutrition_api import router as nutrition_router
from api.pet_api import router as pet_router
from api.predict_api import router as predict_router
from api.recommendation_api import router as recommendation_router
from api.subscription_api import router as subscription_router
from crypto import ensure_production_crypto_config
from database import init_db
from log_utils import setup_level_logger
from services.auth_service import ensure_production_auth_config
from services.gemini_vision_service import ensure_production_vision_config
from services.kakao_client import ensure_production_kakao_config
from services.subscription_service import PlanLimitError

# 관측 지표: 모든 요청의 경로·상태·응답시간을 구조적으로 남긴다.
request_logger = setup_level_logger(logging.INFO)

# database·crypto가 import 시점에 load_dotenv()를 수행하므로 .env 값이 반영돼 있다.
APP_ENV = os.getenv("APP_ENV", "development")

# 운영 기동 fail-fast: 개발 기본값(pepper·암호화 키·Gemini 키 부재·카카오 미설정)을 그대로
# 배포하면 서버가 뜨지 않는다. 비전은 Gemini 단일 백엔드라 키가 없으면 predict가 불가능하고,
# **카카오는 유일한 인증 수단**이라 설정이 없으면 아무도 로그인하지 못한다.
if APP_ENV == "production":
    ensure_production_auth_config()
    ensure_production_crypto_config()
    ensure_production_vision_config()
    ensure_production_kakao_config()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 기동 시 신규 테이블 생성(create_all). on_event("startup")은 0.118에서 deprecated라 lifespan 사용.
    init_db()
    yield


app = FastAPI(
    title="Food Classification API",
    description="음식 이미지를 분류하는 API",
    version="1.0.0",
    lifespan=lifespan,
)

cors_allow_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

cors_kwargs: dict = {
    "allow_origins": cors_allow_origins,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

# localhost 정규식 허용은 개발 편의용이다. 운영은 CORS_ALLOW_ORIGINS 명시 목록만 신뢰한다.
if APP_ENV != "production":
    cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

app.add_middleware(CORSMiddleware, **cors_kwargs)


@app.exception_handler(PlanLimitError)
async def handle_plan_limit(request: Request, error: PlanLimitError) -> JSONResponse:
    # 요금제 한도 초과는 어느 라우트에서 나든 같은 본문이어야 앱이 한 곳에서 업그레이드 화면으로
    # 분기할 수 있다. 그래서 각 api 모듈이 아니라 여기서 한 번만 변환한다.
    # 402 는 429(레이트리밋, 기다리면 풀림)와 달리 "결제해야 풀린다"는 뜻이다.
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "detail": error.message,
            "code": "plan_limit_exceeded",
            "resource": error.resource,
            "plan": error.plan_code,
            "limit": error.limit,
        },
    )


@app.middleware("http")
async def log_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    request_logger.info(
        f"request method={request.method} path={request.url.path} "
        f"status={response.status_code} duration_ms={duration_ms:.1f}"
    )
    return response


# 라우터 등록
app.include_router(auth_router, prefix="/api", tags=["Auth"])
app.include_router(predict_router, prefix="/api", tags=["Predict"])
app.include_router(health_router, prefix="/api", tags=["Health"])
app.include_router(nutrition_router, prefix="/api", tags=["Nutrition"])
app.include_router(consent_router, prefix="/api", tags=["Consent"])
app.include_router(group_router, prefix="/api", tags=["Groups"])
app.include_router(pet_router, prefix="/api", tags=["Pets"])
app.include_router(meta_router, prefix="/api", tags=["Meta"])
app.include_router(recommendation_router, prefix="/api", tags=["Recommendations"])
app.include_router(account_router, prefix="/api", tags=["Account"])
app.include_router(subscription_router, prefix="/api", tags=["Subscription"])

class ExpoWebFiles(StaticFiles):
    """Expo 웹 export 는 라우트마다 `<route>.html` 을 만든다 (`/auth` → `auth.html`).

    기본 StaticFiles 는 `/auth` 를 디렉터리로 찾다 404를 낸다. 그러면 **카카오 콜백이
    `/auth?code=...` 로 돌아왔을 때 웹 로그인이 404 로 끊긴다.** 새로고침·딥링크도 마찬가지다.
    그래서 404 일 때 `<path>.html` 을 한 번 더 시도한다.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404 or path.endswith(".html"):
                raise

            return await super().get_response(f"{path}.html", scope)


# 웹 빌드(Expo export 산출물) 정적 서빙. 반드시 모든 API 라우터 등록 뒤에 mount 해야
# /api/** 가 라우터로 먼저 매칭된다. 빌드 산출물이 없는 개발 환경에서는 건너뛴다.
if os.path.isdir("webapp"):
    app.mount("/", ExpoWebFiles(directory="webapp", html=True), name="webapp")
