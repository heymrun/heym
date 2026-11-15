"""Response headers for downloads named after something the user named."""

from urllib.parse import quote


def attachment_disposition(filename: str) -> str:
    """``Content-Disposition`` value for downloading ``filename``.

    Starlette encodes header values as Latin-1, so a name such as "Müşteri Raporları" or
    "报表" cannot go into ``filename="..."`` as is: building the response raises. Names that
    need quoting use the RFC 5987 ``filename*`` form, the same rule as Starlette's
    ``FileResponse``.
    """
    quoted = quote(filename)
    if quoted == filename:
        return f'attachment; filename="{filename}"'
    return f"attachment; filename*=utf-8''{quoted}"
