"""민감정보(건강) 앱 레이어 암호화.

AES-256-GCM으로 write 시 암호화, read 시 복호화한다. 키는 env(HEALTH_ENCRYPTION_KEY,
base64 32바이트)에서 읽고, 개발 기본값은 운영 기동 시 fail-fast로 막는다.

DB·쿼리 로그에는 암호문만 남는다. 대상 컬럼(혈액형·Rh)은 쿼리에 쓰이지 않으므로
앱 레이어 방식의 '조회 불가' 단점이 없다. (질병·알러지 코드는 JOIN·유니크·필터에 쓰이는
기능 키라 암호화하지 않는다 — 평문 코드 유지.)

계층: database.py·log_utils.py와 같은 최상위 유틸이다. models가 EncryptedString을,
0013 마이그레이션이 encrypt/decrypt를 import하며, 서비스 계층에 의존하지 않는다.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

# 개발 전용 기본 키 (sha256으로 정확히 32바이트 도출). 운영에서는 반드시 교체한다.
_DEFAULT_KEY = base64.b64encode(hashlib.sha256(b"kcal-development-only").digest()).decode("ascii")
HEALTH_ENCRYPTION_KEY = os.getenv("HEALTH_ENCRYPTION_KEY", _DEFAULT_KEY)

# 운영 배포를 막아야 하는 키 값 (미설정 기본값·빈 값).
_INSECURE_KEYS = {"", _DEFAULT_KEY}
_NONCE_BYTES = 12


def ensure_production_crypto_config() -> None:
    # APP_ENV=production 기동 시 main.py가 호출한다. 개발 기본 키로 배포하는 사고 방지.
    if HEALTH_ENCRYPTION_KEY in _INSECURE_KEYS:
        raise RuntimeError(
            "APP_ENV=production에서는 HEALTH_ENCRYPTION_KEY를 고유한 비밀값으로 설정해야 합니다."
        )


def _aesgcm() -> AESGCM:
    key = base64.b64decode(HEALTH_ENCRYPTION_KEY)
    if len(key) != 32:
        raise RuntimeError("HEALTH_ENCRYPTION_KEY는 base64로 인코딩된 32바이트여야 합니다 (AES-256).")
    return AESGCM(key)


def encrypt(plaintext: str | None) -> str | None:
    """평문 → base64(nonce + ciphertext+tag). None은 그대로 None."""
    if plaintext is None:
        return None
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = _aesgcm().encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(token: str | None) -> str | None:
    """base64(nonce + ciphertext+tag) → 평문. None은 그대로 None."""
    if token is None:
        return None
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return _aesgcm().decrypt(nonce, ciphertext, None).decode("utf-8")


class EncryptedString(TypeDecorator):
    """평문 str 컬럼을 DB에는 암호문(base64 VARCHAR)으로 저장한다.

    ORM이 write 시 process_bind_param(암호화), read 시 process_result_value(복호화)를
    자동 적용하므로 서비스·직렬화 코드는 평문을 그대로 다룬다.

    주의: DB에는 암호문이 저장되므로 이 컬럼으로 DB 레벨 JOIN·WHERE·UNIQUE는 불가능하다
    (암호문끼리 비교됨). 그런 용도는 앱 레이어에서 복호화 후 처리해야 한다.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
