import math
from datetime import datetime

from rich.table import Table
from rich.text import Text
from textual.screen import ModalScreen

from .constants import SERVICE_INTERVALS, THRESHOLDS
from .state import HOST_DETAILS, SERVICE_DETAILS
from .theme import PALETTE


def local_now() -> datetime:
    return datetime.now().astimezone()


def ago(moment) -> str:
    if moment is None:
        return "never"
    seconds = max(0, int((local_now() - moment).total_seconds()))
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def nav_hint_text(hints) -> Text:
    t = Text(" ")
    for i, (key, label) in enumerate(hints):
        if i:
            t.append("   ")
        t.append(key)
        t.append(f" {label}")
    t.append(" ")
    return t


def fmt_bytes(value: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.0f} {units[index]}" if index < 2 else f"{value:.1f} {units[index]}"


def fmt_rate(value: float) -> str:
    return fmt_bytes(value) + "/s"


def fmt_gb(value: float) -> str:
    return f"{value:.1f}G" if value < 10 else f"{value:,.0f}G"


def fmt_duration(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours}:{minutes:02}:{secs:02}"
    return f"{days} day{'s' if days != 1 else ''}, {clock}" if days else clock


def fmt_pct(value: float) -> str:
    return f"{value:.0f}%"


def fmt_ms(value: float) -> str:
    return f"{value:.0f} ms"


def fmt_num(value: float) -> str:
    return f"{value:,.0f}" if value >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")


def fmt_mb(value: float) -> str:
    return f"{value / 1024:.1f} GB" if value >= 1024 else f"{value:.0f} MB"


def interval_label(seconds: int) -> str:
    return next((label for label, value in SERVICE_INTERVALS if value == seconds), f"{seconds} seconds")


def interval_short(seconds: int) -> str:
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"


def palette(app) -> dict:
    return PALETTE


def level_style(level: str, pal: dict) -> str:
    return {"critical": pal["bad"], "warning": pal["warn"], "ok": pal["ok"], "info": pal["accent"]}[level]


def rate(kind: str, value: float) -> str:
    warn, bad = THRESHOLDS[kind]
    return "critical" if value >= bad else "warning" if value >= warn else "ok"


def newtext(*args, **kwargs) -> Text:
    return Text(*args, no_wrap=True, overflow="ellipsis", **kwargs)


def _line_count(content) -> int:
    return (content.plain if isinstance(content, Text) else str(content)).count("\n")


def put(widget, content) -> None:
    old = getattr(widget, "shown_content", None)
    if old == content:
        return
    widget.shown_content = content
    width = widget.styles.width
    steady = old is not None and width is not None and not width.is_auto \
        and _line_count(old) == _line_count(content)
    try:
        widget.update(content, layout=not steady)
    except TypeError:
        widget.update(content)


def is_front(screen) -> bool:
    for candidate in reversed(screen.app.screen_stack):
        if not isinstance(candidate, ModalScreen):
            return candidate is screen
    return False


def kv(label: str, value, width: int = 16, style: str | None = None) -> Text:
    line = newtext()
    line.append(f"{label:<{width}}", style="dim")
    line.append(str(value), style=style)
    return line


def add_row(table: Table, *cells) -> None:
    table.add_row(*[Text(c) if isinstance(c, str) else c for c in cells])


def usage_bar(pct: float, width: int, pal: dict, low: float = 70, high: float = 90) -> Text:
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100)
    color = pal["bad"] if pct >= high else pal["warn"] if pct >= low else pal["ok"]
    frame = f"dim {pal['accent']}"
    bar = Text(no_wrap=True)
    bar.append("│", style=frame)
    bar.append("▰" * filled, style=color)
    bar.append("▱" * (width - filled), style="dim")
    bar.append("│", style=frame)
    return bar


def nice_ceiling(value: float, floor: float = 1.0) -> float:
    value = max(value, floor)
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def log_event_text(entry: tuple) -> str:
    text, host, service = entry[2], entry[3], entry[5]
    return text.replace("{service}", f"{service} [{host}]") if service else text


def service_site(host: str, name: str, port: int) -> dict:
    address = HOST_DETAILS.get(host, {}).get("address", "")
    protocol = SERVICE_DETAILS.get((host, name, port), {}).get("protocol", "TCP")
    scheme = {"HTTP": "http", "HTTPS": "https"}.get(protocol)
    if scheme:
        shown = "" if (scheme, port) in (("http", 80), ("https", 443)) else f":{port}"
        return {"label": "Site", "value": f"{scheme}://{address}{shown}"}
    return {"label": "Endpoint", "value": f"{address}:{port}"}
