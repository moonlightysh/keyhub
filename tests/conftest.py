"""
pytest 共享 fixtures：
  - tmp_keypair: 生成临时 RSA-3072 密钥对（公钥/私钥/邮箱）
  - isolated_storage: 把 storage 模块的数据文件重定向到临时目录，测试间互不污染
  - app_client: 提供 Flask test client
"""
import os
import sys
import json
import tempfile
import shutil

import pytest
import pgpy
from pgpy.constants import (
    PubKeyAlgorithm, KeyFlags, HashAlgorithm,
    SymmetricKeyAlgorithm, CompressionAlgorithm,
)

# 让 tests 目录能 import 项目根目录的模块
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def tmp_keypair():
    """生成一对临时 GPG RSA-3072 密钥（带加密子密钥），整个 session 复用一次。"""
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 3072)
    uid = pgpy.PGPUID.new("Test User", email="alice@test.local")
    key.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB],
    )
    sub = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 3072)
    key.add_subkey(sub, usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage})
    return {
        "pub": str(key.pubkey),
        "priv": str(key),
        "email": "alice@test.local",
    }


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path):
    """
    把 storage 的数据目录重定向到 pytest 的 tmp_path，
    保证每个测试用独立的 users.json，互不污染。
    """
    import storage
    users_file = tmp_path / "users.json"
    users_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "USERS_FILE", str(users_file))
    monkeypatch.setattr(storage, "LOCK_FILE", str(tmp_path / ".users.json.lock"))
    return storage


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    """
    返回 Flask test client。
    自动隔离 storage 到临时目录，并确保以离线密文模式启动（不依赖 SMTP）。
    """
    import storage
    users_file = tmp_path / "users.json"
    users_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "USERS_FILE", str(users_file))
    monkeypatch.setattr(storage, "LOCK_FILE", str(tmp_path / ".users.json.lock"))

    # 强制离线模式，避免 SMTP 相关环境变量干扰
    for k in ("SMTP_SEND_ENABLED", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "INVITE_CODE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-for-ci-only")

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()
