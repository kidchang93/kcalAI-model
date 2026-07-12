
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api import (
    auth_router,
    predict_router,
    health_router,
    nutrition_router,
    consent_router,
    group_router,
    pet_router,
    meta_router,
    recommendation_router,
    account_router,
)
from crypto import ensure_production_crypto_config
from database import init_db
from log_utils import setup_level_logger
from services.auth_service import ensure_production_auth_config

# 관측 지표: 모든 요청의 경로·상태·응답시간을 구조적으로 남긴다.
request_logger = setup_level_logger(logging.INFO)

# database·crypto가 import 시점에 load_dotenv()를 수행하므로 .env 값이 반영돼 있다.
APP_ENV = os.getenv("APP_ENV", "development")

# 운영 기동 fail-fast: 개발 기본값(pepper·dev_code 노출·암호화 키)을 그대로 배포하면 서버가 뜨지 않는다.
if APP_ENV == "production":
    ensure_production_auth_config()
    ensure_production_crypto_config()

app = FastAPI(
    title="Food Classification API",
    description="음식 이미지를 분류하는 API",
    version="1.0.0",
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


@app.on_event("startup")
def on_startup():
    init_db()


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

# 웹 빌드(Expo export 산출물) 정적 서빙. 반드시 모든 API 라우터 등록 뒤에 mount 해야
# /api/** 가 라우터로 먼저 매칭된다. 빌드 산출물이 없는 개발 환경에서는 건너뛴다.
if os.path.isdir("webapp"):
    app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
