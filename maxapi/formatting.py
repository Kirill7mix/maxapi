"""
Форматирование текста для MAX мессенджера.

Сервер принимает массив ``elements`` — каждый описывает диапазон символов
в ``text`` и тип форматирования (STRONG, EMPHASIZED, UNDERLINE и т.д.).

Модуль предоставляет удобный билдер ``FormattedText`` для сборки текста
с форматированием::

    from maxapi.formatting import FormattedText

    fmt = (FormattedText()
        .add("Привет, ")
        .bold("мир")
        .add("! ")
        .italic("Это курсив")
        .add(" и ")
        .link("ссылка", "https://example.com")
    )
    await client.send_message(chat_id, fmt)

Типы форматирования (из протокола MAX, подтверждено на боевом сервере):
  STRONG        — жирный
  EMPHASIZED    — курсив
  UNDERLINE     — подчёркнутый
  STRIKETHROUGH — зачёркнутый
  HEADING       — заголовок
  MONOSPACED    — моноширинный (код)
  QUOTE         — цитата-блок
  LINK          — гиперссылка (с атрибутом url)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional


class FormattedText:
    """
    Билдер для текста с форматированием.

    Собирает ``text`` (str) и ``elements`` (list[dict]) для передачи
    в ``send_message()``.  Поддерживает цепочечные вызовы (chaining).

    Пример::

        fmt = (FormattedText()
            .bold("Жирный")
            .add(" обычный ")
            .italic("курсив")
        )
        await client.send_message(chat_id, fmt)
    """

    __slots__ = ("_text", "_elements")

    def __init__(self, text: str = ""):
        self._text: str = text
        self._elements: List[Dict[str, Any]] = []

    # ── Простой текст без форматирования ───────────

    def add(self, text: str) -> FormattedText:
        """Добавляет обычный текст (без форматирования)."""
        self._text += text
        return self

    # ── Форматирование ─────────────────────────────

    def bold(self, text: str) -> FormattedText:
        """Добавляет **жирный** текст (STRONG)."""
        return self._styled(text, "STRONG")

    def italic(self, text: str) -> FormattedText:
        """Добавляет *курсивный* текст (EMPHASIZED)."""
        return self._styled(text, "EMPHASIZED")

    def underline(self, text: str) -> FormattedText:
        """Добавляет подчёркнутый текст (UNDERLINE)."""
        return self._styled(text, "UNDERLINE")

    def strike(self, text: str) -> FormattedText:
        """Добавляет ~~зачёркнутый~~ текст (STRIKETHROUGH)."""
        return self._styled(text, "STRIKETHROUGH")

    def heading(self, text: str) -> FormattedText:
        """Добавляет заголовок (HEADING)."""
        return self._styled(text, "HEADING")

    def code(self, text: str) -> FormattedText:
        """Добавляет `моноширинный` текст (MONOSPACED)."""
        return self._styled(text, "MONOSPACED")

    def quote(self, text: str) -> FormattedText:
        """Добавляет цитату-блок (QUOTE)."""
        return self._styled(text, "QUOTE")

    def link(self, text: str, url: str) -> FormattedText:
        """Добавляет гиперссылку (LINK)."""
        offset = len(self._text)
        element: Dict[str, Any] = {
            "type": "LINK",
            "length": len(text),
            "attributes": {"url": url},
        }
        if offset > 0:
            element["from"] = offset
        self._elements.append(element)
        self._text += text
        return self

    # ── Внутренние методы ──────────────────────────

    def _styled(self, text: str, element_type: str) -> FormattedText:
        """Добавляет текст с указанным типом форматирования."""
        offset = len(self._text)
        element: Dict[str, Any] = {
            "type": element_type,
            "length": len(text),
        }
        if offset > 0:
            element["from"] = offset
        self._elements.append(element)
        self._text += text
        return self

    # ── Доступ к результатам ───────────────────────

    @property
    def text(self) -> str:
        """Собранный текст."""
        return self._text

    @property
    def elements(self) -> Optional[List[Dict[str, Any]]]:
        """Список элементов форматирования (None если пусто)."""
        return self._elements if self._elements else None

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"FormattedText({self._text!r}, elements={len(self._elements)})"

    def __len__(self) -> int:
        return len(self._text)

    def __bool__(self) -> bool:
        return bool(self._text)
