import logging
import os
from logging.handlers import RotatingFileHandler


def get_level_name(level):
    return logging.getLevelName(level).lower()

def setup_level_logger(level, log_dir="logs", max_bytes=1 * 1024 * 1024, backup_count=5):
    """
    지정된 로그 레벨의 로그만 기록하는 로거를 생성
    :param level:
    :param log_dir:
    :param max_bytes:
    :param backup_count:
    :return:
    """
    os.makedirs(log_dir, exist_ok=True)

    level_name = get_level_name(level)
    logger = logging.getLogger(level_name)
    logger.setLevel(level)

    log_file = os.path.join(log_dir, f"{level_name}_log.txt")

    # 이미 설정된 로거는 재사용
    if logger.hasHandlers():
        return logger

    # 핸들러 생성
    handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )

    # 로그 필터: 해당 레벨만 기록
    class LevelFilter(logging.Filter):
        def filter(self, record):
            return record.levelno == level

    handler.addFilter(LevelFilter())

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # 콘솔 핸들러도 설정
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    console.addFilter(LevelFilter())

    logger.addHandler(handler)
    logger.addHandler(console)

    return logger