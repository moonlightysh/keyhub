# ======= KeyHub 部署到阿里云 ECS =======

本文件提供两种部署方式：

- **方式一（推荐）**：容器化部署 —— 本地构建 Docker 镜像 → 推送到阿里云 ACR → ECS 拉取并运行
- **方式二**：裸机部署 —— 直接在 ECS 上用 gunicorn + systemd 运行

---

## 方式一：容器化部署（推荐）

核心思路：在你自己的电脑上构建 Docker 镜像，推送到阿里云容器镜像服务（ACR），然后在 ECS 上拉取镜像并启动容器。这样 ECS 不需要安装 Python 环境，也不需要上传源码。

### 1. 准备 ACR 镜像仓库

1. 登录 [阿里云容器镜像服务 ACR 控制台](https://cr.console.aliyun.com/)
2. 创建一个**个人版**实例（免费）或企业版实例
3. 创建一个命名空间（例如 `keyhub`），并在该命名空间下创建一个镜像仓库（例如 `keyhub`，类型选**私有**）
4. 在 ACR 控制台 → 访问凭证 → 设置**固定密码**（即 Docker 登录密码，不是阿里云账号密码）

记下以下信息，后续会用到：
- 仓库地域：如 `cn-hangzhou`（对应 registry 地址 `registry.cn-hangzhou.aliyuncs.com`）
- 命名空间：如 `keyhub`
- 镜像仓库名：如 `keyhub`
- ACR 登录用户名（即你的阿里云账号全名或 RAM 子账号用户名）
- ACR 登录密码（上面设置的固定密码）

### 2. 本地构建镜像

在你本地电脑的 keyhub 项目根目录执行：

```bash
cd /path/to/keyhub

# 构建镜像（注意把下面的 registry 地址、命名空间、仓库名、标签换成你自己的）
docker build -t registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:latest .
```

> 说明：`Dockerfile` 已配置好多阶段构建，最终镜像只包含运行时依赖，体积较小。镜像内已包含 `gunicorn`，默认以非 root 用户（uid 1000）运行。

### 3. 推送镜像到 ACR

```bash
# 登录 ACR（输入上面记下的用户名和密码）
docker login --username=你的阿里云账号全名 registry.cn-hangzhou.aliyuncs.com

# 推送镜像
docker push registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:latest
```

推送成功后，可在 ACR 控制台看到该镜像。

### 4. ECS 上拉取并运行容器

先在 ECS 上安装 Docker（如已安装可跳过）：

```bash
ssh root@你的ECS公网IP

# Ubuntu 安装 Docker
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
systemctl enable --now docker
```

然后拉取镜像并启动容器：

```bash
# 登录 ACR
docker login --username=你的阿里云账号全名 registry.cn-hangzhou.aliyuncs.com

# 拉取镜像
docker pull registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:latest

# 创建数据持久化目录（存放 users.json）
mkdir -p /opt/keyhub/data

# 启动容器
docker run -d \
  --name keyhub \
  --restart unless-stopped \
  -p 127.0.0.1:5000:5000 \
  -v /opt/keyhub/data:/app/data \
  -e FLASK_SECRET_KEY=请换成openssl-rand-hex-32生成的长随机字符串 \
  -e FLASK_DEBUG=False \
  -e INVITE_CODE=你的邀请码 \
  registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:latest
```

参数说明：
- `-p 127.0.0.1:5000:5000`：只绑定本机回环地址，外部无法直接访问 5000 端口，需通过 nginx 反向代理对外提供服务
- `-v /opt/keyhub/data:/app/data`：**关键**——把宿主机的 `/opt/keyhub/data` 挂载到容器内的 `/app/data`，这样 `users.json` 存在宿主机上，容器删除/重建都不会丢失用户数据
- `-e FLASK_SECRET_KEY`：Session 加密密钥，生产环境务必修改
- `-e INVITE_CODE`：邀请码，留空则不启用访问控制
- `--restart unless-stopped`：容器异常退出时自动重启

### 5. 验证

```bash
# 检查容器状态
docker ps | grep keyhub

# 健康检查
curl http://127.0.0.1:5000/healthz
# 应返回 {"ok": true, "users": N}

# 查看日志
docker logs -f keyhub
```

### 6. 配置 nginx 反向代理 + HTTPS（强烈建议）

```bash
apt install -y nginx

cat > /etc/nginx/sites-available/keyhub <<'EOF'
server {
    listen 80;
    server_name 你的域名.com;              # 没域名就填 _

    client_max_body_size 8M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/keyhub /etc/nginx/sites-enabled/keyhub
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# 免费 HTTPS 证书（需要先有域名并解析到 ECS）
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名.com
```

阿里云安全组入方向放行 **80 / 443** 端口，关闭之前测试用的 5000 端口。

### 7. 数据持久化与备份

用户数据存在宿主机的 `/opt/keyhub/data/users.json`，与容器生命周期无关。但仍需定期备份：

```bash
# 备份
tar czf /opt/keyhub-backup-$(date +%Y%m%d).tar.gz -C /opt keyhub/data

# 如需恢复（先停容器）
docker stop keyhub
tar xzf keyhub-backup-日期.tar.gz -C /opt
docker start keyhub
```

> 也可配置 `backup_oss.py` 定时备份到阿里云 OSS（见 README.md 的 OSS 配置说明）。

### 8. 更新部署（发布新版本）

当代码更新后，在本地重新构建并推送镜像，然后在 ECS 上拉取新版本重启容器：

```bash
# ===== 本地电脑 =====
cd /path/to/keyhub
docker build -t registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:v20261001 .
docker push registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:v20261001

# ===== ECS 上 =====
# 先备份数据
tar czf /opt/keyhub-backup-$(date +%Y%m%d).tar.gz -C /opt keyhub/data

# 拉取新镜像
docker pull registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:v20261001

# 删除旧容器，启动新容器（data 目录挂载不变，用户数据不会丢）
docker stop keyhub && docker rm keyhub
docker run -d \
  --name keyhub \
  --restart unless-stopped \
  -p 127.0.0.1:5000:5000 \
  -v /opt/keyhub/data:/app/data \
  -e FLASK_SECRET_KEY=同之前的密钥 \
  -e FLASK_DEBUG=False \
  -e INVITE_CODE=同之前的邀请码 \
  registry.cn-hangzhou.aliyuncs.com/keyhub/keyhub:v20261001
```

> **注意**：只要不删除 `/opt/keyhub/data` 目录、不使用 `docker volume rm`，用户的公钥和邮箱数据就不会丢失。建议每次更新前先执行备份命令。

### 9. 日常运维

```bash
docker logs -f keyhub              # 查看实时日志
docker restart keyhub              # 重启容器
docker ps                          # 查看运行状态
```

---

## 方式二：裸机部署（gunicorn + systemd）

适用于不想用 Docker 的场景，直接在 ECS 上运行 Python 代码。

### 1. 把代码上传到服务器（任选其一）

方法 A：用 scp 上传本机代码
```bash
scp -r /path/to/keyhub root@你的ECS公网IP:/opt/keyhub
```

方法 B：先推到 git，再在 ECS 上 clone
```bash
ssh root@你的ECS公网IP
git clone 你的仓库地址 /opt/keyhub
```

### 2. 安装系统依赖（Ubuntu/Debian）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

### 3. 创建虚拟环境并安装项目依赖

```bash
cd /opt/keyhub
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn        # 生产用 WSGI 服务器
```

### 4. 配置环境变量

```bash
cp .env.example .env
nano .env
#   FLASK_DEBUG=False
#   FLASK_SECRET_KEY=随便输一串很长的随机字符，比如 openssl rand -hex 32
#   SMTP_HOST / SMTP_PORT / SMTP_USE_SSL / SMTP_USER / SMTP_PASSWORD / SMTP_FROM_NAME
#   按你的邮箱服务商填写（例如 QQ邮箱需要在设置里开启SMTP并拿"授权码"）
```

### 5. 先用 Flask 开发服务器跑一下，看能不能通

```bash
python app.py
# 浏览器访问 http://ECS公网IP:5000 （记得在阿里云控制台安全组放行 5000 端口，仅测试用）
# 测试：
#   - /register 注册一个用户（粘贴你自己的 GPG 公钥）
#   - 回到首页，选中该用户，发送一段消息，检查是否成功加密
# 确认没问题后 Ctrl+C 停掉
```

### 6. 用 systemd + gunicorn 运行（生产方式）

```bash
cp keyhub.service.example /etc/systemd/system/keyhub.service
# 编辑它，修改 User / WorkingDirectory / 以及 Environment 段（推荐直接把变量写在 service 文件里）
nano /etc/systemd/system/keyhub.service

sudo systemctl daemon-reload
sudo systemctl enable --now keyhub
sudo systemctl status keyhub          # 应该显示 active (running)
curl http://127.0.0.1:5000/healthz    # 本地能通
```

### 7. 用 nginx 做反向代理（带 HTTPS 强烈建议）

```bash
cat > /etc/nginx/sites-available/keyhub <<'EOF'
server {
    listen 80;
    server_name 你的域名.com;              # 如果没买域名，这里填 _ 就行

    client_max_body_size 8M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/keyhub /etc/nginx/sites-enabled/keyhub
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 8. （强烈推荐）免费 HTTPS 证书

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名.com         # 按提示填邮箱，它会自动改写 nginx 配置并续期
```

### 9. 阿里安全组 / 防火墙只放行 80 443（把之前临时开的 5000 关掉）

```bash
# Ubuntu 默认用 ufw：
ufw allow 80
ufw allow 443
ufw --force enable
# 别忘了阿里云控制台 -> ECS -> 安全组 -> 入方向也放开 80 / 443
```

### 10. 后续日常运维

```bash
sudo systemctl restart keyhub         # 改了代码之后
sudo journalctl -u keyhub -f          # 看实时日志
# data/users.json 里是所有用户，备份这个文件即可：
tar czf keyhub-backup-$(date +%Y%m%d).tar.gz data/ .env
```

### 11. 更新代码（裸机方式）

```bash
cd /opt/keyhub
# 先备份
tar czf keyhub-backup-$(date +%Y%m%d).tar.gz data/ .env

# 拉新代码（git 方式，最安全，不会动 data/ 目录）
git pull

# 安装新增依赖
source .venv/bin/activate
pip install -r requirements.txt

# 重启服务
sudo systemctl restart keyhub
```

> ⚠️ 如果用 scp 手动传文件，**只传代码文件，不要传 `data/` 目录**，否则会覆盖用户数据。
