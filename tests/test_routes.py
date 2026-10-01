"""
Flask 路由集成测试：
  - /healthz 健康检查
  - /register GET/POST 注册
  - / 首页用户列表
  - /send 加密消息（离线模式）
  - /guide 用户指南
  - /logout 退出

注意：所有路由测试依赖 app.py → crypto_utils → pgpy，pgpy 不可用时整体 skip。
"""
from conftest import pgpy_required


@pgpy_required
class TestHealthz:
    def test_healthz_ok(self, app_client):
        r = app_client.get("/healthz")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert "users" in body
        assert isinstance(body["users"], int)


@pgpy_required
class TestRegister:
    def test_register_get(self, app_client):
        r = app_client.get("/register")
        assert r.status_code == 200
        assert "GPG 公钥" in r.get_data(as_text=True)

    def test_register_post_success(self, app_client, tmp_keypair):
        r = app_client.post("/register", data={
            "email": tmp_keypair["email"],
            "nickname": "Alice",
            "public_key": tmp_keypair["pub"],
        }, follow_redirects=True)
        assert r.status_code == 200


@pgpy_required
class TestIndex:
    def test_index_lists_users(self, app_client, tmp_keypair):
        # 先注册一个用户
        app_client.post("/register", data={
            "email": tmp_keypair["email"],
            "nickname": "Alice",
            "public_key": tmp_keypair["pub"],
        })
        r = app_client.get("/")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert tmp_keypair["email"] in html


@pgpy_required
class TestSend:
    def test_send_offline_returns_ciphertext(self, app_client, tmp_keypair):
        app_client.post("/register", data={
            "email": tmp_keypair["email"],
            "nickname": "Alice",
            "public_key": tmp_keypair["pub"],
        })
        r = app_client.post("/send", data={
            "recipient": tmp_keypair["email"],
            "recipient_nickname": "Alice",
            "message": "机密内容 123",
        })
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "BEGIN PGP MESSAGE" in html
        assert "一键复制密文" in html


@pgpy_required
class TestGuide:
    def test_guide_page_loads(self, app_client):
        r = app_client.get("/guide")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        # 用户指南页面应包含文档内容（USER_GUIDE.md 渲染后）
        assert "KeyHub" in html


@pgpy_required
class TestLogout:
    def test_logout_redirects_to_gate(self, app_client):
        r = app_client.get("/logout", follow_redirects=False)
        # 未设邀请码时 gate 会重定向到 index，但 logout 本身应 redirect
        assert r.status_code in (301, 302)
