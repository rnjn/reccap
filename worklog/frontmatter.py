import json
import re

PLAIN = re.compile(r"^[A-Za-z0-9_./~+()][^\[\]{},\"]*$")
RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


def scalar(value):
    if isinstance(value, int):
        return str(value)
    text = str(value)
    needs_quotes = (
        not PLAIN.match(text)
        or ": " in text
        or " #" in text
        or text.endswith(":")
        or text != text.strip()
        or text.lower() in RESERVED
    )
    return json.dumps(text, ensure_ascii=False) if needs_quotes else text


def dump(pairs):
    lines = ["---"]
    for key, value in pairs:
        if isinstance(value, list):
            lines.append(key + ": [" + ", ".join(scalar(v) for v in value) + "]")
        else:
            lines.append(key + ": " + scalar(value))
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].split("\n"):
        key, sep, value = line.partition(": ")
        if not sep:
            continue
        if value.startswith("[") and value.endswith("]"):
            meta[key] = _items(value[1:-1])
        else:
            meta[key] = _unquote(value)
    return meta, text[end + 5 :]


def _unquote(value):
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _items(inner):
    items = re.findall(r'"(?:[^"\\]|\\.)*"|[^,\s][^,]*', inner)
    return [_unquote(item.strip()) for item in items]
