"""
Константы протокола MAX мессенджера.
Реверс-инженеринг APK v26.9.0 (build 6637).
"""

# ── OK API ──────────────────────────────────────
API_URL = "https://api.ok.ru/api"
APP_KEY = "CMBGJFMGDIHBABABA"  # application_key из gq.java

# ── TCP/SSL сервер ────────────────────────────────
DEFAULT_HOST = "api.oneme.ru"  # из iw7.java, nr3.java
DEFAULT_PORT = 443              # SSL

# Альтернативные хосты (из iw7.java)
ALT_HOSTS = [
    "api.oneme.ru",
    "api-test.oneme.ru",
    "api-tg.oneme.ru",
    "api-test2.oneme.ru",
]

# ── Формат бинарного пакета ────────────────────
PACKET_VERSION = 10           # hnc.a = 10
PACKET_HEADER_SIZE = 10       # ver(1) + cmd(1) + seq(2) + opcode(2) + length(4)
LZ4_THRESHOLD = 32            # сжатие если payload >= 32 байт

# ── Флаги команд (hnc.b) ──────────────────────
CMD_NORMAL = 0x00
CMD_PERSISTENT = 0x02

# ── OpCode'ы ─────────────────────────────────
# Источник: верифицированная таблица + gjc.java
class OpCode:
    """Все коды операций MAX мессенджера."""

    # ── Системные ──
    PING            = 1
    DEBUG           = 2
    RECONNECT       = 3
    LOG             = 5
    SESSION_INIT    = 6
    LOGOUT          = 20
    SYNC            = 21
    CONFIG          = 22

    # ── Авторизация (SMS / токен) ──
    PROFILE         = 16   # ⚠ вызывает дисконнект — не использовать
    AUTH_REQUEST    = 17   # отправить номер телефона
    AUTH            = 18   # ответ сервера (токен)
    LOGIN           = 19   # финальный логин → кэш чатов/профиля
    AUTH_CONFIRM    = 23   # подтвердить SMS-код

    AUTH_LOGIN_RESTORE_PASSWORD     = 101
    AUTH_2FA_DETAILS                = 104
    AUTH_VALIDATE_PASSWORD          = 107
    AUTH_VALIDATE_HINT              = 108
    AUTH_VERIFY_EMAIL               = 109
    AUTH_CHECK_EMAIL                = 110
    AUTH_SET_2FA                    = 111
    AUTH_CREATE_TRACK               = 112
    AUTH_CHECK_PASSWORD             = 113
    AUTH_LOGIN_CHECK_PASSWORD       = 115
    AUTH_LOGIN_PROFILE_DELETE       = 116

    # ── QR-авторизация ──
    AUTH_QR_REQUEST   = 288   # запросить QR-код (w)
    AUTH_QR_STATUS    = 289   # статус QR по trackId (w)
    AUTH_QR_APPROVE   = 290
    AUTH_QR_LOGIN     = 291   # вход по trackId после сканирования (w)

    # ── Ассеты ──
    PRESET_AVATARS     = 25
    ASSETS_GET         = 26
    ASSETS_UPDATE      = 27
    ASSETS_GET_BY_IDS  = 28
    ASSETS_ADD         = 29
    SEARCH_FEEDBACK    = 31
    ASSETS_REMOVE      = 259
    ASSETS_MOVE        = 260
    ASSETS_LIST_MODIFY = 261

    # ── Контакты ──
    CONTACT_INFO          = 32
    CONTACT_ADD           = 33
    CONTACT_UPDATE        = 34
    CONTACT_PRESENCE      = 35
    CONTACT_LIST          = 36
    CONTACT_SEARCH        = 37
    CONTACT_MUTUAL        = 38
    CONTACT_PHOTOS        = 39
    CONTACT_SORT          = 30
    CONTACT_VERIFY        = 42
    REMOVE_CONTACT_PHOTO  = 43
    SEARCH_FEEDBACK       = 31
    CONTACT_INFO_BY_PHONE = 46

    # ── Чаты ──
    CHAT_INFO            = 48
    CHAT_HISTORY         = 49
    CHAT_MARK            = 50
    CHAT_MEDIA           = 51
    CHAT_DELETE          = 52
    CHATS_LIST           = 53
    CHAT_CLEAR           = 54
    CHAT_UPDATE          = 55
    CHAT_CHECK_LINK      = 56
    CHAT_JOIN            = 57
    CHAT_LEAVE           = 58
    CHAT_MEMBERS         = 59
    PUBLIC_SEARCH        = 60
    CHAT_PERSONAL_CONFIG = 61
    CHAT_CREATE          = 63
    CHAT_SEARCH          = 68
    CHAT_SUBSCRIBE       = 75
    CHAT_MEMBERS_UPDATE  = 77
    CHAT_PIN_SET_VISIBILITY = 86
    CHAT_BOT_COMMANDS    = 144
    CHAT_HIDE            = 196
    CHAT_SEARCH_COMMON_PARTICIPANTS = 198
    CHAT_REACTIONS_SETTINGS_SET       = 257
    REACTIONS_SETTINGS_GET_BY_CHAT_ID = 258

    # ── Сообщения ──
    MSG_SEND              = 64
    MSG_TYPING            = 65
    MSG_DELETE            = 66
    MSG_EDIT              = 67
    MSG_SHARE_PREVIEW     = 70
    MSG_GET               = 71
    MSG_SEARCH_TOUCH      = 72
    MSG_SEARCH            = 73
    MSG_GET_STAT          = 74
    MSG_DELETE_RANGE      = 92
    CHAT_COMPLAIN         = 117
    MSG_SEND_CALLBACK     = 118
    SUSPEND_BOT           = 119
    GET_LAST_MENTIONS     = 127
    MSG_REACTION          = 178
    MSG_CANCEL_REACTION   = 179
    MSG_GET_REACTIONS     = 180
    MSG_GET_DETAILED_REACTIONS = 181
    STICKER_CREATE        = 193
    STICKER_SUGGEST       = 194
    VIDEO_CHAT_MEMBERS    = 195

    # ── Геолокация ──
    LOCATION_STOP     = 124
    LOCATION_SEND     = 125
    LOCATION_REQUEST  = 126

    # ── Медиа ──
    PHOTO_UPLOAD    = 80
    STICKER_UPLOAD  = 81
    VIDEO_UPLOAD    = 82
    VIDEO_PLAY      = 83
    VIDEO_CHAT_CREATE_JOIN_LINK = 84
    FILE_UPLOAD     = 87
    FILE_DOWNLOAD   = 88
    LINK_INFO       = 89

    # ── Видео-звонки ──
    VIDEO_CHAT_START        = 76
    VIDEO_CHAT_START_ACTIVE = 78
    VIDEO_CHAT_HISTORY      = 79

    # ── Сессии / безопасность ──
    SESSIONS_INFO       = 96
    SESSIONS_CLOSE      = 97
    PHONE_BIND_REQUEST  = 98
    PHONE_BIND_CONFIRM  = 99
    GET_INBOUND_CALLS   = 103
    EXTERNAL_CALLBACK   = 105
    OK_TOKEN            = 158

    # ── Уведомления (входящие пакеты от сервера) ──
    # Для регистрации: client.on(OpCode.NOTIF_MESSAGE, handler)
    NOTIF_MESSAGE         = 128
    NOTIF_TYPING          = 129
    NOTIF_MARK            = 130
    NOTIF_CONTACT         = 131
    NOTIF_PRESENCE        = 132
    NOTIF_CONFIG          = 134
    NOTIF_CHAT            = 135
    NOTIF_ATTACH          = 136
    NOTIF_CALL_START      = 137
    NOTIF_CONTACT_SORT    = 139
    NOTIF_MSG_DELETE_RANGE = 140
    NOTIF_MSG_DELETE      = 142
    NOTIF_CALLBACK_ANSWER = 143
    NOTIF_LOCATION        = 147
    NOTIF_LOCATION_REQUEST = 148
    NOTIF_ASSETS_UPDATE   = 150
    NOTIF_DRAFT           = 152
    NOTIF_DRAFT_DISCARD   = 153
    NOTIF_MSG_DELAYED     = 154
    NOTIF_MSG_REACTIONS_CHANGED = 155
    NOTIF_MSG_YOU_REACTED = 156
    NOTIF_PROFILE         = 159
    NOTIF_BANNERS         = 292

    # ── Разное ──
    BOT_INFO            = 145
    DRAFT_SAVE          = 176
    DRAFT_DISCARD       = 177
    COMPLAIN            = 161
    COMPLAIN_REASONS_GET = 162
    WEB_APP_INIT_DATA   = 160
    PROFILE_DELETE      = 199
    PROFILE_DELETE_TIME = 200

    # ── Папки ──
    FOLDERS_GET       = 272
    FOLDERS_GET_BY_ID = 273
    FOLDERS_UPDATE    = 274
    FOLDERS_REORDER   = 275
    FOLDERS_DELETE    = 276
    NOTIF_FOLDERS     = 277
