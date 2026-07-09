from .predict_api import router as predict_router
from .file_upload_api import router as file_upload_router
from .auth_api import router as auth_router
from .health_api import router as health_router
from .nutrition_api import router as nutrition_router
from .consent_api import router as consent_router

__all__ = [
    "predict_router",
    "file_upload_router",
    "auth_router",
    "health_router",
    "nutrition_router",
    "consent_router",
]
