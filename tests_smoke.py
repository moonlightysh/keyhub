"""
冒烟测试脚本（不依赖真实 GPG 环境 / SMTP）：
  1) 用 PGPy 生成一对临时 RSA 密钥（不会留到你系统里，用完就删）
  2) 用 storage.add_user 把公钥写进 data/users_test.json（临时）
  3) 用 crypto_utils.validate_public_key 校验公钥合法性
  4) 用 crypto_utils.encrypt_with_public_key 加密明文 "密码是abc"
  5) 用刚才生成的临时私钥解密密文，验证解密结果 == 明文
  6) 启动 Flask app，访问 /healthz 验证路由能正常工作
全部通过就代表你部署到 ECS 上后核心功能也会工作。
"""
import json
import os
import sys
import tempfile

# 先让脚本能 import 同级目录的模块
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pgpy
from pgpy.constants import PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm

# —— 覆盖 storage 的文件路径为临时文件，不污染真实 data/users.json ——
TMP_DIR = tempfile.mkdtemp(prefix="keyhub_test_")
USERS_TMP = os.path.join(TMP_DIR, "users_test.json")
os.makedirs(os.path.dirname(USERS_TMP), exist_ok=True)
with open(USERS_TMP, "w") as f:
    json.dump([], f)

import storage
storage.DATA_DIR = os.path.dirname(USERS_TMP)
storage.USERS_FILE = USERS_TMP

from crypto_utils import validate_public_key, encrypt_with_public_key


def make_tmp_keypair(email="alice@test.local"):
    """生成一个临时的 RSA-3072 密钥对（用完就丢）"""
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 3072)
    uid = pgpy.PGPUID.new("Alice Test", email=email)
    # 注意：不设口令，仅用于测试
    key.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB],
    )
    # 加一个加密子密钥（更贴近真实用户的情况）
    sub = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 3072)
    key.add_subkey(sub, usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage})
    pub_armor = str(key.pubkey)
    priv_armor = str(key)
    return pub_armor, priv_armor, email


