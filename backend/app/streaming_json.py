"""Read only the top-level answer string from incomplete model JSON."""

import json


def answer_prefix(text: str) -> str:
    decoder = json.JSONDecoder()
    cursor = 0
    def spaces():
        nonlocal cursor
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    try:
        spaces()
        if cursor >= len(text) or text[cursor] != "{":
            return ""
        cursor += 1
        while cursor < len(text):
            spaces()
            key, cursor = decoder.raw_decode(text, cursor)
            spaces()
            if cursor >= len(text) or text[cursor] != ":":
                return ""
            cursor += 1
            spaces()
            if key == "answer":
                if cursor >= len(text) or text[cursor] != '"':
                    return ""
                return string_prefix(text, cursor + 1)
            _, cursor = decoder.raw_decode(text, cursor)
            spaces()
            if cursor >= len(text) or text[cursor] != ",":
                return ""
            cursor += 1
    except (ValueError, RecursionError):
        pass
    return ""


def string_prefix(text: str, cursor: int) -> str:
    result = []
    escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while cursor < len(text):
        character = text[cursor]
        if character == '"':
            break
        if character == "\\":
            if cursor + 1 >= len(text):
                break
            escape = text[cursor + 1]
            if escape in escapes:
                result.append(escapes[escape]); cursor += 2; continue
            if escape != "u" or cursor + 6 > len(text):
                break
            try:
                value = int(text[cursor + 2:cursor + 6], 16)
                if 0xD800 <= value <= 0xDBFF:
                    if cursor + 12 > len(text) or text[cursor + 6:cursor + 8] != "\\u":
                        break
                    low = int(text[cursor + 8:cursor + 12], 16)
                    if not 0xDC00 <= low <= 0xDFFF:
                        break
                    value = 0x10000 + ((value - 0xD800) << 10) + low - 0xDC00
                    cursor += 6
                elif 0xDC00 <= value <= 0xDFFF:
                    break
                result.append(chr(value)); cursor += 6; continue
            except ValueError:
                break
        if ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF:
            break
        result.append(character); cursor += 1
    return "".join(result)


def partial_json(text: str):
    """Read an incomplete JSON value, retaining only safely decoded prefixes."""
    decoder, cursor = json.JSONDecoder(), 0
    missing = object()
    def spaces():
        nonlocal cursor
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    def read(depth=0):
        nonlocal cursor
        spaces()
        if cursor >= len(text) or depth > 32:
            return missing, False
        first = text[cursor]
        if first == '"':
            start = cursor
            try:
                value, cursor = decoder.raw_decode(text, cursor)
                value.encode("utf-8")
                return value, True
            except (ValueError, UnicodeError):
                cursor = len(text)
                return string_prefix(text, start + 1), False
        if first == "{":
            cursor += 1
            result = {}
            while True:
                spaces()
                if cursor < len(text) and text[cursor] == "}":
                    cursor += 1
                    return result, True
                if cursor >= len(text) or text[cursor] != '"':
                    return result, False
                try:
                    key, cursor = decoder.raw_decode(text, cursor)
                except ValueError:
                    return result, False
                spaces()
                if not isinstance(key, str) or cursor >= len(text) or text[cursor] != ":":
                    return result, False
                cursor += 1
                value, complete = read(depth + 1)
                if value is not missing:
                    result[key] = value
                if not complete:
                    return result, False
                spaces()
                if cursor < len(text) and text[cursor] == ",":
                    cursor += 1
                elif cursor < len(text) and text[cursor] == "}":
                    cursor += 1
                    return result, True
                else:
                    return result, False
        if first == "[":
            cursor += 1
            result = []
            while True:
                spaces()
                if cursor < len(text) and text[cursor] == "]":
                    cursor += 1
                    return result, True
                value, complete = read(depth + 1)
                if value is not missing:
                    result.append(value)
                if not complete:
                    return result, False
                spaces()
                if cursor < len(text) and text[cursor] == ",":
                    cursor += 1
                elif cursor < len(text) and text[cursor] == "]":
                    cursor += 1
                    return result, True
                else:
                    return result, False
        try:
            value, cursor = decoder.raw_decode(text, cursor)
            return value, True
        except ValueError:
            return missing, False
    try:
        value, _ = read()
    except (ValueError, RecursionError):
        return None
    return value if value is not missing else None


def summary_prefix(text: str) -> str:
    """Expose readable notes, never raw JSON or unvalidated citation fields."""
    data = partial_json(text[:128 * 1024])
    if not isinstance(data, dict):
        return ""
    def field(item, key, limit):
        value = item.get(key)
        return value[:limit] if isinstance(value, str) else ""
    parts = [field(data, "headline", 300), field(data, "overview", 4000)]
    chapters = data.get("chapters")
    if isinstance(chapters, list):
        for i, chapter in enumerate(chapters[:40]):
            if not isinstance(chapter, dict):
                continue
            title = field(chapter, "title", 200)
            if title:
                parts.append(f"章节 {i + 1}：{title}")
            parts.append(field(chapter, "overview", 2000))
            points = chapter.get("points")
            if isinstance(points, list):
                for point in points[:12]:
                    if isinstance(point, dict):
                        value = field(point, "text", 1500)
                        if value:
                            parts.append("• " + value)
    return "\n\n".join(part for part in parts if part)[:16000]
