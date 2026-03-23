# maxapi — MAX Messenger Client API

Неофициальная Python-библиотека для работы с мессенджером **MAX** (ex-TamTam) от VK.

📖 **Документация**: https://Kirill7mix.github.io/maxapi/

---

## Установка

### Из GitHub (рекомендуется)

```bash
pip install git+https://github.com/Kirill7mix/maxapi.git
```

### Для разработки (локально)

```bash
git clone https://github.com/Kirill7mix/maxapi.git
cd maxapi
pip install -e .
```

---

## Быстрый старт

```python
import asyncio
from maxapi import MaxClient

async def main():
    async with MaxClient("my_session") as client:
        # Авторизация по номеру телефона
        await client.send_code("+79001234567")
        code = input("Введите код из SMS: ")
        result = await client.sign_in(code)

        if result.needs_registration:
            name = input("Введите имя: ")
            await client.sign_up(first_name=name, register_token=result.register_token)

        # Работа с API
        profile = client.get_profile()          # из кэша (sync)
        chats = await client.get_chats()         # из кэша LOGIN
        await client.send_message(chat_id=12345678, text="Привет!")
        await client.send_photo(chat_id=12345678, image="photo.jpg", caption="Подпись")

        # Форматированное сообщение
        from maxapi import FormattedText
        fmt = FormattedText().bold("Жирный").add(" и ").italic("курсив")
        await client.send_message(chat_id=12345678, text=fmt)

        # Пересылка сообщения
        await client.forward_message(from_chat_id=111, msg_id=222, to_chat_id=333)

asyncio.run(main())
```

---

## Юзербот (обработка событий)

> **Требуется готовая сессия.** Файл `my_session.json` должен уже существовать.
> Если его нет — сначала пройди авторизацию из раздела [Быстрый старт](#быстрый-старт).

```python
import asyncio
from maxapi import MaxClient
from maxapi.types import Message

client = MaxClient("my_session")  # загружает my_session.json

@client.on_message
async def on_message(msg: Message):
    if msg.is_outgoing:
        return
    print(f"[{msg.chat_id}] {msg.sender_name}: {msg.text}")
    await msg.reply("Привет!")  # цитирует исходное сообщение

asyncio.run(client.run())  # connect() + run_until_disconnected()
```

---

## Протокол

| Уровень     | Технология                                     |
|-------------|------------------------------------------------|
| HTTP API    | OK API (`api.ok.ru`), APP_KEY=`CMBGJFMGDIHBABABA` |
| Транспорт   | TCP/SSL → `api.oneme.ru:443`                   |
| Сериализация| MessagePack                                    |
| Сжатие      | LZ4 (payload ≥ 32 байт)                       |
| Пакеты      | 10-байт заголовок + payload                    |

### Формат пакета (10 байт заголовок)

```
version  (1 байт)  = 10
cmd      (1 байт)  = тип команды (0=normal, 2=persistent)
seq      (2 байта)  = порядковый номер (big-endian)
opcode   (2 байта)  = код операции (big-endian)
length   (4 байта)  = [compression_ratio << 24 | payload_length]
```

### Поток авторизации

```
1. HTTP: auth.anonymLogin          → session_key + session_secret_key
2. TCP:  SESSION_INIT    (op=6)    → конфигурация сервера
3. TCP:  AUTH_REQUEST     (op=17)   → SMS-код отправлен (verifyToken)
4. TCP:  AUTH             (op=18)   → проверка кода (LOGIN/REGISTER токен)
5. TCP:  LOGIN            (op=19)   → вход в аккаунт
```

---

## API-методы

| Метод                | OpCode  | Описание                     |
|----------------------|---------|------------------------------|
| `get_profile()`      | —       | Профиль из кэша (sync)       |
| `fetch_profile()`    | 16      | Свежий профиль с сервера     |
| `get_chats()`        | —       | Чаты из кэша LOGIN (async)   |
| `poll_chats()`       | 53      | Delta-poll изменённых чатов   |
| `get_chat_history()` | 49      | История сообщений чата       |
| `send_message()`     | 64      | Отправка сообщения (+ FormattedText) |
| `forward_message()`  | 64      | Пересылка сообщения          |
| `send_photo()`       | 64+80   | Отправка фото в чат          |
| `upload_photo()`     | 80/HTTP | Загрузка фото, возврат token |
| `edit_message()`     | 67      | Редактирование сообщения     |
| `delete_messages()`  | 66      | Удаление сообщений, включая delete-for-all |
| `get_chat_info()`    | 48      | Информация о чате            |
| `create_chat()`      | 63      | Создание чата                |
| `get_contacts()`     | 36      | Список контактов             |
| `search_contacts()`  | 37      | Поиск контактов              |
| `send_typing()`      | 65      | Уведомление "печатает..."    |
| `mark_read()`        | 50      | Прочитано                    |
| `get_chat_members()` | 59      | Участники чата               |
| `join_chat()`        | 57      | Вступить в чат по ссылке     |
| `leave_chat()`       | 58      | Покинуть чат                 |
| `react()`            | 178     | Поставить реакцию            |
| `send_ping()`        | 1       | Ping/keepalive               |

---

## Структура библиотеки

```
maxapi/
├── __init__.py       # Экспорт: MaxClient, Session, Packet, OpCode, FormattedText
├── client.py         # Главный клиент (авторизация + API)
├── constants.py      # Опкоды и константы протокола
├── formatting.py     # FormattedText — форматирование сообщений
├── protocol.py       # Кодирование/декодирование пакетов (MessagePack + LZ4)
├── session.py        # Хранение сессии (JSON)
├── transport.py      # TCP/SSL соединение + чтение/запись пакетов
└── types.py          # Типы данных: Message, TypingEvent и др.

docs/                 # HTML-документация (GitHub Pages)
├── index.html
├── quickstart.html
├── messages.html
├── chats.html
├── events.html
├── auth.html
├── contacts.html
├── opcodes.html
└── style.css
```

---

## Требования

- Python 3.10+
- aiohttp ≥ 3.9
- msgpack ≥ 1.0
- lz4 ≥ 4.0

---

## Disclaimer

Эта библиотека создана исключительно в образовательных целях путём reverse engineering.  
Используйте на свой страх и риск. Автор не несёт ответственности за возможные последствия.
