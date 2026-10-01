"""
安全相关测试：
  - 邀请码门禁：未通过邀请码时访问受保护路由应重定向到 /gate
  - 邀请码正确后可访问
  - 邀请码错误被拒绝
  - 注册时上传私钥被拒绝
"""
import pytest


class TestInviteGate:
    """邀请码门禁逻辑测试。"""

    @pytest.fixture()
    def gated_client(self, monkeypatch, tmp_path):
        """带邀请码的 Flask test client。"""
        import storage
        users_file = tmp_path / "users.json"
        users_file.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(storage, "USERS_FILE", str(users_file))
        monkeypatch.setattr(storage, "LOCK_FILE", str(tmp_path / ".users.json.lock"))
        for k in ("SMTP_SEND_ENABLED", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
        monkeypatch.setenv("INVITE_CODE", "SECRET-CODE-123")

        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    def test_unauthenticated_redirects_to_gate(self, gated_client):
        """未通过邀请码访问首页应重定向到 /gate。"""
        r = gated_client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "/gate" in r.headers["Location"]

    def test_unauthenticated_register_redirects(self, gated_client):
        r = gated_client.get("/register", follow_redirects=False)
        assert r.status_code == 302
        assert "/gate" in r.headers["Location"]

    def test_wrong_invite_code_rejected(self, gated_client):
        r = gated_client.post("/gate", data={"invite_code": "wrong-code"})
        assert r.status_code == 200
        assert "邀请码不正确" in r.get_data(as_text=True)

    def test_correct_invite_code_grants_access(self, gated_client):
        r = gated_client.post("/gate", data={"invite_code": "SECRET-CODE-123"},
                              follow_redirects=True)
        assert r.status_code == 200
        # 验证通过后能访问首页
        r2 = gated_client.get("/")
        assert r2.status_code == 200


class TestPrivateKeyRejection:
    """注册时上传私钥必须被拒绝。"""

    def test_register_with_private_key_rejected(self, app_client, tmp_keypair):
        r = app_client.post("/register", data={
            "email": tmp_keypair["email"],
            "nickname": "Alice",
            "public_key": tmp_keypair["priv"],  # 故意传私钥
        }, follow_redirects=True)
        html = r.get_data(as_text=True)
        assert "私钥" in html
