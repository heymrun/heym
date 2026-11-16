"""Split a chat message that is over a platform's length limit into parts it accepts."""


def split_message_text(text: str, limit: int) -> list[str]:
    """Split text into parts of at most ``limit``, cut at a line break or a space when one is near.

    Length is counted in UTF-16 code units, as Telegram and Discord count it, so a character
    outside the BMP (most emoji) takes two. The separator a cut lands on is dropped; a text
    without one near the limit is cut at the limit. A text within the limit is one part.
    """
    parts: list[str] = []
    rest = text
    while len(rest.encode("utf-16-le")) // 2 > limit:
        end = units = 0
        for char in rest:
            units += 2 if ord(char) > 0xFFFF else 1
            if units > limit:
                break
            end += 1
        cut = rest.rfind("\n", 0, end + 1)
        if cut < end // 2:
            cut = rest.rfind(" ", 0, end + 1)
        if cut < end // 2:
            parts.append(rest[:end])
            rest = rest[end:]
            continue
        parts.append(rest[:cut])
        rest = rest[cut + 1 :]
    parts.append(rest)
    return parts
