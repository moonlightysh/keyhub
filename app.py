"""
KeyHub - GPG 加密消息工具（Flask 主应用）

功能：
  1) 用户通过表单注册邮箱 + 上传 GPG 公钥（数据存储于 data/users.json，无数据库）
  2) 用户列表页可见所有已注册用户的邮箱/昵称
  3) 选中收件人后填写消息，服务器用对方公钥加密，展示密文
     明文消息绝不会被传出服务器之外

安全：邀请码模式，所有页面需通过邀请码验证才能访问。

运行：
  pip install -r requirements.txt
  python app.py

ECS 生产部署：推荐使用 gunicorn + nginx + systemd（详见 DEPLOY_ECS.md）。
"""
import os
import traceback
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
import markdown

load_dotenv()

from storage import list_users, add_user, get_user_by_email
from crypto_utils import validate_public_key, encrypt_with_public_key


# 用户指南 Markdown 文件路径（与 app.py 同级）
GUIDE_MD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "USER_GUIDE.md")

_GUIDE_HTML_CACHE = None  # 简单内存缓存，避免每次请求都读文件+转换


def _get_guide_html() -> str:
    """读取 USER_GUIDE.md 并转换为 HTML（带缓存）"""
    global _GUIDE_HTML_CACHE
    if _GUIDE_HTML_CACHE is not None:
        return _GUIDE_HTML_CACHE
    try:
        with open(GUIDE_MD_PATH, "r", encoding="utf-8") as f:
            md_text = f.read()
        _GUIDE_HTML_CACHE = markdown.markdown(
            md_text,
            extensions=["fenced_code", "tables", "toc", "sane_lists"],
        )
    except Exception as e:
        app.logger.error(f"加载用户指南失败: {e}")
        _GUIDE_HTML_CACHE = "<p>用户指南加载失败，请稍后重试。</p>"
    return _GUIDE_HTML_CACHE


def fmt_ts(ts: int) -> str:
    """把时间戳格式化成 YYYY-MM-DD HH:MM"""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def get_invite_code() -> str:
    """从环境变量读取邀请码（默认空，为空时表示不启用邀请码模式）"""
    return os.getenv("INVITE_CODE", "").strip()


def invite_required(f):
    """装饰器：未通过邀请码验证时重定向到 /gate"""
    @wraps(f)
    def decorated(*args, **kwargs):
        code = get_invite_code()
        # 如果没设邀请码，直接放行（本地开发或内网场景）
        if not code:
            return f(*args, **kwargs)
        if not session.get("invited"):
            return redirect(url_for("gate"))
        return f(*args, **kwargs)
    return decorated


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-please-change")
    # session 有效期 7 天
    app.config["PERMANENT_SESSION_LIFETIME"] = 7 * 24 * 3600

    app.jinja_env.filters["fmt_ts"] = fmt_ts

    # 全局模板上下文：注入邀请码是否启用
    @app.context_processor
    def inject_invite_status():
        return {"invite_code_enabled": bool(get_invite_code())}

    # ---------- 路由：邀请码验证页 ----------
    @app.route("/gate", methods=["GET", "POST"])
    def gate():
        code = get_invite_code()
        # 没设邀请码 → 直接回首页
        if not code:
            return redirect(url_for("index"))

        if request.method == "POST":
            user_code = (request.form.get("invite_code") or "").strip()
            if user_code == code:
                session.permanent = True
                session["invited"] = True
                flash("✅ 验证通过，欢迎使用 KeyHub", "success")
                return redirect(url_for("index"))
            else:
                flash("邀请码不正确，请重试", "danger")

        return render_template("gate.html")

    # ---------- 路由：退出 ----------
    @app.route("/logout")
    def logout():
        session.clear()
        flash("已退出，需要重新输入邀请码才能访问", "info")
        return redirect(url_for("gate"))

    # ---------- 路由：首页（用户列表 + 加密消息） ----------
    @app.route("/", methods=["GET"])
    @invite_required
    def index():
        users = list_users()
        return render_template("index.html", users=users)

    # ---------- 路由：注册表单页 ----------
    @app.route("/register", methods=["GET"])
    @invite_required
    def register():
        return render_template("register.html", form_data=None)

    # ---------- 路由：提交注册 ----------
    @app.route("/register", methods=["POST"])
    @invite_required
    def register_submit():
        email = (request.form.get("email") or "").strip()
        nickname = (request.form.get("nickname") or "").strip()
        public_key = (request.form.get("public_key") or "").strip()

        form_data = {"email": email, "nickname": nickname, "public_key": public_key}

        # 1. 基础校验
        if not email:
            flash("邮箱不能为空", "danger")
            return render_template("register.html", form_data=form_data)
        if "@" not in email or "." not in email.split("@")[-1]:
            flash("邮箱格式不正确", "danger")
            return render_template("register.html", form_data=form_data)
        if not public_key:
            flash("请粘贴你的 GPG 公钥", "danger")
            return render_template("register.html", form_data=form_data)

        # 2. 公钥合法性校验
        ok, err, fp = validate_public_key(public_key)
        if not ok:
            flash(f"公钥校验失败：{err}", "danger")
            return render_template("register.html", form_data=form_data)

        # 3. 保存
        try:
            user = add_user(email=email, nickname=nickname, public_key=public_key)
        except Exception as e:
            flash(f"保存失败：{e}", "danger")
            return render_template("register.html", form_data=form_data)

        fp_short = (fp or "").replace(" ", "")[-16:]  # 只显示指纹后 16 位
        flash(
            f"✅ 注册/更新成功！指纹：{fp_short}（如需更新公钥，用同一邮箱再次提交即可）",
            "success",
        )
        # 防止表单重复提交：POST 后重定向到首页
        return redirect(url_for("index"))

    # ---------- 路由：用户指南 ----------
    @app.route("/guide", methods=["GET"])
    @invite_required
    def guide():
        html = _get_guide_html()
        return render_template("guide.html", guide_html=html)

    # ---------- 路由：生成加密密文 ----------
    @app.route("/send", methods=["POST"])
    @invite_required
    def send_message():
        recipient = (request.form.get("recipient") or "").strip()
        recipient_nickname = (request.form.get("recipient_nickname") or "").strip()
        message = (request.form.get("message") or "").strip()

        # 1. 参数校验
        if not recipient:
            flash("请先选择一位收件人", "danger")
            return redirect(url_for("index"))
        if not message:
            flash("消息内容不能为空", "danger")
            return redirect(url_for("index"))

        # 2. 查找收件人（确保他在系统中上传过公钥）
        user = get_user_by_email(recipient)
        if user is None:
            flash(f"系统中不存在邮箱为 {recipient} 的用户（对方需要先注册并上传公钥）", "danger")
            return redirect(url_for("index"))

        display_name = recipient_nickname or user.get("nickname") or recipient

        # 3. 用收件人公钥加密消息
        try:
            armored = encrypt_with_public_key(message, user["public_key"])
        except Exception as e:
            flash(f"加密失败：{e}", "danger")
            app.logger.warning("加密失败 %s: %s", recipient, traceback.format_exc())
            return redirect(url_for("index"))

        # 4. 展示密文
        return render_template(
            "ciphertext_preview.html",
            recipient=display_name,
            email=user["email"],
            armored=armored,
        )

    # ---------- 小工具：健康检查 ----------
    @app.route("/healthz", methods=["GET"])
    def healthz():
        return {"ok": True, "users": len(list_users())}

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "True").lower() in ("1", "true", "yes", "on")
    # 生产环境请不要用 app.run()，改用 gunicorn + nginx
    app.run(host="0.0.0.0", port=port, debug=debug)
