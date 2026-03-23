"""
Бинарный протокол MAX мессенджера.

Формат пакета (10 байт заголовок + payload):
  version (1B) = 10
  cmd     (1B) = тип команды
  seq     (2B) = порядковый номер (big-endian)
  opcode  (2B) = код операции (big-endian)
  length  (4B) = [compression_ratio(1B) << 24 | payload_length(3B)] (big-endian)

Payload: MessagePack-сериализованная Map.
Сжатие: LZ4 если payload >= 32 байт.
"""

import struct
import io
from typing import Any, Dict, Optional, Tuple

import msgpack
import lz4.block

from maxapi.constants import PACKET_VERSION, PACKET_HEADER_SIZE, LZ4_THRESHOLD


def serialize_payload(params: dict) -> bytes:
    """Сериализация параметров в MessagePack (аналог adi.h0)."""
    if not params:
        return b""
    return msgpack.packb(params, use_bin_type=True)


def deserialize_payload(data: bytes) -> dict:
    """Десериализация MessagePack в dict (аналог adi.Q)."""
    if not data:
        return {}
    return msgpack.unpackb(data, raw=False, strict_map_key=False)


def encode_packet(
    cmd: int,
    seq: int,
    opcode: int,
    params: Optional[dict] = None,
    version: int = PACKET_VERSION,
) -> bytes:
    """
    Кодирует пакет для отправки (аналог hnc.b / hnc.c).

    Args:
        cmd: Тип команды (0=normal, 2=persistent).
        seq: Порядковый номер пакета.
        opcode: Код операции (OpCode).
        params: Параметры (dict), будут сериализованы в MessagePack.
        version: Версия протокола (по умолчанию 10).

    Returns:
        bytes: Закодированный пакет (заголовок + payload).
    """
    payload = serialize_payload(params) if params else b""
    payload_len = len(payload)

    if payload_len >= LZ4_THRESHOLD:
        # Сжимаем LZ4 (аналог hnc.c)
        compressed = lz4.block.compress(payload, store_size=False)
        compressed_len = len(compressed)
        ratio = (payload_len // compressed_len) + 1
        length_field = (ratio << 24) | compressed_len
        header = struct.pack(
            ">bbHHI",
            version, cmd, seq & 0xFFFF, opcode & 0xFFFF, length_field
        )
        return header + compressed
    else:
        # Без сжатия (аналог hnc.b)
        length_field = payload_len  # compression ratio = 0
        header = struct.pack(
            ">bbHHI",
            version, cmd, seq & 0xFFFF, opcode & 0xFFFF, length_field
        )
        return header + payload


def decode_header(data: bytes) -> Tuple[int, int, int, int, int, int]:
    """
    Декодирует заголовок пакета.

    Args:
        data: Минимум 10 байт.

    Returns:
        (version, cmd, seq, opcode, compression_ratio, payload_length)

    Raises:
        ValueError: Если данных недостаточно.
    """
    if len(data) < PACKET_HEADER_SIZE:
        raise ValueError(f"Недостаточно данных для заголовка: {len(data)} < {PACKET_HEADER_SIZE}")

    version, cmd, seq, opcode, length_raw = struct.unpack(">bbHHI", data[:PACKET_HEADER_SIZE])

    compression_ratio = (length_raw >> 24) & 0xFF
    payload_length = length_raw & 0x00FFFFFF

    return version, cmd, seq, opcode, compression_ratio, payload_length


def decode_packet(header_data: bytes, payload_data: bytes, compression_ratio: int) -> dict:
    """
    Декодирует payload пакета (с учётом сжатия).

    Args:
        header_data: 10-байтный заголовок (для мета-информации).
        payload_data: Сырые байты payload.
        compression_ratio: Коэффициент сжатия из заголовка (0 = без сжатия).

    Returns:
        dict: Десериализованные параметры.
    """
    if not payload_data:
        return {}

    if compression_ratio > 0:
        # Нужно распаковать LZ4
        # Оригинальный размер ~ compressed_len * ratio
        # Используем uncompressed_size как подсказку: ratio * len(payload_data)
        uncompressed_size = compression_ratio * len(payload_data)
        decompressed = lz4.block.decompress(
            payload_data,
            uncompressed_size=uncompressed_size
        )
        return deserialize_payload(decompressed)
    else:
        return deserialize_payload(payload_data)


class Packet:
    """Представление одного пакета протокола MAX."""

    __slots__ = ("version", "cmd", "seq", "opcode", "compression_ratio", "payload_length", "params")

    def __init__(
        self,
        opcode: int,
        params: Optional[dict] = None,
        cmd: int = 0,
        seq: int = 0,
        version: int = PACKET_VERSION,
    ):
        self.version = version
        self.cmd = cmd
        self.seq = seq
        self.opcode = opcode
        self.compression_ratio = 0
        self.payload_length = 0
        self.params = params or {}

    def encode(self, seq: Optional[int] = None) -> bytes:
        """Кодирует пакет в байты для отправки."""
        s = seq if seq is not None else self.seq
        return encode_packet(self.cmd, s, self.opcode, self.params, self.version)

    @classmethod
    def from_bytes(cls, header: bytes, payload: bytes, compression_ratio: int) -> "Packet":
        """Создаёт Packet из полученных байт."""
        version, cmd, seq, opcode, cr, pl = decode_header(header)
        params = decode_packet(header, payload, compression_ratio)
        pkt = cls(opcode=opcode, params=params, cmd=cmd, seq=seq, version=version)
        pkt.compression_ratio = cr
        pkt.payload_length = pl
        return pkt

    def __repr__(self) -> str:
        from maxapi.constants import OpCode
        # Пытаемся найти имя опкода
        name = str(self.opcode)
        for attr in dir(OpCode):
            if not attr.startswith("_") and getattr(OpCode, attr) == self.opcode:
                name = attr
                break
        return f"Packet({name}, seq={self.seq}, params_keys={list(self.params.keys())})"
