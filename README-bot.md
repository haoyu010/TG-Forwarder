# TG-Forwarder Bot 版（无 api_id / 无用户登录）

链路：`https://t.me/s/Ms20260601`（公开预览） → 30 秒轮询 → Bot API → `@xiaotiancaixu`

## 前提

1. 在 @BotFather 创建 bot，拿到 token。
2. 把 bot 加进 `@xiaotiancaixu`，设为管理员，给“发布消息”权限。
3. 飞牛能访问 `t.me` 和 `api.telegram.org`；不能直连就配 `HTTPS_PROXY`。

## 部署

```bash
cp .env.bot.example .env.bot
vi .env.bot   # 填 TELEGRAM_BOT_TOKEN

docker compose -f docker-compose.bot.yml up -d --build
docker logs -f tg-ms20260601-forwarder
```

首次启动会把当前已存在的帖子标记为已读，不会刷屏。

## 验证

```bash
# 发一条最新帖子到目标频道
docker compose -f docker-compose.bot.yml run --rm forwarder \
  python -m app.web_forwarder --test-send
```

## 补历史

```bash
# 补最近 20 条
docker compose -f docker-compose.bot.yml run --rm forwarder \
  python -m app.web_forwarder --backfill 20
```

## 本地 dry-run（不发送）

```bash
python web_forwarder.py --dry-run --limit 20
```

## 目录

- `app/web_forwarder.py`：主程序
- `Dockerfile.bot`：bot 版镜像
- `docker-compose.bot.yml`：bot 版 compose
- `data/web_forwarder.sqlite3`：已发送记录 / 剧集去重
