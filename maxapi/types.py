"""
Типы данных MAX API — объекты, которые передаются в обработчики событий.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from maxapi.client import MaxClient


class Message:
    """
    Входящее или исходящее сообщение (опкод NOTIF_MESSAGE = 128).

    Атрибуты:
        id          — уникальный ID сообщения
        chat_id     — ID чата
        sender_id   — UID отправителя
        sender_name — имя отправителя (из кэша контактов, или str(sender_id))
        text        — текст сообщения
        time_ms     — время в миллисекундах
        elements    — список элементов форматирования (STRONG, EMPHASIZED, ...)
        attaches    — список вложений (PHOTO, STICKER, FILE, ...)
        link        — объект ссылки (REPLY / FORWARD) или None
        raw         — полный dict из сервера (params пакета)

    Свойства:
        is_outgoing — True если отправили мы
        is_reply    — True если это ответ (цитата) на другое сообщение
        is_forward  — True если это пересланное сообщение
        reply_to_message — dict исходного сообщения при REPLY
        forwarded_message — dict пересланного сообщения при FORWARD

    Методы:
        await message.reply("текст")    — ответить в тот же чат с цитированием
        await message.forward(chat_id)  — переслать это сообщение в другой чат
    """

    __slots__ = (
        "id", "chat_id", "sender_id", "text", "time_ms",
        "elements", "attaches", "link",
        "raw", "_client",
    )

    def __init__(self, chat_id: int, msg: Dict[str, Any], raw: Dict[str, Any], client: "MaxClient"):
        self._client = client
        self.raw = raw
        self.chat_id = chat_id
        self.id: int = msg.get("id", 0)
        self.sender_id: int = msg.get("sender", 0)
        self.text: str = msg.get("text") or ""
        self.time_ms: int = msg.get("time", 0)
        self.elements: List[Dict[str, Any]] = msg.get("elements", [])
        self.attaches: List[Dict[str, Any]] = msg.get("attaches", [])
        self.link: Optional[Dict[str, Any]] = msg.get("link")

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

    @property
    def sender_name(self) -> str:
        """Имя отправителя из кэша контактов, или строка с UID если не найден."""
        for contact in self._client._contacts:
            if contact.get("id") == self.sender_id:
                for name_entry in contact.get("names", []):
                    first = name_entry.get("firstName", "")
                    last = name_entry.get("lastName", "")
                    full = f"{first} {last}".strip()
                    if full:
                        return full
                break
        # Проверяем профиль самого клиента
        if self.sender_id == self._client.uid:
            return self._client._profile.get("name", str(self.sender_id))
        return str(self.sender_id)

    @property
    def is_reply(self) -> bool:
        """True — если это ответ (цитата) на другое сообщение."""
        return bool(self.link and self.link.get("type") == "REPLY")

    @property
    def is_forward(self) -> bool:
        """True — если это пересланное сообщение."""
        return bool(self.link and self.link.get("type") == "FORWARD")

    @property
    def reply_to_message(self) -> Optional[Dict[str, Any]]:
        """Объект исходного сообщения при REPLY (или None)."""
        if self.is_reply:
            return self.link.get("message")
        return None

    @property
    def forwarded_message(self) -> Optional[Dict[str, Any]]:
        """Объект пересланного сообщения при FORWARD (или None)."""
        if self.is_forward:
            return self.link.get("message")
        return None

    async def reply(self, text, **kwargs) -> Dict[str, Any]:
        """Ответить в тот же чат (с цитированием исходного сообщения).

        Args:
            text: Текст (str) или FormattedText.
            **kwargs: Дополнительные аргументы для send_message (attaches, elements).
        """
        return await self._client.send_message(self.chat_id, text, reply_to=self.id, **kwargs)

    async def forward(self, to_chat_id: int, text: str = "") -> Dict[str, Any]:
        """Переслать это сообщение в другой чат."""
        return await self._client.forward_message(to_chat_id, self.chat_id, self.id, text=text)

    def __repr__(self) -> str:
        direction = "OUT" if self.is_outgoing else "IN"
        extras = []
        if self.is_reply:
            extras.append("reply")
        if self.is_forward:
            extras.append("forward")
        if self.elements:
            extras.append(f"fmt={len(self.elements)}")
        if self.attaches:
            types = [a.get('_type', '?') for a in self.attaches]
            extras.append(f"att={','.join(types)}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        return (
            f"<Message [{direction}]{extra_str} "
            f"chat={self.chat_id} from={self.sender_id} "
            f"text={self.text!r:.40}>"
        )


class TypingEvent:
    """
    Событие печатания (опкод NOTIF_TYPING = 129).

    Атрибуты:
        chat_id     — ID чата
        sender_id   — UID пользователя, который печатает
        typing_type — тип набора: None (текст), "STICKER" и т.д.
        raw         — полный dict из сервера
    """

    __slots__ = ("chat_id", "sender_id", "typing_type", "raw")

    def __init__(self, params: Dict[str, Any]):
        self.raw = params
        self.chat_id: int = params.get("chatId", 0)
        self.sender_id: int = params.get("userId", 0)
        self.typing_type: Optional[str] = params.get("type")

    def __repr__(self) -> str:
        t = f" type={self.typing_type}" if self.typing_type else ""
        return f"<TypingEvent chat={self.chat_id} user={self.sender_id}{t}>"
