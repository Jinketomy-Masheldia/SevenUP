"""Minimal strict IMG4 container handling; never changes IM4P payload bytes."""

import hashlib

from .core import require


def tlv(data: bytes, offset=0):
    require(0 <= offset and offset + 2 <= len(data), "Truncated DER header.")
    tag, length = data[offset:offset + 2]
    require(tag & 31 != 31, "High-tag DER is not accepted at the IMG4 container level.")
    head = offset + 2
    if length & 128:
        count = length & 127
        require(1 <= count <= 8 and head + count <= len(data), "Invalid DER length.")
        length = int.from_bytes(data[head:head + count], "big")
        require(length >= 128, "Non-canonical DER length.")
        head += count
    require(head + length <= len(data), "Truncated DER body.")
    return tag, head, head + length


def children(data: bytes):
    tag, pos, end = tlv(data)
    require(tag in (0x30, 0xA0) and end == len(data), "Expected a complete DER container.")
    result = []
    while pos < end:
        tag, body, tail = tlv(data, pos)
        result.append((tag, data[body:tail], data[pos:tail]))
        pos = tail
    return result


def pack(tag: int, body: bytes) -> bytes:
    length = len(body)
    prefix = bytes([length]) if length < 128 else length.to_bytes((length.bit_length() + 7) // 8, "big")
    if length >= 128:
        prefix = bytes([128 | len(prefix)]) + prefix
    return bytes([tag]) + prefix + body


def split_image(image: bytes) -> tuple[bytes, bytes]:
    top = children(image)
    require(len(top) >= 3 and top[0][1] == b"IMG4" and top[1][0] == 0x30, "Expected IMG4 with IM4P and IM4M.")
    payload = top[1][2]
    require(children(payload)[0][1] == b"IM4P", "Missing IM4P.")
    tickets = [item for item in top if item[0] == 0xA0]
    require(len(tickets) == 1, "Expected exactly one IM4M wrapper.")
    ticket = tickets[0][1]
    require(children(ticket)[0][1] == b"IM4M", "Missing IM4M.")
    return payload, ticket


def wrap(payload: bytes, ticket: bytes) -> bytes:
    require(children(payload)[0][1] == b"IM4P", "Invalid IM4P input.")
    require(children(ticket)[0][1] == b"IM4M", "Invalid IM4M input.")
    return pack(0x30, pack(0x16, b"IMG4") + payload + pack(0xA0, ticket))


def reticket(image: bytes, ticket: bytes) -> bytes:
    old_payload, _ = split_image(image)
    require(children(ticket)[0][1] == b"IM4M", "Invalid replacement ticket.")
    result = pack(0x30, b"".join(pack(0xA0, ticket) if tag == 0xA0 else raw for tag, _, raw in children(image)))
    new_payload, new_ticket = split_image(result)
    require(old_payload == new_payload and new_ticket == ticket, "IMG4 reticket validation failed.")
    return result


def im4p_type(payload: bytes) -> str:
    rows = children(payload)
    require(rows[0][1] == b"IM4P" and len(rows[1][1]) == 4, "Invalid IM4P type.")
    return rows[1][1].decode("ascii")


def ticket_hash(ticket: bytes) -> str:
    return hashlib.sha384(ticket).hexdigest().upper()
