"""
crypto_utils 模块单元测试：
  - validate_public_key: 空输入 / 合法公钥 / 私钥拒绝 / 非法文本
  - encrypt_with_public_key: 空明文 / 空公钥 / 加密结果为 ASCII Armor / 可被对应私钥解密
"""
import pgpy
import pytest

from crypto_utils import validate_public_key, encrypt_with_public_key


# ---------- validate_public_key ----------

class TestValidatePublicKey:
    def test_empty_input(self):
        ok, err, fp = validate_public_key("")
        assert ok is False
        assert "空" in err
        assert fp is None

    def test_none_input(self):
        ok, err, fp = validate_public_key(None)
        assert ok is False
        assert fp is None

    def test_valid_public_key(self, tmp_keypair):
        ok, err, fp = validate_public_key(tmp_keypair["pub"])
        assert ok is True, f"合法公钥校验失败: {err}"
        assert err == ""
        assert fp and len(fp) > 0

    def test_private_key_rejected(self, tmp_keypair):
        ok, err, fp = validate_public_key(tmp_keypair["priv"])
        assert ok is False
        assert "私钥" in err
        assert fp is None

    def test_malformed_text(self):
        ok, err, fp = validate_public_key("not a pgp key at all")
        assert ok is False
        assert fp is None


# ---------- encrypt_with_public_key ----------

class TestEncryptWithPublicKey:
    def test_empty_plaintext_raises(self, tmp_keypair):
        with pytest.raises(ValueError):
            encrypt_with_public_key("", tmp_keypair["pub"])

    def test_empty_pubkey_raises(self):
        with pytest.raises(ValueError):
            encrypt_with_public_key("hello", "")

    def test_returns_ascii_armor(self, tmp_keypair):
        ciphertext = encrypt_with_public_key("hello world", tmp_keypair["pub"])
        assert "BEGIN PGP MESSAGE" in ciphertext
        assert "END PGP MESSAGE" in ciphertext

    def test_decrypt_matches_plaintext(self, tmp_keypair):
        plaintext = "密码是abc\n中文换行 emoji🚀 UTF-8 测试"
        ciphertext = encrypt_with_public_key(plaintext, tmp_keypair["pub"])

        priv_key, _ = pgpy.PGPKey.from_blob(tmp_keypair["priv"])
        enc_msg = pgpy.PGPMessage.from_blob(ciphertext)
        decrypted = priv_key.decrypt(enc_msg).message
        if isinstance(decrypted, bytes):
            decrypted = decrypted.decode("utf-8")
        assert decrypted == plaintext
