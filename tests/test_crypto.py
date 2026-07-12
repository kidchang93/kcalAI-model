"""crypto.py 테스트 — AES-256-GCM 암복호화와 EncryptedString ORM 왕복."""

import base64

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select, text

import crypto
from crypto import EncryptedString, decrypt, encrypt


# --- 암복호화 프리미티브 --------------------------------------------------

@pytest.mark.parametrize("value", ["diabetes", "당뇨", "peanut", "A", "+", "여러 글자 한국어 값"])
def test_round_trip(value):
    assert decrypt(encrypt(value)) == value


def test_none_passthrough():
    assert encrypt(None) is None
    assert decrypt(None) is None


def test_ciphertext_differs_from_plaintext():
    token = encrypt("diabetes")
    assert token != "diabetes"
    base64.b64decode(token)  # base64로 디코드 가능해야 한다


def test_same_plaintext_encrypts_differently():
    # 랜덤 nonce라 같은 평문도 매번 다른 암호문이 된다 (결정성 노출 방지).
    assert encrypt("egg") != encrypt("egg")


def test_decrypt_tampered_fails():
    token = encrypt("milk")
    raw = bytearray(base64.b64decode(token))
    raw[-1] ^= 0x01  # 태그 변조
    tampered = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(Exception):
        decrypt(tampered)


# --- 운영 설정 게이트 ------------------------------------------------------

def test_production_crypto_rejects_default_key(monkeypatch):
    monkeypatch.setattr(crypto, "HEALTH_ENCRYPTION_KEY", crypto._DEFAULT_KEY)
    with pytest.raises(RuntimeError):
        crypto.ensure_production_crypto_config()


def test_production_crypto_passes_with_custom_key(monkeypatch):
    custom = base64.b64encode(b"a" * 32).decode()
    monkeypatch.setattr(crypto, "HEALTH_ENCRYPTION_KEY", custom)
    crypto.ensure_production_crypto_config()  # 예외 없음


# --- EncryptedString ORM 왕복 (DB, 마이그레이션 독립) ----------------------

_probe_meta = MetaData()
_probe = Table(
    "_enc_probe",
    _probe_meta,
    Column("id", Integer, primary_key=True),
    Column("secret", EncryptedString(255)),
)


def test_encrypted_string_at_rest(db):
    connection = db.get_bind()
    _probe_meta.create_all(bind=connection)  # 외부 트랜잭션 안 — 종료 시 롤백된다

    db.execute(_probe.insert().values(id=1, secret="당뇨"))
    db.flush()

    # 타입을 거친 read는 복호화된다.
    assert db.execute(select(_probe.c.secret)).scalar() == "당뇨"
    # 원시 SQL(text)은 타입 프로세싱을 거치지 않아 암호문이 나온다.
    raw = db.execute(text("select secret from _enc_probe where id = 1")).scalar()
    assert raw != "당뇨"
    base64.b64decode(raw)  # 저장 형식은 base64