def main():
    print("[1/5] 生成临时 GPG 密钥对（RSA-3072）...")
    pub, priv, email = make_tmp_keypair()
    assert "BEGIN PGP PUBLIC KEY BLOCK" in pub
    assert "BEGIN PGP PRIVATE KEY BLOCK" in priv
    print("      OK  公钥长度 =", len(pub), "私钥长度 =", len(priv))

    print("[2/5] storage.add_user / list_users 读写 JSON ...")
    from storage import add_user, list_users, get_user_by_email, delete_user
    u = add_user(email=email, nickname="Alice", public_key=pub)
    assert u["email"] == email
    users = list_users()
    assert any(x["email"].lower() == email.lower() for x in users), "add_user 后没读到"
    u2 = get_user_by_email(email)
    assert u2 is not None, "get_user_by_email 找不到用户"
    # storage 存储时对公钥做了 strip，所以比较时也要双方 strip 后再比
    assert u2["public_key"].strip() == pub.strip(), "get_user_by_email 返回的公钥不一致"
    print("      OK  当前用户总数 =", len(users))

    print("[3/5] crypto_utils.validate_public_key 公钥校验 ...")
    ok, err, fp = validate_public_key(pub)
    assert ok, f"合法公钥居然校验失败: {err}"
    assert fp and len(fp) > 0, "没有返回指纹"
    print("      OK  指纹 =", fp)

    # 尝试把私钥当成公钥传，应当被拒绝
    ok2, err2, _ = validate_public_key(priv)
    assert not ok2 and "私钥" in err2, "把私钥传进去居然通过了！"
    print("      OK  上传私钥时被正确拒绝：", err2)

    print("[4/5] 加密 / 解密 端到端验证（原文 = 密码是abc）...")
    plaintext = "密码是abc\n附带一点中文、换行和 emoji🚀，确保 UTF-8 没问题。"
    armored = encrypt_with_public_key(plaintext, pub)
    assert "BEGIN PGP MESSAGE" in armored, "加密结果不是 ASCII Armor 格式的 PGP Message"
    # 用临时私钥解密
    priv_key, _ = pgpy.PGPKey.from_blob(priv)
    enc_msg = pgpy.PGPMessage.from_blob(armored)
    decrypted_obj = priv_key.decrypt(enc_msg)
    decrypted_text = decrypted_obj.message
    # PGPy 不同版本返回的 message 可能是 bytes 或 str，统一一下
    if isinstance(decrypted_text, bytes):
        try:
            decrypted_text = decrypted_text.decode("utf-8")
        except Exception:
            decrypted_text = str(decrypted_text)
    assert decrypted_text == plaintext, (
        f"解密前后不一致！\n原文长度={len(plaintext)} 解密结果长度={len(decrypted_text)}\n"
        f"解密结果: {decrypted_text[:200]!r}"
    )
    print("      OK  加密后密文长度 =", len(armored), "，解密与原文一致 ✓")

    print("[5/5] 启动 Flask 并访问 /healthz ...")
    # 确保以"默认离线密文模式"启动（SMTP_SEND_ENABLED 环境变量为 false/未设置）
    os.environ.pop("SMTP_SEND_ENABLED", None)
    os.environ.pop("SMTP_HOST", None)
    os.environ.pop("SMTP_USER", None)
    os.environ.pop("SMTP_PASSWORD", None)

    from app import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    # 新模式字段：默认应该是 offline_ciphertext，且 smtp_send_enabled=false
    assert body.get("mode") == "offline_ciphertext", f"期望默认离线模式，实际: {body}"
    assert body.get("smtp_send_enabled") is False, "smtp_send_enabled 默认为 false 才对"
    print("      OK  /healthz 返回：", body)

    # 额外测一下注册页 GET
    r2 = client.get("/register")
    assert r2.status_code == 200 and "GPG 公钥" in r2.get_data(as_text=True)
    # 提交注册
    r3 = client.post("/register", data={
        "email": email,
        "nickname": "Alice2",
        "public_key": pub,
    }, follow_redirects=True)
    assert r3.status_code == 200
    # 首页 GET
    r4 = client.get("/")
    r4_html = r4.get_data(as_text=True)
    assert r4.status_code == 200 and email in r4_html
    # 默认模式的提示文案
    assert "离线密文模式" in r4_html, "首页应该提示处于离线密文模式"
    assert "加密并生成密文" in r4_html, "按钮文字应为 加密并生成密文"
    print("      OK  注册页 GET/POST、首页 GET 正常，离线模式文案正确")

    # —— 核心：测试 /send 默认 (不勾选 via_smtp) 必须直接展示密文预览页 ——
    plain = "密码是abc 来自 tests_smoke 🚀"
    r5 = client.post("/send", data={
        "recipient": email,
        "recipient_nickname": "Alice2",
        "subject": "测试主题",
        "message": plain,
        # 不提交 via_smtp 字段 => 默认离线模式
    })
    r5_html = r5.get_data(as_text=True)
    assert r5.status_code == 200, "默认离线模式下 POST /send 应直接 200 返回密文预览页，不应该重定向"
    assert "BEGIN PGP MESSAGE" in r5_html, "密文预览页必须包含 ASCII Armor 格式密文"
    assert "一键复制密文" in r5_html, "密文预览页应该有复制按钮"
    print("      OK  POST /send（离线模式）直接返回密文预览页，未调用 SMTP")

    # 再验证：就算用户勾了 via_smtp=1，只要 SMTP_SEND_ENABLED=false，仍然不能发，会展示密文
    r6 = client.post("/send", data={
        "recipient": email,
        "recipient_nickname": "Alice2",
        "subject": "测试主题2",
        "message": plain + " v2",
        "via_smtp": "1",
    })
    r6_html = r6.get_data(as_text=True)
    assert r6.status_code == 200
    assert "BEGIN PGP MESSAGE" in r6_html
    assert "SMTP_SEND_ENABLED=false" in r6_html or "管理员未开启自动发送邮件" in r6_html, (
        "用户勾选 via_smtp 但系统开关未开启时，应当提示原因并仍展示密文"
    )
    print("      OK  POST /send（勾选 via_smtp 但 SMTP_SEND_ENABLED=false）仍安全回落为密文预览")

    # 清理临时文件
    try:
        delete_user(email)
        os.remove(USERS_TMP)
        os.rmdir(os.path.dirname(USERS_TMP))
    except Exception:
        pass

    print("\n🎉 全部冒烟测试通过！核心功能（JSON 存储 / GPG 加密解密 / Flask 路由 / 默认离线密文模式）均正常。")
    print("   当前系统默认工作于【离线密文模式】，不依赖任何 SMTP 服务器：")
    print("     - 用户填消息 → 服务器用收件人公钥加密 → 页面展示密文 → 你自己复制发给对方")
    print("   如后续需要自动通过 SMTP 发邮件，只需两步：")
    print("     1) .env 中 SMTP_SEND_ENABLED=true 并填好 SMTP_HOST/USER/PASSWORD")
    print("     2) 前端发送时勾选『尝试通过 SMTP 自动发送加密邮件』")
    print("   部署到阿里云 ECS 请参考 DEPLOY_ECS.md")


if __name__ == "__main__":
    main()
