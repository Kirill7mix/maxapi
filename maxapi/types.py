"""
Типы данных MAX API — объекты, которые передаются в обработчики событий.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from maxapi.client import MaxClient


class Message:
    """
    Входящее или исходящее сообщение (опкод NOTIF_MESSAGE = 128).

    Атрибуты:
        id        — уникальный ID сообщения
        chat_id   — ID чата
        sender_id — UID отправителя
        text      — текст сообщения
        time_ms   — время в миллисекундах
        raw       — полный dict из сервера (params пакета)

    Методы:
        await message.reply("текст")  — ответить в тот же чат
        message.is_outgoing           — True если отправили мы
    """

    __slots__ = ("id", "chat_id", "sender_id", "text", "time_ms", "raw", "_client")

    def __init__(self, chat_id: int, msg: Dict[str, Any], raw: Dict[str, Any], client: "MaxClient"):
        self._client = client
        self.raw = raw
        self.chat_id = chat_id
        self.id: int = msg.get("id", 0)
        self.sender_id: int = msg.get("sender", 0)
        self.text: str = msg.get("text") or ""
        self.time_ms: int = msg.get("time", 0)

    @classmethod
    def from_packet(cls, params: Dict[str, Any], client: "MaxClient") -> "Message":
        """Создаёт Message из params пакета NOTIF_MESSAGE."""
        chat_id = params.get("chatId", 0)
        msg = params.get("message", {})
        return cls(chat_id=chat_id, msg=msg, raw=params, client=client)

    @property
    def is_outgoing(self) -> bool:
        """True — если сообщение отправили мы сами."""
        return self.sender_id == self._client.uid

    async def reply(self, text: str) -> Dict[str, Any]:
        """Ответить в тот же чат."""
        return await self._client.send_message(self.chat_id, text)

    def __repr__(self) -> str:
        direction = "OUT" if self.is_outgoing else "IN"
        return (
            f"<Message [{direction}] "
            f"chat={self.chat_id} from={self.sender_id} "
            f"text={self.text!r:.40}>"
        )


class TypingEvent:
    """
    Событие печатания (опкод NOTIF_TYPING = 129).

    Атрибуты:
        chat_id   — ID чата
        sender_id — UID пользователя, который печатает
        raw       — полный dict из сервера
    """

    __slots__ = ("chat_id", "sender_id", "raw")

    def __init__(self, params: Dict[str, Any]):
        self.raw = params
        self.chat_id: int = params.get("chatId", 0)
        self.sender_id: int = params.get("userId", 0)

    def __repr__(self) -> str:
        return f"<TypingEvent chat={self.chat_id} user={self.sender_id}>"
