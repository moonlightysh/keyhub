# KeyHub

一个轻量级的 **GPG 加密消息 Web 应用**。用户上传自己的 GPG 公钥后，其他人即可选中该用户作为收件人，输入敏感消息（密码、密钥、账号等），服务器用收件人公钥进行 AES-256 加密并输出 ASCII Armor 密文。用户把密文通过任意渠道发给对方，只有对方持有的私钥才能解密。

## 特性

- 🔒 **端到端加密**：消息在服务器端用收件人 GPG 公钥加密，明文不落地、不外发
- 🔑 **邀请码访问控制**：仅持有邀请码的用户可注册上传公钥，防止身份假冒
- 📝 **JSON 文件存储**：用户数据存于 `data/users.json`，不依赖任何数据库
- 🔐 **公钥合法性校验**：自动拒绝私钥上传，避免用户误操作
- 🚀 **纯 Python 加密栈**：基于 PGPy，无需系统安装 GPG 命令
- ☁️ **可选 OSS 备份**：支持将 `users.json` 定时增量备份到阿里云 OSS

## 技术栈

- 后端：Flask + PGPy（GPG 加密）
- 存储：JSON 文件（fcntl.flock 跨进程锁 + 原子写入）
- 部署：gunicorn + nginx + systemd（阿里云 ECS）

## 快速开始（本地开发）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（可选，留空 INVITE_CODE 则不启用邀请码）
cp .env.example .env
# 编辑 .env，按需填写

# 3. 启动开发服务器
python app.py
# 访问 http://localhost:5000
```

## 环境变量

参见 [.env.example](.env.example)，主要包括：

| 变量 | 说明 |
|------|------|
| `FLASK_SECRET_KEY` | Flask Session 秘钥，生产环境务必修改 |
| `FLASK_PORT` / `FLASK_DEBUG` | 运行端口与调试模式 |
| `INVITE_CODE` | 邀请码，留空则不启用访问控制 |
| `SMTP_*` | 可选，SMTP 直发加密邮件的配置 |
| `OSS_*` | 可选，阿里云 OSS 备份配置 |

## 部署到阿里云 ECS

详见 [DEPLOY_ECS.md](DEPLOY_ECS.md)，核心步骤：`gunicorn` 运行 WSGI、`nginx` 反向代理、`systemd` 守护进程。

## 用户使用文档

面向最终用户的完整使用说明（生成密钥、上传公钥、发送加密消息、解密）见 → [USER_GUIDE.md](USER_GUIDE.md)

## 项目结构

```
keyhub/
├── app.py                  # Flask 主应用（路由：gate / index / register / send）
├── crypto_utils.py         # GPG 公钥校验与加密（PGPy + AES-256）
├── storage.py              # JSON 文件存储（fcntl.flock 跨进程锁）
├── mailer.py               # 可选的 SMTP 加密邮件发送
├── backup_oss.py           # 可选的 OSS 增量备份
├── templates/              # Jinja2 页面模板
├── static/                 # 前端样式
├── data/users.json         # 用户数据（运行时生成）
├── DEPLOY_ECS.md           # ECS 部署文档
└── USER_GUIDE.md           # 用户使用文档
```

## 安全说明

- 明文消息仅在加密过程中存在于服务器内存，加密后立即丢弃，不写入任何存储
- GPG 公钥上传时会校验 `is_public`，拒绝私钥
- 用户数据写入采用「临时文件 + `os.replace` 原子替换」+ `fcntl.flock` 跨进程锁，防止并发损坏
- 邀请码机制防止匿名用户冒用他人邮箱上传公钥（身份假冒攻击）
