"""Kleine Helfer: Zeit, Snowflakes, Dateinamen, Größenangaben."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

DISCORD_EPOCH_MS = 1420070400000

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def snowflake_to_datetime(snowflake: int | str) -> datetime:
    ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def datetime_to_snowflake(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    ms = int(dt.timestamp() * 1000) - DISCORD_EPOCH_MS
    return max(ms, 0) << 22


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-8601 und die Varianten aus dem Datenpaket robust lesen. Ohne Zone gilt UTC."""
    if not value:
        return None
    m = _TS_RE.match(str(value).strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    micro = int((m.group(7) or "0")[:6].ljust(6, "0"))
    tz = timezone.utc
    zone = m.group(8)
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
    return datetime(year, month, day, hour, minute, second, micro, tzinfo=tz).astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def parse_date_input(text: str) -> date | None:
    """'2024-03-31', '31.03.2024' oder leer. Wirft ValueError bei Unsinn."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Datum nicht lesbar: {text!r} (erwartet 2024-03-31 oder 31.03.2024)")


def date_range_to_utc(von: date | None, bis: date | None) -> tuple[datetime | None, datetime | None]:
    """'von' ab 00:00 lokal, 'bis' einschließlich (also bis zum Folgetag 00:00 lokal)."""
    after = datetime.combine(von, time.min).astimezone() if von else None
    before = datetime.combine(bis + timedelta(days=1), time.min).astimezone() if bis else None
    if after and before and after >= before:
        raise ValueError("Das Startdatum liegt nach dem Enddatum.")
    return after, before


def local(dt: datetime) -> datetime:
    return dt.astimezone()


def fmt_datetime(dt: datetime, seconds: bool = False) -> str:
    return local(dt).strftime("%d.%m.%Y %H:%M:%S" if seconds else "%d.%m.%Y %H:%M")


def fmt_time(dt: datetime) -> str:
    return local(dt).strftime("%H:%M")


def fmt_day_long(dt: datetime) -> str:
    d = local(dt)
    return f"{WEEKDAYS_DE[d.weekday()]}, {d.day}. {MONTHS_DE[d.month - 1]} {d.year}"


def fmt_discord_timestamp(unix: int, style: str) -> str:
    """Discord-Zeitstempel <t:unix:style> als feste deutsche Angabe (Archiv: kein 'vor 3 Tagen')."""
    d = datetime.fromtimestamp(unix, tz=timezone.utc).astimezone()
    long_date = f"{d.day}. {MONTHS_DE[d.month - 1]} {d.year}"
    if style == "t":
        return d.strftime("%H:%M")
    if style == "T":
        return d.strftime("%H:%M:%S")
    if style == "d":
        return d.strftime("%d.%m.%Y")
    if style == "D":
        return long_date
    if style == "F":
        return f"{WEEKDAYS_DE[d.weekday()]}, {long_date} {d.strftime('%H:%M')}"
    return f"{long_date} {d.strftime('%H:%M')}"


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Windows-taugliche Dateinamen: keine verbotenen Zeichen, keine reservierten Namen."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = "unbenannt"
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = "_" + name
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            name = stem[: max_len - len(ext) - 1].rstrip(". ") + "." + ext
        else:
            name = name[:max_len].rstrip(". ")
    return name


def human_size(num: int | None) -> str:
    if num is None:
        return ""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return f"{num} B"
