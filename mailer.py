"""
邮件发送模块：
  - 通过 SMTP（支持 SSL 和 STARTTLS）发送已用 GPG 公钥加密的邮件
  - 邮件主体为纯文本（ASCII Armor 密文），同时带 .asc 附件，方便收件人用
    Thunderbird + Enigmail / GPGTools / Gpg4win 等直接解密阅读
"""
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import Optional

# 优先读取环境变量（dotenv 已经在 app.py 中加载过）
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "True").lower() in ("1", "true", "yes", "on")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "KeyHub")


def is_smtp_configured() -> bool:
    """判断 SMTP 配置是否完整（用于前端展示提示）"""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_encrypted_email(
    to_email: str,
    to_nickname: str,
    subject: str,
    armored_ciphertext: str,
    from_name: Optional[str] = None,
) -> None:
    """
    发送一封加密邮件。
    :param to_email: 收件人邮箱
    :param to_nickname: 收件人昵称（用于展示）
    :param subject: 邮件主题（明文传输，不要放敏感内容）
    :param armored_ciphertext: 用收件人 GPG 公钥加密后的 ASCII Armor 格式密文
    :param from_name: 发件人显示名称，默认取配置里的
    :raises RuntimeError: SMTP 未配置时抛出
    :raises Exception: SMTP 连接/登录/发送失败会抛原始异常，调用方自行捕获
    """
    if not is_smtp_configured():
        raise RuntimeError(
            "SMTP 尚未配置：请在服务器的 .env 文件中填入 SMTP_HOST / SMTP_PORT / "
            "SMTP_USER / SMTP_PASSWORD 等环境变量后重启服务"
        )

    if not to_email:
        raise ValueError("收件人邮箱为空")
    if not armored_ciphertext:
        raise ValueError("加密内容为空")

    display_from_name = from_name or SMTP_FROM_NAME or SMTP_USER

    # 构建一个带附件的多部分邮件
    msg = MIMEMultipart()
    msg["From"] = formataddr((display_from_name, SMTP_USER))
    msg["To"] = formataddr((to_nickname or to_email, to_email))
    msg["Subject"] = subject or "来自 KeyHub 的加密邮件"
    msg["Date"] = formatdate(localtime=True)
    msg["X-Mailer"] = "KeyHub-GPG-Gateway"

    # 正文：提示 + 密文
    body_intro = (
        "这是一封使用您的 GPG 公钥加密的邮件。\r\n"
        "请将下方的密文（或附件 message.asc）用您的 GPG 私钥解密查看原文。\r\n"
        "如果邮件客户端不自动识别，请将密文块复制后用 gpg --decrypt 解密。\r\n"
        "-----BEGIN EXPLANATION-----\r\n"
        "加密算法：AES-256 + 收件人 GPG 公钥（RSA/ECC）\r\n"
        "中间人即使截获此邮件，没有您的私钥也无法解密内容。\r\n"
        "-----END EXPLANATION-----\r\n"
        "\r\n"
    )
    msg.attach(MIMEText(body_intro + armored_ciphertext, "plain", "utf-8"))

    # 附件：.asc 文件，方便用户直接拖进 GPG 工具
    part = MIMEBase("application", "pgp-encrypted")
    part.set_payload(armored_ciphertext.encode("utf-8"))
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        'attachment; filename="message.asc"',
    )
    msg.attach(part)

    # 真正的 SMTP 发送
    if SMTP_USE_SSL:
        # SSL 模式，默认 465 端口
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
    else:
        # 普通模式（一般配 587 端口 + STARTTLS）
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            # 尝试启用 STARTTLS（如果服务器支持）
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPException:
                pass
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
