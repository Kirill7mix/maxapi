"""
Управление сессией MAX мессенджера.

Хранит:
  - device_id: ID устройства (генерируется один раз)
  - session_key / session_secret_key: от auth.anonymLogin (OK API)
  - auth_token: токен авторизации (после успешного LOGIN)
  - uid: ID пользователя
  - proxy_host: хост TCP-сервера (из SESSION_INIT)
"""

import json
import uuid
import os
import hashlib
import time
from typing import Optional


class Session:
    """
    Сессия MAX мессенджера (аналог Telethon StringSession / SQLiteSession).

    Автоматически сохраняется/загружается из JSON-файла.
    """

    def __init__(self, session_file: str = "max_session.json"):
        self.session_file = session_file

        # Генерируемые при первом запуске
        self.device_id: str = ""
        self.client_session_id: int = 0

        # От OK API auth.anonymLogin
        self.session_key: str = ""
        self.session_secret_key: str = ""
        self.api_server: str = "https://api.ok.ru/"

        # После авторизации
        self.auth_token: str = ""  # Токен для LOGIN
        self.uid: int = 0  # User ID

        # TCP сервер
        self.proxy_host: str = ""  # От SESSION_INIT

        # Телефон
        self.phone: str = ""

        # Временные (не сохраняются)
        self._verify_token: str = ""  # Токен из AUTH_REQUEST для ввода кода
        self._code_length: int = 0

        self._load()

    def _load(self) -> None:
        """Загружает сессию из файла."""
        if not os.path.exists(self.session_file):
            self._generate_device_id()
            return

        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.device_id = data.get("device_id", "")
            self.client_session_id = data.get("client_session_id", 0)
            self.session_key = data.get("session_key", "")
            self.session_secret_key = data.get("session_secret_key", "")
            self.api_server = data.get("api_server", "https://api.ok.ru/")
            self.auth_token = data.get("auth_token", "")
            self.uid = data.get("uid", 0)
            self.proxy_host = data.get("proxy_host", "")
            self.phone = data.get("phone", "")

            if not self.device_id:
                self._generate_device_id()

        except (json.JSONDecodeError, IOError):
            self._generate_device_id()

    def save(self) -> None:
        """Сохраняет сессию в файл."""
        data = {
            "device_id": self.device_id,
            "client_session_id": self.client_session_id,
            "session_key": self.session_key,
            "session_secret_key": self.session_secret_key,
            "api_server": self.api_server,
            "auth_token": self.auth_token,
            "uid": self.uid,
            "proxy_host": self.proxy_host,
            "phone": self.phone,
        }
        with open(self.session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _generate_device_id(self) -> None:
        """Генерирует device_id (UUID-подобный)."""
        self.device_id = str(uuid.uuid4())
        self.client_session_id = int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF

    @property
    def is_anonymous(self) -> bool:
        """Есть сессия OK API, но нет авторизации."""
        return bool(self.session_key) and not bool(self.auth_token)

    @property
    def is_authorized(self) -> bool:
        """Полностью авторизован (есть auth_token)."""
        return bool(self.auth_token)

    @property
    def has_session(self) -> bool:
        """Есть ли анонимная сессия OK API."""
        return bool(self.session_key)

    def clear(self) -> None:
        """Очищает все данные сессии."""
        self.session_key = ""
        self.session_secret_key = ""
        self.auth_token = ""
        self.uid = 0
        self.proxy_host = ""
        self.phone = ""
        self._verify_token = ""
        self._code_length = 0
        self.save()

    def __repr__(self) -> str:
        status = "authorized" if self.is_authorized else ("anonymous" if self.is_anonymous else "empty")
        return f"Session(status={status}, phone={self.phone!r}, uid={self.uid})"
