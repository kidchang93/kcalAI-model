"""앱 로거. 모듈마다 `logger = get_logger(__name__)` 하나를 쓴다.

INFO 이하는 `task-logs/info_log.txt`, ERROR 이상은 `task-logs/error_log.txt` 로 갈린다.
콘솔에도 함께 나간다 — systemd(journalctl)와 cron 로그(`task-logs/cron_*.log`)가 이 출력을 받는다.

핸들러는 공통 상위 로거 `kcal` 에 **한 번만** 붙는다(재import·테스트에도 중복 부착 없음).
root 에 붙이지 않는 이유: httpx·urllib3 같은 서드파티 로그까지 파일로 들어오는데, 토스 요청
URL 에는 빌링키가 실린다. uvicorn 기본 설정은 root 에 핸들러를 달지 않아 중복 출력도 없다.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "task-logs"
_PARENT = logging.getLogger("kcal")


def _rotating(filename: str) -> RotatingFileHandler:
    return RotatingFileHandler(
        os.path.join(LOG_DIR, filename), maxBytes=1024 * 1024, backupCount=5, encoding="utf-8"
    )


def get_logger(name: str) -> logging.Logger:
    if not _PARENT.handlers:
        os.makedirs(LOG_DIR, exist_ok=True)

        info_file = _rotating("info_log.txt")
        info_file.addFilter(lambda record: record.levelno < logging.ERROR)

        error_file = _rotating("error_log.txt")
        error_file.setLevel(logging.ERROR)

        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

        for handler in (info_file, error_file, logging.StreamHandler()):
            handler.setFormatter(formatter)
            _PARENT.addHandler(handler)

        _PARENT.setLevel(logging.INFO)

    return logging.getLogger(f"kcal.{name}")
