from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import TelegramConfig


@dataclass
class LoginState:
    phone: str | None = None
    phone_code_hash: str | None = None
    status: str = "idle"
    message: str = ""


class TelegramLoginManager:
    def __init__(self, telegram: TelegramConfig):
        self.telegram = telegram
        self.client: Any | None = None
        self.state = LoginState()

    async def send_code(self, phone: str) -> LoginState:
        from telethon import TelegramClient

        self.client = TelegramClient(self.telegram.session_path, self.telegram.api_id, self.telegram.api_hash)
        await self.client.connect()
        sent = await self.client.send_code_request(phone)
        self.state = LoginState(
            phone=phone,
            phone_code_hash=sent.phone_code_hash,
            status="code_sent",
            message="验证码已发送到 Telegram",
        )
        return self.state

    async def sign_in(self, code: str, password: str | None = None) -> LoginState:
        if not self.client:
            raise RuntimeError("请先发送验证码")
        if not self.state.phone:
            raise RuntimeError("缺少手机号")

        from telethon.errors import SessionPasswordNeededError

        try:
            await self.client.sign_in(phone=self.state.phone, code=code, phone_code_hash=self.state.phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                self.state.status = "password_required"
                self.state.message = "需要 Telegram 二步验证密码"
                return self.state
            await self.client.sign_in(password=password)

        me = await self.client.get_me()
        await self.client.disconnect()
        self.state = LoginState(
            phone=self.state.phone,
            phone_code_hash=None,
            status="signed_in",
            message=f"登录成功：{getattr(me, 'username', None) or getattr(me, 'id', 'unknown')}",
        )
        return self.state
