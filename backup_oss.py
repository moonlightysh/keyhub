#!/usr/bin/env python3
"""
KeyHub - users.json 定时备份到阿里云 OSS

流程：
  1. 读取 data/users.json，计算 SHA-256
  2. 从 OSS 读取上次备份对象的 x-oss-hash（SHA-256）元数据
  3. 如果 hash 一致 → 跳过本次备份
  4. 如果 hash 不一致或 OSS 上不存在 → 上传新版本，带 hash 元数据
  5. 旧版本保留（通过 OSS 生命周期规则自动清理，或手动管理）

用法：
  # 手动执行一次
  python backup_oss.py

  # 定时执行（crontab 每天凌晨 3 点）
  # 0 3 * * * cd /opt/keyhub && .venv/bin/python backup_oss.py >> logs/backup.log 2>&1

环境变量（.env 或系统环境）：
  OSS_ACCESS_KEY_ID     - 阿里云 AccessKey ID（建议 RAM 子账号，仅授权 OSS 写权限）
  OSS_ACCESS_KEY_SECRET - 阿里云 AccessKey Secret
  OSS_ENDPOINT          - OSS Endpoint，如 https://oss-cn-hangzhou.aliyuncs.com
  OSS_BUCKET            - Bucket 名称
  OSS_PREFIX            - 存储路径前缀，默认 keyhub-backup/（可选）

依赖：oss2（pip install oss2）
"""
import hashlib
import os
import sys
from datetime import datetime

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

from storage import USERS_FILE

# ---------- 配置 ----------
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_BUCKET = os.getenv("OSS_BUCKET", "")
OSS_PREFIX = os.getenv("OSS_PREFIX", "keyhub-backup/").rstrip("/") + "/"

# 本地记录上次备份的 hash，避免每次都去查 OSS（加速判断）
LAST_HASH_FILE = os.path.join(os.path.dirname(USERS_FILE), ".last_backup_hash")


def compute_sha256(filepath: str) -> str:
    """计算文件的 SHA-256"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def get_local_last_hash() -> str:
    """读取本地记录的上次备份 hash"""
    try:
        with open(LAST_HASH_FILE, "r") as f:
            return f.read().strip()
    except (FileNotFoundError, IOError):
        return ""


def save_local_last_hash(h: str) -> None:
    """保存本次备份 hash 到本地"""
    try:
        with open(LAST_HASH_FILE, "w") as f:
            f.write(h)
    except IOError:
        pass


def main() -> int:
    # 1. 检查配置
    missing = []
    if not OSS_ACCESS_KEY_ID:
        missing.append("OSS_ACCESS_KEY_ID")
    if not OSS_ACCESS_KEY_SECRET:
        missing.append("OSS_ACCESS_KEY_SECRET")
    if not OSS_ENDPOINT:
        missing.append("OSS_ENDPOINT")
    if not OSS_BUCKET:
        missing.append("OSS_BUCKET")
    if missing:
        print(f"[ERROR] 缺少环境变量: {', '.join(missing)}")
        print("请在 .env 中配置阿里云 OSS 相关参数。")
        return 1

    # 2. 检查 users.json 存在
    if not os.path.isfile(USERS_FILE):
        print(f"[ERROR] 文件不存在: {USERS_FILE}")
        return 1

    # 3. 计算当前文件 SHA-256
    current_hash = compute_sha256(USERS_FILE)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 4. 比对本地记录的上次 hash（快速跳过，避免查 OSS）
    local_last = get_local_last_hash()
    if local_last == current_hash:
        print(f"[{now_str}] 跳过：文件未变化（SHA-256: {current_hash[:16]}…）")
        return 0

    # 5. 导入 oss2（延迟导入，未配置 OSS 时不报错）
    try:
        import oss2
    except ImportError:
        print("[ERROR] 未安装 oss2，请执行: pip install oss2")
        return 1

    # 6. 连接 OSS
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)

    # 7. 查询 OSS 上最新备份对象的 hash 元数据（双保险）
    #    OSS 对象命名：keyhub-backup/users.json（始终覆盖同一对象，靠 OSS 版本控制保留历史）
    oss_key = OSS_PREFIX + "users.json"

    try:
        meta = bucket.head_object(oss_key)
        oss_last_hash = meta.headers.get("x-oss-meta-sha256", "")
    except oss2.NoSuchKey:
        oss_last_hash = ""
    except Exception as e:
        print(f"[WARN] 查询 OSS 元数据失败: {e}，继续尝试上传…")
        oss_last_hash = ""

    # 8. 如果 OSS 上的 hash 和当前一致 → 只更新本地记录，跳过上传
    if oss_last_hash == current_hash:
        print(f"[{now_str}] 跳过：OSS 上已是最新（SHA-256: {current_hash[:16]}…）")
        save_local_last_hash(current_hash)
        return 0

    # 9. 上传到 OSS，附带 SHA-256 元数据
    try:
        bucket.put_object_from_file(
            oss_key,
            USERS_FILE,
            headers={"x-oss-meta-sha256": current_hash},
        )
        save_local_last_hash(current_hash)
        print(
            f"[{now_str}] ✅ 备份成功！\n"
            f"   对象: oss://{OSS_BUCKET}/{oss_key}\n"
            f"   SHA-256: {current_hash}\n"
            f"   大小: {os.path.getsize(USERS_FILE)} bytes"
        )
        return 0
    except Exception as e:
        print(f"[{now_str}] ❌ 备份失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
