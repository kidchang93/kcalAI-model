from .predict_api import router as predict_router
from .file_upload_api import router as file_upload_router
from .auth_api import router as auth_router

__all__ = ["predict_router", "file_upload_router", "auth_router"]
