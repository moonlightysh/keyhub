"""
GPG 公钥加密工具模块：
  - 使用 PGPy（纯 Python 实现，不需要系统安装 gpg 命令，便于在阿里云 ECS 上部署）
  - 提供两个核心函数：
      1. validate_public_key(pubkey_str) -> (bool, str, fingerprint)  校验公钥是否合法
      2. encrypt_with_public_key(plaintext, pubkey_str) -> str          用公钥加密文本，返回 ASCII Armor 格式密文
"""
from typing import Tuple, Optional

import pgpy
from pgpy import PGPKey
from pgpy.constants import SymmetricKeyAlgorithm


def validate_public_key(pubkey_str: str) -> Tuple[bool, str, Optional[str]]:
    """
    校验一段文本是否为合法的 GPG 公钥（只接受公钥，不接受私钥）。
    返回：(是否合法, 错误信息, 公钥指纹)
    """
    text = (pubkey_str or "").strip()
    if not text:
        return False, "公钥内容为空", None
    try:
        key, _others = PGPKey.from_blob(text)
    except Exception as e:
        return False, f"公钥解析失败：{e}", None

    if not key.is_public:
        return False, "你上传的是私钥！请上传公钥（public key）", None

    if not key.is_primary or key.key_algorithm is None:
        return False, "这不是一个合法的主密钥", None

    fp = key.fingerprint
    return True, "", fp


def encrypt_with_public_key(plaintext: str, pubkey_str: str) -> str:
    """
    使用收件人 GPG 公钥加密明文，返回 ASCII Armor 格式的密文字符串。
    抛出异常说明加密失败（调用方要捕获）。
    """
    text = (plaintext or "")
    pub_str = (pubkey_str or "").strip()
    if not pub_str:
        raise ValueError("收件人公钥为空，无法加密")
    if not text:
        raise ValueError("明文内容为空")

    # 加载公钥
    try:
        pub_key, _ = PGPKey.from_blob(pub_str)
    except Exception as e:
        raise ValueError(f"加载收件人公钥失败：{e}")

    if not pub_key.is_public:
        raise ValueError("收件人密钥不是公钥")

    # 选择一个用于加密的子密钥（优先使用加密子密钥，没有就用主密钥）
    enc_key = None
    # 遍历子键
    try:
        for sk in pub_key.subkeys.values():
            if sk.can_encrypt:
                enc_key = sk
                break
    except Exception:
        enc_key = None
    if enc_key is None:
        # 如果主密钥自身支持加密（一些旧 RSA 密钥），则用主密钥
        if getattr(pub_key, "can_encrypt", False):
            enc_key = pub_key
        else:
            # 兜底，仍然用 pub_key，PGPy 在 encrypt 时会尽力选择
            enc_key = pub_key

    # 构造明文消息
    msg = pgpy.PGPMessage.new(text, compress=True)

    # 加密：优先用 AES-256
    try:
        encrypted = enc_key.encrypt(msg, cipher=SymmetricKeyAlgorithm.AES256)
    except TypeError:
        # 兼容不同 PGPy 版本参数名
        encrypted = enc_key.encrypt(msg)
    except Exception as e:
        # 若 enc_key 不可加密，则退回用 pub_key
        if enc_key is not pub_key:
            try:
                encrypted = pub_key.encrypt(msg, cipher=SymmetricKeyAlgorithm.AES256)
            except TypeError:
                encrypted = pub_key.encrypt(msg)
        else:
            raise e

    # 返回 ASCII Armor 格式的字符串
    armored = str(encrypted)
    if not armored:
        raise RuntimeError("加密后得到空结果")
    return armored
