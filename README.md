# SMS 验证码中转站

手机转发软件 → `https://sms.<你的域名>/push` → 外网 Docker（FastAPI + SQLite）→ 内网服务调用 `/code` 取验证码。

## 接口
| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| GET | `/health` | 无 | 健康检查 |
| POST | `/push` | `X-Token` | JSON 或表单；正文字段 `body`/`text`/`msg`/`content`，发送方 `from`/`sender`；自动提取 4-8 位验证码 |
| GET | `/code?keyword=&since=` | `X-Token` | 返回最新一条未使用且未过期（`CODE_TTL`，默认 300 秒）的验证码并标记已用；无则 404。`keyword` 匹配短信内容或发送方，`since` 为 Unix 时间戳 |
| GET | `/latest?n=10` | `X-Token` | 最近 n 条原始记录，调试用 |

## 部署（外网电脑）
```bash
git clone https://github.com/chenyonghuang8-bot/sms.git && cd sms
cp .env.example .env
openssl rand -hex 32   # 把结果填到 .env 的 RELAY_TOKEN
docker compose up -d --build                     # 只启动中转服务（仅本机 127.0.0.1:8080）
docker compose --profile tunnel up -d --build    # 同时启动 cloudflared 隧道
```
数据保存在 `./data/sms.db`，旧记录（默认 24 小时，`KEEP_SECONDS`）定时清理。

## Cloudflare Tunnel 配置
1. 域名托管在 Cloudflare。进入 Zero Trust → Networks → Tunnels → Create a tunnel → 选 Cloudflared。
2. 复制给出的 token，填到 `.env` 的 `TUNNEL_TOKEN`。
3. Public Hostname 添加：Subdomain `sms`，Domain 选你的域名，Service 类型 `HTTP`，URL `relay:8080`（即 `http://relay:8080`）。
4. `docker compose --profile tunnel up -d`，访问 `https://sms.<域名>/health` 返回 `{"ok":true}` 即成功。外网电脑无需开放端口。

## 手机转发软件配置（如 SmsForwarder 的 Webhook）
- URL：`https://sms.<域名>/push`
- 方法：`POST`
- Header：`X-Token: <RELAY_TOKEN>`
- Body（JSON）：`{"from": "[from]", "body": "[content]"}`（占位符按软件实际写法填写）；也可用表单 `body=...`

测试：
```bash
curl -X POST https://sms.<域名>/push -H "X-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"from":"10690","body":"【某平台】验证码 123456"}'
```

## 内网使用
```bash
curl -G https://sms.<域名>/code -H "X-Token: $TOKEN" --data-urlencode keyword=某平台
```
Python 轮询见 `client_example.py`：触发发送验证码前记录 `since=time.time()`，再调用 `wait_code(url, token, keyword, since=since)`，避免取到旧验证码。

## 安全建议
- `RELAY_TOKEN` 用 32 字节以上随机串，不要提交 `.env`。
- 在 Cloudflare 对 `/code`、`/latest` 加一层 Access（Service Token）或 WAF 规则只允许内网出口 IP；`/push` 保持 token 认证供手机使用。
- 验证码取用即失效、默认 5 分钟过期；只用于你自己的账号。

## 开发
```bash
pip install -r requirements-dev.txt && pytest -q
RELAY_TOKEN=dev DB_PATH=./data/dev.db uvicorn app.main:app --port 8080
```
