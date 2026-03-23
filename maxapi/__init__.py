"""
MAX Messenger Client API (reverse-engineered from APK v26.9.0)
Аналог Telethon для MAX (ex-TamTam) мессенджера от VK.

Использование:
    import asyncio
    from maxapi import MaxClient

    async def main():
        async with MaxClient("my_session") as client:
            await client.send_code("+79001234567")
            code = input("Введите код из SMS: ")
            await client.sign_in(code)

            chats = await client.get_chats()
            print(chats)

    asyncio.run(main())
"""
from maxapi.client import MaxClient, AuthResult, SentCode, AuthError
from maxapi.session import Session
from maxapi.protocol import Packet
from maxapi.constants import OpCode
from maxapi.types import Message, TypingEvent
from maxapi.formatting import FormattedText

__version__ = "0.2.0"
__all__ = [
    "MaxClient",
    "Session",
    "Packet",
    "OpCode",
    "Message",
    "TypingEvent",
    "FormattedText",
    "AuthResult",
    "SentCode",
    "AuthError",
]
