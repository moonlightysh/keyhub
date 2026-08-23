"""
JSON 文件存储模块：
  - 用户数据（邮箱 + 昵称 + GPG 公钥文本）保存在 data/users.json 中
  - 使用 fcntl.flock 文件锁（跨进程安全，适配 gunicorn 多 worker）
  - 写入采用「临时文件 + os.replace 原子替换」，防止写一半崩溃导致文件损坏
  - 采用标准库，不依赖数据库
"""
import json
import os
import fcntl
import time
from typing import List, Optional, Dict, Any

# 数据文件路径（与本模块同级的 data 目录下）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOCK_FILE = os.path.join(DATA_DIR, ".users.json.lock")  # 独立锁文件


def _ensure_data_dir() -> None:
    """确保 data 目录和 users.json 文件存在"""
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


class _FileLock:
    """
    基于 fcntl.flock 的跨进程文件锁。
    gunicorn 多 worker 场景下，threading.Lock 无法跨进程，
    必须用操作系统级文件锁保证「读-改-写」的原子性。
    """
    def __enter__(self):
        _ensure_data_dir()
        self._fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)
        # 阻塞式排他锁：拿到锁才返回
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)


def _read_all() -> List[Dict[str, Any]]:
    """读取所有用户记录（加共享锁，防止读到写一半的数据）"""
    _ensure_data_dir()
    with _FileLock():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return []


def _write_all(users: List[Dict[str, Any]]) -> None:
    """覆盖写入所有用户记录（排他锁 + 临时文件原子替换）"""
    _ensure_data_dir()
    with _FileLock():
        tmp_file = USERS_FILE + f".tmp.{os.getpid()}.{int(time.time() * 1000)}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            # 原子替换（同分区下 os.replace 是原子操作）
            os.replace(tmp_file, USERS_FILE)
        finally:
            if os.path.isfile(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass


def list_users() -> List[Dict[str, Any]]:
    """返回所有用户列表（按注册时间倒序）"""
    users = _read_all()
    # 按 created_at 倒序（新注册的在前）
    users.sort(key=lambda u: u.get("created_at", 0), reverse=True)
    return users


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """根据邮箱查找用户"""
    email_lc = (email or "").strip().lower()
    for u in _read_all():
        if (u.get("email") or "").strip().lower() == email_lc:
            return u
    return None


def add_user(email: str, nickname: str, public_key: str) -> Dict[str, Any]:
    """
    新增一个用户。若邮箱已存在，则覆盖（更新昵称和公钥）。
    返回新的用户对象。
    """
    email = (email or "").strip()
    nickname = (nickname or "").strip() or email
    public_key = (public_key or "").strip()
    if not email:
        raise ValueError("邮箱不能为空")
    if not public_key:
        raise ValueError("GPG 公钥不能为空")

    users = _read_all()
    now = int(time.time())

    # 找是否已有同邮箱用户
    existing_idx = None
    for i, u in enumerate(users):
        if (u.get("email") or "").strip().lower() == email.lower():
            existing_idx = i
            break

    user = {
        "email": email,
        "nickname": nickname,
        "public_key": public_key,
        "created_at": now,
        "updated_at": now,
    }
    if existing_idx is not None:
        # 保留原创建时间
        user["created_at"] = users[existing_idx].get("created_at", now)
        users[existing_idx] = user
    else:
        users.append(user)

    _write_all(users)
    return user


def delete_user(email: str) -> bool:
    """根据邮箱删除用户。返回 True 表示真的删除到了。"""
    email_lc = (email or "").strip().lower()
    users = _read_all()
    new_users = [u for u in users if (u.get("email") or "").strip().lower() != email_lc]
    if len(new_users) == len(users):
        return False
    _write_all(new_users)
    return True
