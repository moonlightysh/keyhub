# ======= KeyHub 部署到阿里云 ECS（Ubuntu 22.04 示例） =======

# 1. 把代码上传到服务器（任选其一）
#   方法 A：用 scp 上传本机代码
#      scp -r /path/to/keyhub root@你的ECS公网IP:/opt/keyhub
#   方法 B：先推到 git，再在 ECS 上 clone
ssh root@你的ECS公网IP

# 2. 安装系统依赖（Ubuntu/Debian）
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx

# 3. 创建虚拟环境并安装项目依赖
cd /opt/keyhub
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn        # 生产用 WSGI 服务器

# 4. 配置环境变量
cp .env.example .env
nano .env
#   FLASK_DEBUG=False
#   FLASK_SECRET_KEY=随便输一串很长的随机字符，比如 openssl rand -hex 32
#   SMTP_HOST / SMTP_PORT / SMTP_USE_SSL / SMTP_USER / SMTP_PASSWORD / SMTP_FROM_NAME
#   按你的邮箱服务商填写（例如 QQ邮箱需要在设置里开启SMTP并拿“授权码”）

# 5. 先用 Flask 开发服务器跑一下，看能不能通
#    然后浏览器访问 http://ECS公网IP:5000 （记得在阿里云控制台安全组放行 5000 端口，仅测试用）
python app.py
#    浏览器里测试：
#      - /register 注册一个用户（粘贴你自己的 GPG 公钥）
#      - 回到首页，选中该用户，发送一段消息，检查是否成功加密
#    确认没问题后 Ctrl+C 停掉

# 6. 用 systemd + gunicorn 运行（生产方式）
cp keyhub.service.example /etc/systemd/system/keyhub.service
#   编辑它，修改 User / WorkingDirectory / 以及 Environment 段（推荐直接把变量写在 service 文件里）
nano /etc/systemd/system/keyhub.service

sudo systemctl daemon-reload
sudo systemctl enable --now keyhub
sudo systemctl status keyhub          # 应该显示 active (running)
curl http://127.0.0.1:5000/healthz    # 本地能通

# 7. 用 nginx 做反向代理（带 HTTPS 强烈建议）
#    新建 nginx 站点
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

# 8. （强烈推荐）免费 HTTPS 证书
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名.com         # 按提示填邮箱，它会自动改写 nginx 配置并续期

# 9. 阿里安全组 / 防火墙只放行 80 443（把之前临时开的 5000 关掉）
#    Ubuntu 默认用 ufw：
ufw allow 80
ufw allow 443
ufw --force enable
#    别忘了阿里云控制台 -> ECS -> 安全组 -> 入方向也放开 80 / 443

# 10. 后续日常运维
sudo systemctl restart keyhub         # 改了代码之后
sudo journalctl -u keyhub -f          # 看实时日志
#   data/users.json 里是所有用户，备份这个文件即可：
tar czf keyhub-backup-$(date +%Y%m%d).tar.gz data/ .env
