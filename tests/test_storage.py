"""
storage 模块单元测试：
  - add_user / get_user_by_email / list_users / delete_user
  - 同邮箱覆盖更新（保留 created_at）
  - 边界：空邮箱 / 空公钥
"""
import pytest


class TestStorage:
    def test_add_and_get_user(self, isolated_storage, tmp_keypair):
        s = isolated_storage
        u = s.add_user(email=tmp_keypair["email"], nickname="Alice", public_key=tmp_keypair["pub"])
        assert u["email"] == tmp_keypair["email"]
        assert u["nickname"] == "Alice"

        got = s.get_user_by_email(tmp_keypair["email"])
        assert got is not None
        assert got["public_key"].strip() == tmp_keypair["pub"].strip()

    def test_list_users_sorted_by_created_desc(self, isolated_storage, tmp_keypair, monkeypatch):
        import storage as s_mod
        s = isolated_storage
        # 用 mock 时间戳确保两个用户的 created_at 不同
        ts = [1000]
        def fake_time():
            ts[0] += 1
            return ts[0]
        monkeypatch.setattr(s_mod.time, "time", fake_time)

        s.add_user(email="a@test.local", nickname="A", public_key=tmp_keypair["pub"])
        s.add_user(email="b@test.local", nickname="B", public_key=tmp_keypair["pub"])
        users = s.list_users()
        assert users[0]["email"] == "b@test.local"

    def test_update_existing_user_preserves_created_at(self, isolated_storage, tmp_keypair, monkeypatch):
        import storage as s_mod
        s = isolated_storage
        ts = [1000]
        def fake_time():
            ts[0] += 1
            return ts[0]
        monkeypatch.setattr(s_mod.time, "time", fake_time)

        u1 = s.add_user(email=tmp_keypair["email"], nickname="Old", public_key=tmp_keypair["pub"])
        created = u1["created_at"]
        u2 = s.add_user(email=tmp_keypair["email"], nickname="New", public_key=tmp_keypair["pub"])
        assert u2["nickname"] == "New"
        assert u2["created_at"] == created  # 创建时间保留

    def test_delete_user(self, isolated_storage, tmp_keypair):
        s = isolated_storage
        s.add_user(email=tmp_keypair["email"], nickname="Alice", public_key=tmp_keypair["pub"])
        assert s.delete_user(tmp_keypair["email"]) is True
        assert s.get_user_by_email(tmp_keypair["email"]) is None

    def test_delete_nonexistent_returns_false(self, isolated_storage):
        s = isolated_storage
        assert s.delete_user("nobody@test.local") is False

    def test_empty_email_raises(self, isolated_storage, tmp_keypair):
        s = isolated_storage
        with pytest.raises(ValueError):
            s.add_user(email="", nickname="X", public_key=tmp_keypair["pub"])

    def test_empty_pubkey_raises(self, isolated_storage):
        s = isolated_storage
        with pytest.raises(ValueError):
            s.add_user(email="x@test.local", nickname="X", public_key="")

    def test_email_case_insensitive_lookup(self, isolated_storage, tmp_keypair):
        s = isolated_storage
        s.add_user(email="Alice@Test.Local", nickname="A", public_key=tmp_keypair["pub"])
        assert s.get_user_by_email("alice@test.local") is not None
