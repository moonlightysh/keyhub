#!/bin/bash
# KeyHub CI 测试脚本（云效流水线「测试」阶段执行）
# 用法：bash ci_test.sh
set -e

echo ">>> [0/4] 安装系统依赖（libbz2，pgpy 压缩需要）"
# alinux3 / CentOS / RHEL 用 dnf/yum
if command -v dnf >/dev/null 2>&1; then
  dnf install -y -q bzip2-libs bzip2 >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q bzip2-libs bzip2 >/dev/null 2>&1 || true
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq libbz2-1.0 bzip2 >/dev/null 2>&1 || true
fi

# 兜底：若 bzip2-libs 只提供了 libbz2.so.1 而没有 libbz2.so.1.0，
# 则建一个软链接，因为编译好的 _bz2 扩展链接的是 libbz2.so.1.0
if [ ! -f /usr/lib64/libbz2.so.1.0 ] && [ -f /usr/lib64/libbz2.so.1 ]; then
  ln -sf /usr/lib64/libbz2.so.1 /usr/lib64/libbz2.so.1.0 2>/dev/null || true
fi
if [ ! -f /usr/lib/libbz2.so.1.0 ] && [ -f /usr/lib/libbz2.so.1 ]; then
  ln -sf /usr/lib/libbz2.so.1 /usr/lib/libbz2.so.1.0 2>/dev/null || true
fi

echo ">>> [1/4] 安装依赖（含 pytest）"
pip install -q -r requirements-dev.txt

echo ">>> [2/4] 语法检查（编译所有 .py）"
python -m py_compile app.py storage.py crypto_utils.py mailer.py backup_oss.py

echo ">>> [3/4] 运行 pytest 测试套件（生成 HTML 报告到 report/index.html）"
mkdir -p report
python -m pytest tests/ -v --tb=short \
  --html=report/index.html --self-contained-html \
  -W ignore::DeprecationWarning -W ignore::UserWarning

echo ""
echo "✅ CI 测试全部通过"
