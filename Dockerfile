# ======= KeyHub Dockerfile（简化版，无需 apt 编译依赖） =======
# PGPy / cryptography 已经提供 arm64 & amd64 的 manylinux wheel，
# 所以不需要在镜像里装 build-essential / libffi-dev 等编译工具，
# 避免 debian 镜像源 CDN 下载不稳定的问题。
#
# 用法：
#   docker build -t keyhub .
#   docker run --rm -p 127.0.0.1:5000:5000 -v "$(pwd)/data:/app/data" keyhub
FROM python:3.9-slim

# 1) 配置国内 pip 镜像 + 更新 pip（不碰 apt，避免 deb.debian.org 的 CDN 500 问题）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
 && pip config set global.trusted-host mirrors.aliyun.com \
 && pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

# 2) 先只复制 requirements.txt，充分利用 Docker 缓存层（代码变动不用重新装依赖）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn

# 3) 复制应用代码
COPY app.py storage.py crypto_utils.py mailer.py backup_oss.py ./
COPY templates ./templates
COPY static ./static

# 4) 默认运行于「离线密文模式」，不需要配 SMTP
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_SECRET_KEY=docker-default-secret-change-in-production \
    FLASK_DEBUG=False \
    SMTP_SEND_ENABLED=false

# 5) 数据目录：存放 data/users.json；用数字 UID 运行（不依赖 useradd，兼容性更好）
RUN mkdir -p /app/data && chown -R 1000:1000 /app
VOLUME ["/app/data"]
USER 1000:1000

EXPOSE 5000

# 6) 启动：gunicorn（生产用），监听 0.0.0.0:5000，宿主机通过 127.0.0.1:5000 映射访问
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "60", "--access-logfile", "-", "app:app"]
