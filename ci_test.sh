#!/bin/bash
# KeyHub CI 测试脚本（云效流水线「测试」阶段执行）
# 用法：bash ci_test.sh
set -e

echo ">>> [1/3] 安装依赖（含 pytest）"
pip install -q -r requirements-dev.txt

echo ">>> [2/3] 语法检查（编译所有 .py）"
python -m py_compile app.py storage.py crypto_utils.py mailer.py backup_oss.py

echo ">>> [3/3] 运行 pytest 测试套件"
python -m pytest tests/ -v --tb=short -W ignore::DeprecationWarning -W ignore::UserWarning

echo ""
echo "✅ CI 测试全部通过"
