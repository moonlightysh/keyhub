"""
storage 模块单元测试：
  - add_user / get_user_by_email / list_users / delete_user
  - 同邮箱覆盖更新（保留 created_at）
  - 边界：空邮箱 / 空公钥

注意：storage 不依赖 pgpy，公钥只当作字符串存储，所以这里用假公钥字符串，
      确保在 pgpy 不可用的 CI 环境下也能完整运行。
"""
import pytest

# 假公钥字符串，仅用于测试 storage 的存取逻辑（storage 不校验公钥合法性）
DUMMY_PUBKEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nFAKE\n-----END PGP PUBLIC KEY BLOCK-----"


class TestStorage:
    def test_add_and_get_user(self, isolated_storage):
        s = isolated_storage
        u = s.add_user(email="alice@test.local", nickname="Alice", public_key=DUMMY_PUBKEY)
        assert u["email"] == "alice@test.local"
        assert u["nickname"] == "Alice"

        got = s.get_user_by_email("alice@test.local")
        assert got is not None
        assert got["public_key"].strip() == DUMMY_PUBKEY.strip()

    def test_list_users_sorted_by_created_desc(self, isolated_storage, monkeypatch):
        import storage as s_mod
        s = isolated_storage
        ts = [1000]
        def fake_time():
            ts[0] += 1
            return ts[0]
        monkeypatch.setattr(s_mod.time, "time", fake_time)

        s.add_user(email="a@test.local", nickname="A", public_key=DUMMY_PUBKEY)
        s.add_user(email="b@test.local", nickname="B", public_key=DUMMY_PUBKEY)
        users = s.list_users()
        assert users[0]["email"] == "b@test.local"

    def test_update_existing_user_preserves_created_at(self, isolated_storage, monkeypatch):
        import storage as s_mod
        s = isolated_storage
        ts = [1000]
        def fake_time():
            ts[0] += 1
            return ts[0]
        monkeypatch.setattr(s_mod.time, "time", fake_time)

        u1 = s.add_user(email="alice@test.local", nickname="Old", public_key=DUMMY_PUBKEY)
        created = u1["created_at"]
        u2 = s.add_user(email="alice@test.local", nickname="New", public_key=DUMMY_PUBKEY)
        assert u2["nickname"] == "New"
        assert u2["created_at"] == created  # 创建时间保留

    def test_delete_user(self, isolated_storage):
        s = isolated_storage
        s.add_user(email="alice@test.local", nickname="Alice", public_key=DUMMY_PUBKEY)
        assert s.delete_user("alice@test.local") is True
        assert s.get_user_by_email("alice@test.local") is None

    def test_delete_nonexistent_returns_false(self, isolated_storage):
        s = isolated_storage
        assert s.delete_user("nobody@test.local") is False

    def test_empty_email_raises(self, isolated_storage):
        s = isolated_storage
        with pytest.raises(ValueError):
            s.add_user(email="", nickname="X", public_key=DUMMY_PUBKEY)

    def test_empty_pubkey_raises(self, isolated_storage):
        s = isolated_storage
        with pytest.raises(ValueError):
            s.add_user(email="x@test.local", nickname="X", public_key="")

    def test_email_case_insensitive_lookup(self, isolated_storage):
        s = isolated_storage
        s.add_user(email="Alice@Test.Local", nickname="A", public_key=DUMMY_PUBKEY)
        assert s.get_user_by_email("alice@test.local") is not None
