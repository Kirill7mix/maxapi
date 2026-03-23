"""
test_all_methods.py — Полный аудит всех методов maxapi.

Тестирует каждый метод клиента и выводит итоговую таблицу pass/fail.

Чат: 63530148 (выданы полные полномочия)
Сессия: kiril_session
"""

import asyncio
import json
import logging
import struct
import sys
import zlib

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from maxapi.client import MaxClient

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

CHAT_ID    = 63530148
SESSION    = "kiril_session"
MY_UID     = 61091213
STICKER_ID = 1083866299   # статический стикер, подтверждён рабочим


# ── PNG-генератор ────────────────────────────────────────────────────────────

def _png_chunk(name: bytes, data: bytes) -> bytes:
    payload = name + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    )


def make_tiny_png(width: int = 10, height: int = 10) -> bytes:
    """Создаёт минимальный валидный PNG (белые пиксели, RGB 8-bit)."""
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xFF\xFF\xFF" * width   # filter byte + pixels
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


TINY_PNG = make_tiny_png()


# ───────────────────────────── helpers ──────────────────────────────────────

results: list[tuple[str, bool, str]] = []


def rec(name: str, passed: bool, detail: str = "") -> None:
    """Записывает результат теста и выводит строку."""
    results.append((name, passed, detail))
    icon = "✅ PASS" if passed else "❌ FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon}  {name}{suffix}")


def msg_id(r: dict) -> int | None:
    """Извлекает msgId из ответа send_message / forward_message."""
    if not isinstance(r, dict):
        return None
    msg = r.get("message")
    if not isinstance(msg, dict):
        return None
    return msg.get("msgId") or msg.get("id")


async def ensure_connected(client: MaxClient) -> None:
    """Восстанавливает соединение, если оно было разорвано."""
    if not client.is_connected:
        print("  ↻ Переподключение...")
        await client.disconnect()
        await client.connect()


# ─────────────────────────────── main ───────────────────────────────────────

