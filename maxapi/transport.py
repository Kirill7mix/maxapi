"""
TCP/SSL транспорт для MAX мессенджера.

Подключается к api.oneme.ru:443 (SSL), отправляет/получает бинарные пакеты.
После SESSION_INIT сервер может вернуть proxy-хост для переключения.
"""

import asyncio
import ssl
import logging
import struct
from typing import Optional, Callable, Awaitable, Dict

from maxapi.constants import PACKET_HEADER_SIZE
from maxapi.protocol import decode_header, decode_packet, Packet

logger = logging.getLogger("maxapi.transport")

DEFAULT_HOST = "api.oneme.ru"
DEFAULT_PORT = 443


class Connection:
    """
    Асинхронное TCP/SSL подключение к серверу MAX.

    Управляет чтением/записью пакетов, нумерацией seq,
    и диспетчеризацией входящих пакетов.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._seq: int = 0
        self._connected = False
        self._read_task: Optional[asyncio.Task] = None

        # Колбэки для входящих пакетов: opcode -> callback(Packet)
        self._handlers: Dict[int, Callable[[Packet], Awaitable[None]]] = {}
        # Ожидающие ответов: seq -> Future
        self._pending: Dict[int, asyncio.Future] = {}
        # Общий обработчик для уведомлений (пакеты без seq-ответа)
        self._notification_handler: Optional[Callable[[Packet], Awaitable[None]]] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Устанавливает SSL-соединение с сервером."""
        if self._connected:
            return

        ctx = ssl.create_default_context()
        logger.info("Подключение к %s:%d ...", self.host, self.port)

        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port, ssl=ctx
        )
        self._connected = True
        self._seq = 0
        logger.info("Подключено к %s:%d", self.host, self.port)

        # Запускаем фоновое чтение
        self._read_task = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        """Закрывает соединение."""
        self._connected = False
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

        # Отменяем все ожидающие
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Соединение закрыто"))
        self._pending.clear()
        logger.info("Отключено от %s:%d", self.host, self.port)

    async def reconnect(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        """Переподключение (возможно к другому хосту, например proxy)."""
        await self.disconnect()
        if host:
            self.host = host
        if port:
            self.port = port
        await self.connect()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq & 0xFFFF

    async def send(self, packet: Packet, wait_response: bool = True, timeout: float = 30.0) -> Optional[Packet]:
        """
        Отправляет пакет и опционально ждёт ответ.

        Args:
            packet: Пакет для отправки.
            wait_response: Если True, ждём ответ с таким же seq.
            timeout: Таймаут ожидания ответа (сек).

        Returns:
            Ответный пакет или None.
        """
        if not self._connected or not self._writer:
            raise ConnectionError("Не подключено к серверу")

        seq = self._next_seq()
        data = packet.encode(seq=seq)

        logger.debug(">>> Отправка: opcode=%d seq=%d len=%d", packet.opcode, seq, len(data))
        self._writer.write(data)
        await self._writer.drain()

        if not wait_response:
            return None

        # Создаём Future для ожидания ответа
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Packet] = loop.create_future()
        self._pending[seq] = fut

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(seq, None)
            raise TimeoutError(f"Таймаут ожидания ответа на seq={seq}, opcode={packet.opcode}")

    async def _read_loop(self) -> None:
        """Фоновый цикл чтения пакетов."""
        try:
            while self._connected and self._reader:
                # Читаем заголовок (10 байт)
                header = await self._reader.readexactly(PACKET_HEADER_SIZE)
                version, cmd, seq, opcode, compression_ratio, payload_length = decode_header(header)

                logger.debug(
                    "<<< Получен заголовок: opcode=%d seq=%d payload_len=%d cr=%d",
                    opcode, seq, payload_length, compression_ratio
                )

                # Читаем payload
                payload = b""
                if payload_length > 0:
                    payload = await self._reader.readexactly(payload_length)

                # Декодируем
                params = decode_packet(header, payload, compression_ratio)
                pkt = Packet(opcode=opcode, params=params, cmd=cmd, seq=seq)
                pkt.compression_ratio = compression_ratio
                pkt.payload_length = payload_length

                logger.debug("<<< Декодирован: %s", pkt)

                # Диспетчеризация
                await self._dispatch(pkt)

        except asyncio.IncompleteReadError:
            logger.warning("Соединение разорвано (неполное чтение)")
            self._connected = False
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Ошибка в read_loop: %s", e, exc_info=True)
            self._connected = False

    async def _dispatch(self, packet: Packet) -> None:
        """Диспетчеризация входящего пакета."""
        seq = packet.seq

        # Пакеты с опкодом >= 128 — серверные уведомления (push).
        # Они никогда не являются ответами на наши запросы,
        # даже если seq случайно совпадает. Отправляем прямо в handlers.
        is_notification = packet.opcode >= 128

        # Проверяем, есть ли ожидающий ответ по seq
        if not is_notification and seq in self._pending:
            fut = self._pending.pop(seq)
            if not fut.done():
                fut.set_result(packet)
            return

        # Проверяем зарегистрированный обработчик по opcode
        handler = self._handlers.get(packet.opcode)
        if handler:
            try:
                await handler(packet)
            except Exception as e:
                logger.error("Ошибка в обработчике opcode=%d: %s", packet.opcode, e)
            return

        # Общий обработчик уведомлений
        if self._notification_handler:
            try:
                await self._notification_handler(packet)
            except Exception as e:
                logger.error("Ошибка в notification_handler: %s", e)
            return

        logger.debug("Необработанный пакет: %s", packet)

    def on(self, opcode: int, handler: Callable[[Packet], Awaitable[None]]) -> None:
        """Регистрирует обработчик для определённого опкода."""
        self._handlers[opcode] = handler

    def on_notification(self, handler: Callable[[Packet], Awaitable[None]]) -> None:
        """Регистрирует общий обработчик уведомлений."""
        self._notification_handler = handler
