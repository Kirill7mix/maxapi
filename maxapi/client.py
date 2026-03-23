"""
Клиент MAX мессенджера — аналог Telethon для VK MAX (ex-TamTam).

Пример использования:
    import asyncio
    from maxapi import MaxClient

    async def main():
        async with MaxClient("my_session") as client:
            await client.send_code("+79001234567")
            await client.sign_in(input("Код из SMS: "))

            me = client.me                          # Профиль из LOGIN
            chats = client.cached_chats             # Чаты из LOGIN
            chats = await client.get_chats()        # Свежие чаты с сервера

            await client.send_message(chat_id, "Привет!")
    asyncio.run(main())
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Callable, Awaitable

if TYPE_CHECKING:
    from maxapi.formatting import FormattedText

import aiohttp

from maxapi.constants import API_URL, APP_KEY, OpCode
from maxapi.protocol import Packet
from maxapi.transport import Connection, DEFAULT_HOST, DEFAULT_PORT
from maxapi.session import Session
from maxapi.types import Message, TypingEvent, PresenceEvent, ReactionEvent

logger = logging.getLogger("maxapi.client")

# Версия приложения MAX (из APK)
APP_VERSION = "26.9.0"
BUILD_NUMBER = 6637
DEVICE_TYPE = "ANDROID"
OS_VERSION = "14"
ARCH = "arm64-v8a"


class MaxClient:
    """
    Клиент MAX мессенджера.

    Использование (аналог Telethon):
        async with MaxClient("my_session") as client:
            await client.send_code("+79001234567")
            code = input("Введите код из SMS: ")
            await client.sign_in(code)

            # Получить чаты
            chats = await client.get_chats()

            # Отправить сообщение
            await client.send_message(chat_id, "Привет!")
    """

    def __init__(self, session: str = "max_session"):
        """
        Args:
            session: Имя файла сессии (без .json) или объект Session.
        """
        if isinstance(session, Session):
            self._session = session
        else:
            self._session = Session(f"{session}.json")

        self._conn: Optional[Connection] = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._logged_in = False

        # Кэш данных из LOGIN-ответа
        self._login_data: Dict[str, Any] = {}
        self._profile: Dict[str, Any] = {}   # profile.contact
        self._chats: List[Dict] = []          # список чатов
        self._contacts: List[Dict] = []       # список контактов
        self._presence: Dict[str, Any] = {}  # статусы онлайн
        self._chat_marker: int = 0            # маркер для пагинации чатов
        self._config: Dict[str, Any] = {}     # конфигурация сервера

        # Обработчики событий: opcode -> [async callable]
        self._handlers: Dict[int, List[Callable]] = {}

    @property
    def session(self) -> Session:
        return self._session

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and self._conn.connected

    @property
    def is_authorized(self) -> bool:
        return self._session.is_authorized

    @property
    def me(self) -> Dict[str, Any]:
        """Профиль текущего пользователя из кэша LOGIN.
        Для свежего профиля с сервера — используйте await client.get_profile()."""
        return self._profile

    @property
    def uid(self) -> int:
        """UID текущего пользователя."""
        return self._session.uid

    @property
    def cached_chats(self) -> List[Dict]:
        """Список чатов из кэша (LOGIN-ответ)."""
        return self._chats

    @property
    def cached_contacts(self) -> List[Dict]:
        """Список контактов из кэша (LOGIN-ответ)."""
        return self._contacts

    # ── Управление подключением ─────────────────────

    async def connect(self) -> None:
        """Подключается к серверу MAX (OK API + TCP/SSL)."""
        # HTTP-клиент для OK API
        if not self._http or self._http.closed:
            self._http = aiohttp.ClientSession()

        # Шаг 1: Анонимная сессия OK API (если нет)
        if not self._session.has_session:
            await self._anonym_login()

        # Шаг 2: TCP подключение
        host = self._session.proxy_host or DEFAULT_HOST
        self._conn = Connection(host=host, port=DEFAULT_PORT)
        await self._conn.connect()

        # Шаг 3: SESSION_INIT
        await self._session_init()

        # Шаг 4: Автоматический логин если есть токен
        if self._session.is_authorized and not self._logged_in:
            try:
                logger.info("Автоматический вход с сохраненным токеном...")
                await self.login_with_token(self._session.auth_token)
            except Exception as e:
                logger.error("Ошибка авто-входа: %s", e)

        # Шаг 5: Подключаем диспетчер push-уведомлений
        self._conn.on_notification(self._dispatch_notification)

    async def disconnect(self) -> None:
        """Отключается от сервера."""
        if self._conn:
            await self._conn.disconnect()
            self._conn = None
        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None
        self._logged_in = False  # сбрасываем флаг — следующий connect() выполнит LOGIN заново
        self._session.save()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    # ── Событийные обработчики (handlers) ──────────

    def on(self, opcode: int) -> Callable:
        """
        Декоратор: регистрирует обработчик для входящего пакета по opcode.

        Для сообщений используйте удобный шорткат @client.on_message.

        Пример::

            @client.on(OpCode.NOTIF_TYPING)
            async def on_typing(event: TypingEvent):
                print(f"Печатает: {event.sender_id}")

            @client.on(OpCode.NOTIF_PRESENCE)
            async def on_presence(event: dict):
                print(event)
        """
        def decorator(func: Callable) -> Callable:
            self._handlers.setdefault(opcode, []).append(func)
            return func
        return decorator

    def on_message(self, func: Callable) -> Callable:
        """
        Декоратор: обработчик входящих сообщений (NOTIF_MESSAGE, opcode 128).

        Передаёт объект Message с полями id, chat_id, sender_id, text,
        is_outgoing и методом reply().

        Пример::

            @client.on_message
            async def handler(msg: Message):
                if not msg.is_outgoing:
                    await msg.reply("Привет!")
        """
        self._handlers.setdefault(OpCode.NOTIF_MESSAGE, []).append(func)
        return func

    def on_reaction(self, func: Callable) -> Callable:
        """
        Декоратор: обработчик изменения реакций (NOTIF_MSG_REACTIONS_CHANGED, opcode 155).

        Передаёт объект ReactionEvent.

        Пример::

            @client.on_reaction
            async def handler(event: ReactionEvent):
                print(f"Реакция на сообщение {event.message_id}: {event.top_reaction}")
        """
        self._handlers.setdefault(OpCode.NOTIF_MSG_REACTIONS_CHANGED, []).append(func)
        return func

    def on_presence(self, func: Callable) -> Callable:
        """
        Декоратор: обработчик изменения статуса пользователя (NOTIF_PRESENCE, opcode 132).

        Передаёт объект PresenceEvent.

        Пример::

            @client.on_presence
            async def handler(event: PresenceEvent):
                if event.is_online:
                    print(f"Пользователь {event.user_id} вошёл онлайн")
        """
        self._handlers.setdefault(OpCode.NOTIF_PRESENCE, []).append(func)
        return func

    async def _dispatch_notification(self, pkt: "Packet") -> None:
        """Внутренний диспетчер: вызывает обработчики по opcode пакета.

        Каждый обработчик запускается как отдельная asyncio-задача —
        это позволяет хендлерам делать await (например send_message)
        без блокировки _read_loop.
        """
        handlers = self._handlers.get(pkt.opcode)
        if not handlers:
            return

        # Строим удобный объект в зависимости от opcode
        if pkt.opcode == OpCode.NOTIF_MESSAGE:
            event = Message.from_packet(pkt.params, self)
        elif pkt.opcode == OpCode.NOTIF_TYPING:
            event = TypingEvent(pkt.params)
        elif pkt.opcode == OpCode.NOTIF_PRESENCE:
            event = PresenceEvent(pkt.params)
        elif pkt.opcode == OpCode.NOTIF_MSG_REACTIONS_CHANGED:
            event = ReactionEvent(pkt.params)
        else:
            event = pkt.params  # сырой dict для остальных

        for handler in handlers:
            asyncio.create_task(self._run_handler(handler, event, pkt.opcode))

    async def _run_handler(self, handler: Callable, event: Any, opcode: int) -> None:
        """Запускает один обработчик, перехватывает исключения."""
        try:
            await handler(event)
        except Exception as e:
            logger.error("Ошибка в обработчике opcode=%d: %s", opcode, e, exc_info=True)

    async def run_until_disconnected(self) -> None:
        """
        Блокирует выполнение до разрыва соединения.

        Используйте после регистрации обработчиков::

            @client.on_message
            async def handler(msg):
                ...

            await client.connect()
            await client.run_until_disconnected()
        """
        try:
            while self.is_connected:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        """
        Удобный ярлык: подключиться и ждать до разрыва соединения.

        Использование::

            @client.on_message
            async def handler(msg):
                ...

            asyncio.run(client.run())
        """
        await self.connect()
        await self.run_until_disconnected()

    # ── OK API (HTTP) ───────────────────────────────

    @staticmethod
    def _calculate_sig(params: dict, session_secret: str) -> str:
        """Подпись для OK API (MD5)."""
        sorted_params = sorted(params.items())
        sig_string = "".join(f"{k}={v}" for k, v in sorted_params)
        sig_string += session_secret
        return hashlib.md5(sig_string.encode("utf-8")).hexdigest()

    async def _ok_api_call(self, method: str, extra_params: dict = None) -> dict:
        """Вызов OK API с подписью."""
        params = {
            "application_key": APP_KEY,
            "method": method,
        }
        if self._session.session_key:
            params["session_key"] = self._session.session_key
        if extra_params:
            params.update(extra_params)

        params["sig"] = self._calculate_sig(params, self._session.session_secret_key)

        async with self._http.post(
            f"{API_URL}/{method.replace('.', '/')}",
            data=params,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        ) as resp:
            return await resp.json()

    async def _anonym_login(self, auth_token: str = None) -> dict:
        """
        OK API auth.anonymLogin — получение анонимной сессии.

        Если auth_token передан — используем его для получения авторизованной сессии.
        """
        if auth_token:
            session_data = json.dumps({
                "auth_token": auth_token,
                "version": 3,
                "device_id": self._session.device_id,
                "client_version": 1,
            })
        else:
            session_data = json.dumps({
                "version": 2,
                "device_id": self._session.device_id,
                "client_version": 1,
            })

        params = {
            "application_key": APP_KEY,
            "method": "auth.anonymLogin",
            "client": "android",
            "deviceId": self._session.device_id,
            "verification_supported": "true",
            "verification_supported_v": "1",
            "gen_token": "true",
            "session_data": session_data,
        }

        async with self._http.post(
            f"{API_URL}/auth/anonymLogin",
            data=params,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        ) as resp:
            result = await resp.json()

        if "error_code" in result:
            raise AuthError(f"anonymLogin failed: {result.get('error_msg', result)}")

        self._session.session_key = result.get("session_key", "")
        self._session.session_secret_key = result.get("session_secret_key", "")
        self._session.api_server = result.get("api_server", "https://api.ok.ru/")
        self._session.uid = int(result.get("uid", 0))
        self._session.save()

        logger.info("Анонимная сессия получена. UID=%s", self._session.uid)
        return result

    # ── TCP протокол ────────────────────────────────

    async def _session_init(self) -> dict:
        """
        Отправляет SESSION_INIT (opcode 6) серверу.
        Получает proxy-хост и конфигурацию.

        Аналог x3g.java → y3g.java.
        """
        user_agent = {
            "deviceType": DEVICE_TYPE,
            "appVersion": APP_VERSION,
            "arch": ARCH,
            "buildNumber": BUILD_NUMBER,
            "osVersion": OS_VERSION,
            "locale": "ru",
            "deviceLocale": "ru",
            "deviceName": "Python MaxAPI Client",
            "screen": "1080x1920",
            "timezone": "Europe/Moscow",
        }

        params = {
            "userAgent": user_agent,
            "deviceId": self._session.device_id,
            "clientSessionId": self._session.client_session_id,
        }

        pkt = Packet(opcode=OpCode.SESSION_INIT, params=params)
        response = await self._conn.send(pkt)

        if response and response.params:
            proxy = response.params.get("proxy")
            if proxy and proxy != self._conn.host:
                logger.info("Получен proxy-хост: %s (переподключение)", proxy)
                self._session.proxy_host = proxy
                self._session.save()
                # Переподключаемся к proxy
                await self._conn.reconnect(host=proxy)
                # Повторяем SESSION_INIT на новом хосте
                response = await self._conn.send(pkt)

            logger.info("SESSION_INIT: %s", response.params)

        return response.params if response else {}

    # ── Авторизация (Телефон + SMS) ─────────────────

    async def send_code(self, phone: str) -> "SentCode":
        """
        Отправляет запрос на SMS-код (AUTH_REQUEST, opcode 17).

        Аналог dg0.java: bvb(gjc.l, 17) + phone + type=START_AUTH.

        Args:
            phone: Номер телефона ("+79001234567").

        Returns:
            SentCode с информацией о коде.
        """
        if not self.is_connected:
            raise ConnectionError("Не подключено. Вызовите connect() сначала.")

        self._session.phone = phone

        params = {
            "phone": phone,
            "type": "START_AUTH",
        }

        pkt = Packet(opcode=OpCode.AUTH_REQUEST, params=params)
        response = await self._conn.send(pkt)

        if not response:
            raise AuthError("Нет ответа на AUTH_REQUEST")

        # Проверяем ошибки
        error = response.params.get("error") or response.params.get("errorCode")
        if error:
            raise AuthError(f"AUTH_REQUEST error: {response.params}")

        # Сохраняем verify_token и code_length из ответа (cg0.java)
        self._session._verify_token = response.params.get("token", "")
        self._session._code_length = response.params.get("codeLength", 6)

        logger.info(
            "SMS-код отправлен на %s (длина кода: %d)",
            phone, self._session._code_length
        )

        return SentCode(
            phone=phone,
            verify_token=self._session._verify_token,
            code_length=self._session._code_length,
            alt_action_duration=response.params.get("altActionDuration", 0),
            request_max_duration=response.params.get("requestMaxDuration", 0),
            request_count_left=response.params.get("requestCountLeft", 0),
        )

    async def resend_code(self) -> "SentCode":
        """
        Повторная отправка SMS-кода (AUTH_REQUEST с type=RESEND).
        """
        if not self._session.phone:
            raise AuthError("Сначала вызовите send_code()")

        params = {
            "phone": self._session.phone,
            "type": "RESEND",
        }

        pkt = Packet(opcode=OpCode.AUTH_REQUEST, params=params)
        response = await self._conn.send(pkt)

        if not response:
            raise AuthError("Нет ответа на RESEND")

        self._session._verify_token = response.params.get("token", self._session._verify_token)
        self._session._code_length = response.params.get("codeLength", self._session._code_length)

        return SentCode(
            phone=self._session.phone,
            verify_token=self._session._verify_token,
            code_length=self._session._code_length,
        )

    async def sign_in(self, code: str) -> "AuthResult":
        """
        Подтверждает SMS-код и выполняет логин (AUTH + LOGIN).

        Аналог:
          1) qf0.a(): AUTH (opcode 18) с token + verifyCode + authTokenType=CHECK_CODE
          2) t99: LOGIN (opcode 19) с token из ответа AUTH

        Args:
            code: SMS-код.

        Returns:
            AuthResult с результатом авторизации.
        """
        if not self._session._verify_token:
            raise AuthError("Сначала вызовите send_code()")

        # Шаг 1: AUTH (opcode 18) — проверка SMS-кода
        auth_params = {
            "token": self._session._verify_token,
            "verifyCode": code,
            "authTokenType": "CHECK_CODE",
        }

        pkt = Packet(opcode=OpCode.AUTH, params=auth_params)
        auth_response = await self._conn.send(pkt)

        if not auth_response:
            raise AuthError("Нет ответа на AUTH (проверка кода)")

        error = auth_response.params.get("error") or auth_response.params.get("errorCode")
        if error:
            raise AuthError(f"Неверный код или ошибка AUTH: {auth_response.params}")

        logger.info("AUTH ответ: %s", auth_response.params)

        # Определяем тип ответа (f74.n())
        # Реальная структура: {"tokenAttrs": {"LOGIN": {"token": "..."}}, "profile": {...}}
        # Или плоская: {"LOGIN": "token_value"}
        tokens = auth_response.params

        # Извлекаем LOGIN-токен (вложенная или плоская структура)
        token_attrs = tokens.get("tokenAttrs", {})
        login_data = token_attrs.get("LOGIN") or {}
        login_token = login_data.get("token") if isinstance(login_data, dict) else login_data
        # Фоллбэк на плоскую структуру
        if not login_token:
            login_token = tokens.get("LOGIN")

        register_data = token_attrs.get("REGISTER") or {}
        register_token = register_data.get("token") if isinstance(register_data, dict) else register_data
        if not register_token:
            register_token = tokens.get("REGISTER")

        # Сохраняем профиль если пришёл
        profile = tokens.get("profile")

        if login_token:
            # Шаг 2: LOGIN (opcode 19) — вход существующего
            return await self._do_login(login_token)
        elif register_token:
            # Пользователь не зарегистрирован, нужна регистрация
            return AuthResult(
                success=False,
                needs_registration=True,
                register_token=register_token,
                params=auth_response.params,
            )
        else:
            # Возможно 2FA или другой ответ
            return AuthResult(
                success=False,
                needs_2fa=bool(tokens.get("2fa") or tokens.get("sxf")),
                params=auth_response.params,
            )

    async def sign_up(self, first_name: str, last_name: str = "", register_token: str = None) -> "AuthResult":
        """
        Регистрация нового пользователя (AUTH_CONFIRM, opcode 23).

        Аналог gf0.java: bvb(gjc.r, 11) с token + tokenType=REGISTER + firstName.

        Args:
            first_name: Имя.
            last_name: Фамилия (необязательно).
            register_token: Токен от sign_in() (если не передан, используется последний).

        Returns:
            AuthResult.
        """
        token = register_token or self._session._verify_token

        params = {
            "token": token,
            "tokenType": "REGISTER",
            "firstName": first_name,
        }
        if last_name:
            params["lastName"] = last_name

        pkt = Packet(opcode=OpCode.AUTH_CONFIRM, params=params)
        response = await self._conn.send(pkt)

        if not response:
            raise AuthError("Нет ответа на AUTH_CONFIRM (регистрация)")

        error = response.params.get("error")
        if error:
            raise AuthError(f"Ошибка регистрации: {response.params}")

        # После регистрации Login
        login_token = response.params.get("LOGIN") or response.params.get("token")
        if login_token:
            return await self._do_login(login_token)

        return AuthResult(success=False, params=response.params)

    async def _do_login(self, token: str) -> "AuthResult":
        """
        Выполняет LOGIN (opcode 19) с полученным токеном.
        Аналог t99.java: super(gjc.n) + token + interactive + sync params.
        """
        login_params = {
            "token": token,
            "interactive": True,
        }

        pkt = Packet(opcode=OpCode.LOGIN, params=login_params)
        response = await self._conn.send(pkt, timeout=60.0)

        if not response:
            raise AuthError("Нет ответа на LOGIN")

        error = response.params.get("error") or response.params.get("errorCode")
        if error:
            raise AuthError(f"Ошибка LOGIN: {response.params}")

        # Сохраняем auth_token
        auth_token = response.params.get("auth_token", token)
        self._session.auth_token = auth_token

        # ── Кэшируем всё что пришло в LOGIN ──────────────────────────────
        data = response.params
        self._login_data = data

        # Профиль пользователя
        profile_raw = data.get("profile", {})
        contact = profile_raw.get("contact", {})
        self._profile = self._parse_contact(
            contact,
            profile_options=profile_raw.get("profileOptions", [])
        )

        # UID
        uid = contact.get("id", 0)
        if uid:
            self._session.uid = int(uid)

        # Чаты, контакты, присутствие, конфиг
        self._chats = data.get("chats", [])
        self._contacts = data.get("contacts", [])
        self._presence = data.get("presence", {})
        self._config = data.get("config", {})
        self._chat_marker = data.get("chatMarker", 0)

        # Новый токен если пришёл
        new_token = data.get("token")
        if new_token:
            self._session.auth_token = new_token
            auth_token = new_token

        self._session.save()
        self._logged_in = True

        logger.info("Успешный вход! UID=%s name=%s chats=%d",
                    self._session.uid, self._profile.get("name"), len(self._chats))

        # Переавторизовываем OK API сессию с auth_token
        try:
            await self._anonym_login(auth_token=auth_token)
        except Exception as e:
            logger.warning("Не удалось обновить OK API сессию (auth.anonymLogin): %s", e)

        return AuthResult(
            success=True,
            uid=self._session.uid,
            auth_token=auth_token,
            params=data,
        )

    async def login_with_token(self, auth_token: str) -> "AuthResult":
        """
        Быстрый вход с уже имеющимся auth_token.
        Пропускает send_code/sign_in — сразу LOGIN.
        """
        self._session.auth_token = auth_token
        return await self._do_login(auth_token)

    # ── API-методы (чаты, сообщения) ────────────────

    async def _send_command(self, opcode: int, params: dict = None, timeout: float = 30.0) -> dict:
        """Отправляет команду и возвращает ответ."""
        if not self.is_connected:
            raise ConnectionError("Не подключено")

        pkt = Packet(opcode=opcode, params=params or {})
        response = await self._conn.send(pkt, timeout=timeout)
        return response.params if response else {}

    def get_profile(self) -> Dict[str, Any]:
        """
        Возвращает профиль текущего пользователя из кэша (без сетевого запроса).

        Returns:
            dict с полями: id, phone, name, first_name, last_name, country, options и др.
        """
        return self._profile

    async def fetch_profile(self, user_id: int = None) -> Dict[str, Any]:
        """
        Запрашивает свежий профиль пользователя с сервера (PROFILE, opcode 16).

        Правильный wire-параметр — "userId" (не "uid"!).
        Возвращает сырой dict из поля "profile.contact".

        Args:
            user_id: UID пользователя. По умолчанию — текущий пользователь.

        Returns:
            dict с полями: id, phone, names, options, accountStatus, country, updateTime и др.

        Raises:
            ConnectionError: если нет подключения.
            RuntimeError: если сервер вернул ошибку.
        """
        uid = user_id or self._session.uid
        result = await self._send_command(OpCode.PROFILE, {"userId": uid})

        error = result.get("error")
        if error:
            raise RuntimeError(f"PROFILE error: {result.get('message', error)}")

        # Разбираем вложенную структуру profile.contact
        raw = result.get("profile", result)
        contact = raw.get("contact", raw)

        # Обновляем кэш если запрашивали себя
        if not user_id or user_id == self._session.uid:
            self._profile = self._parse_contact(contact)

        return contact

    def _parse_contact(self, contact: dict, profile_options: list = None) -> dict:
        """Парсит объект contact в плоский профиль (как при LOGIN)."""
        profile = {
            "id": contact.get("id", 0),
            "phone": contact.get("phone", ""),
            "first_name": "",
            "last_name": "",
            "name": "",
            "options": contact.get("options", []),
            "country": contact.get("country", ""),
            "account_status": contact.get("accountStatus", 0),
            "update_time": contact.get("updateTime", 0),
            "profile_options": profile_options or [],
        }
        for name_entry in contact.get("names", []):
            if name_entry.get("type") == "ONEME" or not profile["first_name"]:
                profile["first_name"] = name_entry.get("firstName", "")
                profile["last_name"] = name_entry.get("lastName", "")
                profile["name"] = name_entry.get("name", "")
        return profile

    async def get_chats(self) -> List[Dict]:
        """
        Возвращает полный список чатов из кэша LOGIN.

        Чаты приходят от сервера при входе в аккаунт (opcode LOGIN). 
        Для получения обновлений с момента входа — используйте poll_chats().

        Returns:
            Список объектов чатов (snapshot при логине).
        """
        return self._chats

    async def poll_chats(self, count: int = 50) -> List[Dict]:
        """
        Delta-poll: запрашивает чаты, изменившиеся с момента последнего запроса.

        Использует CHATS_LIST (opcode 53) с текущим marker.
        Сервер возвращает только новые/изменённые чаты с момента входа.
        Обновляет внутренний кэш и marker.

        Протокол:
          - При логине сервер выдаёт снапшот и marker=X.
          - Каждый poll_chats() отдаёт delta с marker=X и возвращает новый marker.
          - Изменённые чаты мёрджатся в кэш _chats.

        Args:
            count: Максимум чатов в ответе.

        Returns:
            Список изменившихся чатов (может быть пустым если нет новых).
        """
        result = await self._send_command(OpCode.CHATS_LIST, {
            "count": count,
            "marker": self._chat_marker,
        })
        delta = result.get("chats", [])
        new_marker = result.get("marker", self._chat_marker)
        if delta:
            # Мёрдж: обновляем существующие чаты, добавляем новые
            existing = {c.get("id"): i for i, c in enumerate(self._chats)}
            for chat in delta:
                cid = chat.get("id")
                if cid in existing:
                    self._chats[existing[cid]] = chat
                else:
                    self._chats.append(chat)
            self._chat_marker = new_marker
        return delta

    async def get_chat_history(self, chat_id: int, count: int = 20, from_msg: int = None) -> dict:
        """
        Получает историю сообщений чата (CHAT_HISTORY, opcode 49).

        Проматывает backward=count сообщений назад от from_msg.
        По умолчанию from_msg — текущее время в миллисекундах (последние сообщения).

        Args:
            chat_id: ID чата (целое число).
            count: Кол-во сообщений (backward).
            from_msg: Временная метка в мс для пагинации; 0 = текущее время.
        """
        import time
        params: dict = {
            "chatId": int(chat_id),
            "from": int(from_msg) if from_msg else int(time.time() * 1000),
            "backward": count,
            "forward": 0,
            "getMessages": True,
            "getChat": False,
            "itemType": "REGULAR",
            "interactive": True,
        }
        return await self._send_command(OpCode.CHAT_HISTORY, params)

    async def send_message(
        self,
        chat_id: int,
        text: "str | FormattedText",  # noqa: F821
        reply_to: int = None,
        attaches: list = None,
        elements: list = None,
    ) -> dict:
        """
        Отправляет текстовое сообщение или сообщение с вложениями (MSG_SEND, opcode 64).

        Формат: chatId + message = {cid, text, elements, attaches, (link с replyTo)}.

        Args:
            chat_id: ID чата (int).
            text: Текст сообщения (str) или FormattedText с форматированием.
            reply_to: ID сообщения для ответа (int).
            attaches: Список вложений (list of dict).
            elements: Форматирование текста (list of dict). Если text — FormattedText,
                      elements берутся из него автоматически.
        """
        from maxapi.formatting import FormattedText

        # Если передан FormattedText — извлекаем text и elements
        if isinstance(text, FormattedText):
            elements = elements or text.elements
            text = text.text

        message: dict = {
            "cid": int(time.time() * 1000),  # уникальный client-side ID для дедупликации
            "text": text,
            "detectShare": False,
            "isLive": False,
        }
        if reply_to:
            message["link"] = {"type": "REPLY", "messageId": int(reply_to)}
        if attaches:
            message["attaches"] = attaches
        if elements:
            message["elements"] = elements
        params = {
            "chatId": int(chat_id),
            "message": message,
        }
        return await self._send_command(OpCode.MSG_SEND, params)

    async def forward_message(self, to_chat_id: int, from_chat_id: int, message_id: int, text: str = "") -> dict:
        """
        Пересылает сообщение в другой (или тот же) чат (MSG_SEND с link.type=FORWARD).

        Args:
            to_chat_id: ID чата-получателя.
            from_chat_id: ID чата-источника.
            message_id: ID пересылаемого сообщения.
            text: Дополнительный текст (необязательно).

        Returns:
            Ответ сервера на MSG_SEND.
        """
        message: dict = {
            "cid": int(time.time() * 1000),
            "text": text,
            "detectShare": False,
            "isLive": False,
            "link": {
                "type": "FORWARD",
                "messageId": int(message_id),
                "chatId": int(from_chat_id),
            },
        }
        params = {
            "chatId": int(to_chat_id),
            "message": message,
        }
        return await self._send_command(OpCode.MSG_SEND, params)

    async def upload_photo(self, chat_id: int, image_data: bytes) -> str:
        """
        Загружает фотографию и возвращает её токен для вставки в сообщение.

        Двухшаговый процесс:
          1. PHOTO_UPLOAD (opcode 80) → получаем одноразовый URL
          2. HTTP multipart POST → получаем токен фото

        Args:
            chat_id: ID чата, для которого загружается фото.
            image_data: Байты JPEG/PNG изображения.

        Returns:
            Токен фото (str), передаётся в attaches при send_message.
        """
        from urllib.parse import urlparse, parse_qs

        # 1. Получить URL загрузки
        r = await self._send_command(OpCode.PHOTO_UPLOAD, {"chatId": int(chat_id), "count": 1})
        upload_url = r.get("url")
        if not upload_url:
            raise RuntimeError(f"PHOTO_UPLOAD вернул неожиданный ответ: {r}")

        # 2. Multipart upload
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", image_data, filename="photo.jpg", content_type="image/jpeg")
            async with session.post(upload_url, data=form) as resp:
                body = await resp.json()

        # Ответ: {"photos": {photoId: {"token": "..."}}}
        photos = body.get("photos", {})
        if not photos:
            raise RuntimeError(f"Ответ сервера при загрузке фото не содержит photos: {body}")
        first_key = next(iter(photos))
        token = photos[first_key]["token"]
        return token

    async def send_photo(
        self,
        chat_id: int,
        image: "str | bytes",
        caption: str = "",
        reply_to: int = None,
    ) -> dict:
        """
        Отправляет фотографию в чат.

        Args:
            chat_id: ID чата.
            image: Путь к файлу (str) или байты изображения (bytes).
            caption: Подпись к фото (необязательно).
            reply_to: ID сообщения для ответа (необязательно).

        Returns:
            Ответ сервера на MSG_SEND.
        """
        if isinstance(image, str):
            with open(image, "rb") as f:
                image_data = f.read()
        else:
            image_data = image

        token = await self.upload_photo(int(chat_id), image_data)

        attaches = [{"_type": "PHOTO", "photoToken": token}]
        return await self.send_message(
            chat_id=chat_id,
            text=caption,
            reply_to=reply_to,
            attaches=attaches,
        )

    async def edit_message(self, chat_id: int, msg_id: int, text: str) -> dict:
        """Редактирует сообщение (MSG_EDIT, opcode 67)."""
        return await self._send_command(OpCode.MSG_EDIT, {
            "chatId": int(chat_id),
            "messageId": int(msg_id),
            "text": text,
        })

    async def delete_messages(self, chat_id: int, msg_ids: List[int]) -> dict:
        """Удаляет сообщения (MSG_DELETE, opcode 66)."""
        return await self._send_command(OpCode.MSG_DELETE, {
            "chatId": chat_id,
            "messageIds": msg_ids,
        })

    async def get_chat_info(self, chat_id: str) -> dict:
        """Получает информацию о чате (CHAT_INFO, opcode 48)."""
        return await self._send_command(OpCode.CHAT_INFO, {"chatId": chat_id})

    async def create_chat(self, title: str, member_ids: List[str] = None) -> dict:
        """Создаёт новый чат (CHAT_CREATE, opcode 63)."""
        params = {"title": title}
        if member_ids:
            params["memberIds"] = member_ids
        return await self._send_command(OpCode.CHAT_CREATE, params)

    async def get_contacts(self, status: str = "BLOCKED") -> List[Dict]:
        """
        Возвращает список контактов по статусу.

        Сервер поддерживает только два статуса: "BLOCKED" и "REMOVED".
        Обычные (активные) контакты загружаются через LOGIN и хранятся в cached_contacts.

        Args:
            status: "BLOCKED" — заблокированные, "REMOVED" — удалённые.

        Returns:
            Список объектов контактов.
        """
        result = await self._send_command(OpCode.CONTACT_LIST, {
            "status": status,
            "count": 40,
        })
        return result.get("contacts", result if isinstance(result, list) else [])

    async def search_contacts(self, query: str) -> dict:
        """Поиск контактов (CONTACT_SEARCH, opcode 37)."""
        return await self._send_command(OpCode.CONTACT_SEARCH, {"query": query})

    async def search(self, query: str) -> Dict[str, Any]:
        """
        Глобальный поиск — аналог get_entity() в Telethon.

        Ищет одновременно:
          - в кэше чатов (по названию/имени, без сети)
          - контакты на сервере (CONTACT_SEARCH, opcode 37)
          - публичные чаты/каналы (PUBLIC_SEARCH, opcode 60)

        Args:
            query: Строка поиска (имя, ник, часть названия).

        Returns:
            dict с ключами:
              ``chats``    — совпадения из кэша LOGIN
              ``contacts`` — результаты CONTACT_SEARCH
              ``public``   — результаты PUBLIC_SEARCH
        """
        q = query.lower().strip()

        # 1. Локальный поиск по кэшу чатов
        matched_chats = []
        for chat in self._chats:
            title = str(chat.get("name") or chat.get("title") or "").lower()
            cid   = str(chat.get("id", ""))
            if q in title or q == cid:
                matched_chats.append(chat)

        # 2. Серверный поиск контактов и публичных чатов (параллельно)
        contacts_result: Dict = {}
        public_result:   Dict = {}
        try:
            contacts_result, public_result = await asyncio.gather(
                self._send_command(OpCode.CONTACT_SEARCH, {"query": query}),
                self._send_command(OpCode.PUBLIC_SEARCH,  {"query": query, "count": 20}),
                return_exceptions=True,
            )
        except Exception:
            pass

        if isinstance(contacts_result, Exception):
            contacts_result = {}
        if isinstance(public_result,   Exception):
            public_result   = {}

        return {
            "chats":    matched_chats,
            "contacts": contacts_result.get("contacts", []) if isinstance(contacts_result, dict) else [],
            "public":   public_result.get("chats",    []) if isinstance(public_result,   dict) else [],
        }

    async def send_typing(self, chat_id: str) -> None:
        """Отправляет уведомление о наборе (MSG_TYPING, opcode 65)."""
        pkt = Packet(opcode=OpCode.MSG_TYPING, params={"chatId": chat_id})
        await self._conn.send(pkt, wait_response=False)

    async def mark_read(self, chat_id: str, msg_id: str) -> dict:
        """Помечает сообщения как прочитанные (CHAT_MARK, opcode 50)."""
        return await self._send_command(OpCode.CHAT_MARK, {
            "chatId": chat_id,
            "messageId": msg_id,
        })

    async def get_chat_members(self, chat_id: str, count: int = 100) -> dict:
        """Получает список участников чата (CHAT_MEMBERS, opcode 59)."""
        return await self._send_command(OpCode.CHAT_MEMBERS, {
            "chatId": chat_id,
            "count": count,
        })

    async def leave_chat(self, chat_id: str) -> dict:
        """Покидает чат (CHAT_LEAVE, opcode 58)."""
        return await self._send_command(OpCode.CHAT_LEAVE, {"chatId": chat_id})

    async def join_chat(self, link: str) -> dict:
        """Присоединяется к чату по ссылке (CHAT_JOIN, opcode 57)."""
        return await self._send_command(OpCode.CHAT_JOIN, {"link": link})

    async def get_link_info(self, url: str) -> dict:
        """Получает превью ссылки (LINK_INFO, opcode 89)."""
        return await self._send_command(OpCode.LINK_INFO, {"url": url})

    async def react(self, chat_id: int, msg_id: int, reaction: str) -> None:
        """Ставит реакцию (MSG_REACTION, opcode 178). Fire-and-forget."""
        pkt = Packet(opcode=OpCode.MSG_REACTION, params={
            "chatId": int(chat_id),
            "messageId": int(msg_id),
            "reaction": {"reactionType": "EMOJI", "id": reaction},
        })
        await self._conn.send(pkt, wait_response=False)

    async def cancel_reaction(self, chat_id: int, msg_id: int) -> None:
        """Убирает реакцию (MSG_CANCEL_REACTION, opcode 179). Fire-and-forget."""
        pkt = Packet(opcode=OpCode.MSG_CANCEL_REACTION, params={
            "chatId": int(chat_id),
            "messageId": int(msg_id),
        })
        await self._conn.send(pkt, wait_response=False)

    async def send_sticker(self, chat_id: int, sticker_id: int) -> dict:
        """Отправляет стикер в чат.

        Args:
            chat_id: ID чата.
            sticker_id: ID стикера.

        Returns:
            dict: Ответ сервера с полем 'message'.
        """
        return await self.send_message(
            chat_id, "",
            attaches=[{"_type": "STICKER", "stickerId": int(sticker_id)}],
        )

    async def send_ping(self) -> dict:
        """Отправляет PING (opcode 1)."""
        return await self._send_command(OpCode.PING)


# ── Вспомогательные классы ──────────────────────


class SentCode:
    """Результат send_code() — информация об отправленном SMS-коде."""

    def __init__(
        self,
        phone: str = "",
        verify_token: str = "",
        code_length: int = 6,
        alt_action_duration: int = 0,
        request_max_duration: int = 0,
        request_count_left: int = 0,
    ):
        self.phone = phone
        self.verify_token = verify_token
        self.code_length = code_length
        self.alt_action_duration = alt_action_duration
        self.request_max_duration = request_max_duration
        self.request_count_left = request_count_left

    def __repr__(self) -> str:
        return (
            f"SentCode(phone={self.phone!r}, code_length={self.code_length}, "
            f"requests_left={self.request_count_left})"
        )


class AuthResult:
    """Результат sign_in() / sign_up() / login_with_token()."""

    def __init__(
        self,
        success: bool = False,
        uid: int = 0,
        auth_token: str = "",
        needs_registration: bool = False,
        needs_2fa: bool = False,
        register_token: str = "",
        params: dict = None,
    ):
        self.success = success
        self.uid = uid
        self.auth_token = auth_token
        self.needs_registration = needs_registration
        self.needs_2fa = needs_2fa
        self.register_token = register_token
        self.params = params or {}

    def __repr__(self) -> str:
        if self.success:
            return f"AuthResult(success=True, uid={self.uid})"
        if self.needs_registration:
            return "AuthResult(needs_registration=True)"
        if self.needs_2fa:
            return "AuthResult(needs_2fa=True)"
        return f"AuthResult(success=False, params={self.params})"

    def __bool__(self) -> bool:
        return self.success


class AuthError(Exception):
    """Ошибка авторизации."""
    pass