async def run():
    async with MaxClient(SESSION) as client:
        sent_id   = None   # msgId первого send_message — нужен многим тестам
        sticker_id_sent = None

        print()
        print("=" * 62)
        print(f"  MAXAPI METHOD AUDIT  —  chat {CHAT_ID}")
        print("=" * 62)
        print()

        # ── 1. send_message ─────────────────────────────────────────────
        print("▶ send_message (plain text)")
        try:
            r = await client.send_message(CHAT_ID, "🧪 [test_all_methods] suite started")
            sent_id = msg_id(r)
            rec("send_message", bool(sent_id), f"msgId={sent_id}")
        except Exception as e:
            rec("send_message", False, str(e))
        await asyncio.sleep(0.5)

        # ── 2. send_message with reply_to ────────────────────────────────
        print("▶ send_message(reply_to)")
        reply_id = None
        if sent_id:
            try:
                r = await client.send_message(CHAT_ID, "↩️ reply test", reply_to=sent_id)
                reply_id = msg_id(r)
                rec("send_message(reply_to)", bool(reply_id), f"msgId={reply_id}")
            except Exception as e:
                rec("send_message(reply_to)", False, str(e))
        else:
            rec("send_message(reply_to)", False, "skipped — send_message failed")
        await asyncio.sleep(0.5)

        # ── 3. forward_message ───────────────────────────────────────────
        print("▶ forward_message")
        fwd_id = None
        if sent_id:
            try:
                r = await client.forward_message(CHAT_ID, CHAT_ID, sent_id)
                fwd_id = msg_id(r)
                rec("forward_message", bool(fwd_id), f"msgId={fwd_id}")
            except Exception as e:
                rec("forward_message", False, str(e))
        else:
            rec("forward_message", False, "skipped — send_message failed")
        await asyncio.sleep(0.5)

        # ── 4. edit_message ──────────────────────────────────────────────
        print("▶ edit_message")
        if sent_id:
            try:
                r = await client.edit_message(CHAT_ID, sent_id, "✏️ [edited] test message")
                ok = isinstance(r, dict) and "error" not in r
                rec("edit_message", ok, json.dumps(r)[:100])
            except Exception as e:
                rec("edit_message", False, str(e))
        else:
            rec("edit_message", False, "skipped — no sent_id")
        await asyncio.sleep(0.5)

        # ── 5. send_typing ───────────────────────────────────────────────
        print("▶ send_typing")
        try:
            await client.send_typing(CHAT_ID)
            rec("send_typing", True, "fire-and-forget, no error")
        except Exception as e:
            rec("send_typing", False, str(e))
        await asyncio.sleep(0.5)

        # ── 6. mark_read ─────────────────────────────────────────────────
        print("▶ mark_read")
        if sent_id:
            try:
                r = await client.mark_read(CHAT_ID, sent_id)
                rec("mark_read", isinstance(r, dict) and "error" not in r, json.dumps(r)[:80])
            except Exception as e:
                rec("mark_read", False, str(e))
        else:
            rec("mark_read", False, "skipped — no sent_id")
        await asyncio.sleep(0.5)

        # ── 7. react ─────────────────────────────────────────────────────
        print("▶ react")
        if sent_id:
            try:
                await client.react(CHAT_ID, sent_id, "👍")
                rec("react", True, "fire-and-forget, no error")
            except Exception as e:
                rec("react", False, str(e))
        else:
            rec("react", False, "skipped — no sent_id")
        await asyncio.sleep(0.5)

        # ── 8. cancel_reaction ───────────────────────────────────────────
        print("▶ cancel_reaction")
        if sent_id:
            try:
                await client.cancel_reaction(CHAT_ID, sent_id)
                rec("cancel_reaction", True, "fire-and-forget, no error")
            except Exception as e:
                rec("cancel_reaction", False, str(e))
        else:
            rec("cancel_reaction", False, "skipped — no sent_id")
        await asyncio.sleep(0.5)

        # ── 9. send_sticker ──────────────────────────────────────────────
        print("▶ send_sticker")
        try:
            r = await client.send_sticker(CHAT_ID, STICKER_ID)
            sticker_id_sent = msg_id(r)
            rec("send_sticker", bool(sticker_id_sent), f"msgId={sticker_id_sent}")
        except Exception as e:
            rec("send_sticker", False, str(e))
        await asyncio.sleep(0.5)

        # ── 10. send_photo ───────────────────────────────────────────────
        print("▶ send_photo (10×10 PNG)")
        photo_msg_id = None
        try:
            r = await client.send_photo(CHAT_ID, TINY_PNG, caption="📷 photo test")
            photo_msg_id = msg_id(r)
            rec("send_photo", bool(photo_msg_id), f"msgId={photo_msg_id}")
        except Exception as e:
            rec("send_photo", False, str(e))
        await asyncio.sleep(0.5)

        # ── 11. get_chat_history ─────────────────────────────────────────
        print("▶ get_chat_history")
        try:
            r = await client.get_chat_history(CHAT_ID, count=10)
            messages = r.get("messages", []) if isinstance(r, dict) else []
            rec("get_chat_history", isinstance(messages, list), f"{len(messages)} messages")
        except Exception as e:
            rec("get_chat_history", False, str(e))
        await asyncio.sleep(0.5)

        # ── 12. get_chat_info ────────────────────────────────────────────
        # NOTE: may cause server disconnect for DM chats — always reconnect after
        print("▶ get_chat_info")
        try:
            r = await client.get_chat_info(CHAT_ID)
            err = r.get("error", "") if isinstance(r, dict) else ""
            name = r.get("title") or r.get("name") or r.get("id") or "?"
            # Для P2P-чатов (DIALOG) сервер возвращает ошибку — это ожидаемо
            ok = isinstance(r, dict) and not err
            suffix = "(только для групп!)" if not ok else ""
            rec("get_chat_info", ok, f"name={name!r} {suffix}".strip())
        except Exception as e:
            rec("get_chat_info", False, str(e))
        await asyncio.sleep(0.5)
        await ensure_connected(client)   # сервер может закрыть соединение после этого запроса

        # ── 13. get_chat_members ─────────────────────────────────────────
        print("▶ get_chat_members")
        try:
            r = await client.get_chat_members(CHAT_ID, count=10)
            err = r.get("error", "") if isinstance(r, dict) else ""
            members = r.get("members", []) if isinstance(r, dict) else []
            ok = isinstance(r, dict) and not err
            suffix = "(только для групп!)" if not ok else ""
            rec("get_chat_members", ok, f"{len(members)} members {suffix}".strip())
        except Exception as e:
            rec("get_chat_members", False, str(e))
        await asyncio.sleep(0.5)

        # ── 14. get_chats (cache) ────────────────────────────────────────
        print("▶ get_chats")
        try:
            chats = await client.get_chats()
            rec("get_chats", isinstance(chats, list), f"{len(chats)} chats")
        except Exception as e:
            rec("get_chats", False, str(e))
        await asyncio.sleep(0.3)

        # ── 15. poll_chats ───────────────────────────────────────────────
        print("▶ poll_chats")
        await ensure_connected(client)
        try:
            chats = await client.poll_chats(count=20)
            rec("poll_chats", isinstance(chats, list), f"{len(chats)} chats")
        except Exception as e:
            rec("poll_chats", False, str(e))
        await asyncio.sleep(0.5)

        # ── 16. fetch_profile ────────────────────────────────────────────
        print("▶ fetch_profile (own)")
        await ensure_connected(client)
        try:
            r = await client.fetch_profile(MY_UID)
            names_list = r.get("names", []) if isinstance(r, dict) else []
            first_name = names_list[0].get("firstName", "") if names_list else ""
            name = first_name or r.get("id", "?")
            rec("fetch_profile", isinstance(r, dict) and "error" not in r, f"name={name!r}")
        except Exception as e:
            rec("fetch_profile", False, str(e))
        await asyncio.sleep(0.5)

        # ── 17. get_contacts ─────────────────────────────────────────────
        print("▶ get_contacts (BLOCKED)")
        await ensure_connected(client)
        try:
            r = await client.get_contacts("BLOCKED")
            rec("get_contacts", isinstance(r, list), f"{len(r)} contacts")
        except Exception as e:
            rec("get_contacts", False, str(e))
        await asyncio.sleep(0.5)

        # ── 18. search_contacts ──────────────────────────────────────────
        print("▶ search_contacts")
        await ensure_connected(client)
        try:
            r = await client.search_contacts("Kirill")
            contacts = r.get("contacts", []) if isinstance(r, dict) else []
            rec("search_contacts", isinstance(r, dict) and "error" not in r, f"{len(contacts)} results")
        except Exception as e:
            rec("search_contacts", False, str(e))
        await asyncio.sleep(0.5)

        # ── 19. search ───────────────────────────────────────────────────
        print("▶ search (global)")
        await ensure_connected(client)
        try:
            r = await client.search("MAX")
            pub   = len(r.get("public",   []))
            ctcts = len(r.get("contacts", []))
            chs   = len(r.get("chats",    []))
            rec("search", isinstance(r, dict), f"chats={chs}, contacts={ctcts}, public={pub}")
        except Exception as e:
            rec("search", False, str(e))
        await asyncio.sleep(0.5)

        # ── 20. get_link_info ────────────────────────────────────────────
        print("▶ get_link_info")
        await ensure_connected(client)
        try:
            r = await client.get_link_info("https://example.com")
            err = r.get("error", "") if isinstance(r, dict) else ""
            # «link.not.found» — протокол работает, URL просто не кешируется
            ok = isinstance(r, dict) and err != "proto.payload"
            rec("get_link_info", ok, err or json.dumps(r)[:60])
        except Exception as e:
            rec("get_link_info", False, str(e))
        await asyncio.sleep(0.5)

        # ── 21. delete_messages ──────────────────────────────────────────
        # Удаляем отправленные тестовые сообщения чтобы не засорять чат
        print("▶ delete_messages (cleanup)")
        await ensure_connected(client)
        to_delete = [i for i in [sent_id, reply_id, fwd_id, sticker_id_sent, photo_msg_id] if i]
        if to_delete:
            try:
                r = await client.delete_messages(CHAT_ID, to_delete)
                ok = isinstance(r, dict) and "error" not in r
                rec("delete_messages", ok, f"deleted {len(to_delete)} msgs, resp={json.dumps(r)[:80]}")
            except Exception as e:
                rec("delete_messages", False, str(e))
        else:
            rec("delete_messages", False, "skipped — nothing to delete")

        # ─────────────────────────────── SUMMARY ────────────────────────
        passed = sum(1 for _, ok, _ in results if ok)
        failed = sum(1 for _, ok, _ in results if not ok)

        print()
        print("=" * 62)
        print("  SUMMARY")
        print("=" * 62)
        print(f"  Passed: {passed}/{len(results)},  Failed: {failed}/{len(results)}")
        print()

        for name, ok, detail in results:
            icon   = "✅" if ok else "❌"
            suffix = f"  ({detail})" if detail else ""
            print(f"  {icon}  {name}{suffix}")

        print()
        if failed:
            print("  ⚠️  Методы выше помечены ❌ — НЕ работают и не должны быть в документации.")
        else:
            print("  🎉  Все методы прошли проверку!")
        print()


if __name__ == "__main__":
    asyncio.run(run())
