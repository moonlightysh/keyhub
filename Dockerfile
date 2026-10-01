# ======= KeyHub Dockerfile（多阶段构建，瘦身版） =======
# 用法：
#   docker build -t keyhub .
#   docker run --rm -p 127.0.0.1:5000:5000 -v "$(pwd)/data:/app/data" keyhub

# ====== Stage 1: builder（安装依赖，最终镜像不会包含此层） ======
FROM python:3.9-slim AS builder

# pip 阿里云镜像加速
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
 && pip config set global.trusted-host mirrors.aliyun.com

WORKDIR /build

# 只复制 requirements.txt，利用 Docker 缓存
COPY requirements.txt ./

# 安装依赖到 /install 前缀，--no-compile 跳过 .pyc 编译
RUN pip install --no-cache-dir --no-compile --prefix=/install \
      -r requirements.txt gunicorn

# ====== Stage 2: runtime（最终镜像，最小化） ======
FROM python:3.9-slim

# 从 builder 只拷贝 site-packages 和 gunicorn 入口（不含 pip/setuptools/wheel）
COPY --from=builder /install /usr/local

WORKDIR /app

# 复制应用代码
COPY app.py storage.py crypto_utils.py mailer.py backup_oss.py USER_GUIDE.md ./
COPY templates ./templates
COPY static ./static

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_SECRET_KEY=docker-default-secret-change-in-production \
    FLASK_DEBUG=False

# 数据目录 + 非 root 用户
RUN mkdir -p /app/data && chown -R 1000:1000 /app
VOLUME ["/app/data"]
USER 1000:1000

EXPOSE 5000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "60", "--access-logfile", "-", "app:app"]
