# TG-Forwarder Bot 版（无 api_id / 无用户登录）

链路：`https://t.me/s/Ms20260601`（公开预览） → 30 秒轮询 → Bot API → `@xiaotiancaixu`

Dashboard：`http://<飞牛IP>:8001`（复用原 React 前端；原 8000 端口的前端/服务不动）

## 前提

1. 在 @BotFather 创建 bot，拿到 token。
2. 把 bot 加进 `@xiaotiancaixu`，设为管理员，给“发布消息”权限。
3. 飞牛能访问 `t.me`、`api.telegram.org`、`api.themoviedb.org`。

## 部署

```bash
cp .env.bot.example .env.bot
vi .env.bot   # 填 TELEGRAM_BOT_TOKEN

docker compose -f docker-compose.bot.yml up -d --build
docker logs -f tg-ms20260601-forwarder
```

Dashboard：`http://<飞牛IP>:8001`

首次启动会把当前已存在的帖子标记为已读，不会刷屏。

## 验证

```bash
# 发一条最新允许帖子到目标频道
docker exec tg-ms20260601-forwarder python -m app.web_forwarder --test-send
```

## 补历史

```bash
# 补最近 20 条（只发允许的）
docker exec tg-ms20260601-forwarder python -m app.web_forwarder --backfill 20
```

## 目录

- `app/web_forwarder.py`：抓取/过滤/发送核心
- `app/bot_api.py`：FastAPI Dashboard + 后台循环
- `Dockerfile.bot`：多阶段构建（Node 构建前端 + Python 运行）
- `docker-compose.bot.yml`：bot 版 compose，端口 8001
- `config.bot.yaml`：bot 专用配置（过滤规则从原 config.yaml 复制）
- `data/bot/web_forwarder.sqlite3`：已发送/过滤/记录/去重
