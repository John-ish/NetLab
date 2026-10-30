from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static

from .charts import braille_grid
from .constants import SERVICE_ICON, SERVICE_LABEL
from .helpers import interval_short, palette, put


class KeyBar(Widget):

    def __init__(self, events: list[tuple[str, str]]) -> None:
        super().__init__(id="footer-keys")
        self.events = events

    def _lines(self, width: int) -> list[list[tuple[str, str]]]:
        lines, current, used = [], [], 0
        for key, label in self.events:
            size = len(key) + 1 + len(label)
            if current and used + 3 + size > width:
                lines.append(current)
                current, used = [], 0
            used += size + (3 if current else 0)
            current.append((key, label))
        if current:
            lines.append(current)
        return lines

    def get_content_height(self, container, viewport, width: int) -> int:
        return max(1, len(self._lines(max(10, width))))

    def render(self) -> Text:
        accent = palette(self.app)["accent"]
        out = []
        for line in self._lines(max(10, self.size.width)):
            text = Text(no_wrap=True, overflow="crop")
            for index, (key, label) in enumerate(line):
                if index:
                    text.append("   ")
                text.append(key, style=accent)
                text.append(f" {label}", style="dim")
            out.append(text)
        return Text("\n").join(out)


class SvcScroll(VerticalScroll, can_focus=False, inherit_bindings=False):
    """Scroll container that doesn't steal focus or arrow keys from the rows."""


class SparkLine(Static):

    def __init__(self, chart_rows: int = 2, window: int = 60, **kwargs):
        super().__init__("", **kwargs)
        self.chart_rows = chart_rows
        self.window = window
        self.points: list[float] = []
        self.high = 100.0

    def plot(self, points, high: float = 100.0) -> None:
        self.points = list(points)[-self.window:]
        self.high = high
        self._draw()

    def on_resize(self, event) -> None:
        self._draw()

    def _draw(self) -> None:
        width = self.size.width
        if width <= 0:
            return
        grid = braille_grid(self.points, width, self.chart_rows, 0.0, self.high, fill=True)
        lines = ["".join(chr(0x2800 + bits) if bits else " " for bits in row) for row in grid]
        self.update(Text("\n".join(lines), no_wrap=True, overflow="crop"))


class DetailCard(Vertical, can_focus=True):
    BINDINGS = [("enter", "open", "Details")]

    class Opened(Message):
        def __init__(self, kind: str) -> None:
            super().__init__()
            self.kind = kind

    def __init__(self, kind: str, title: str, *children, subtitle: str = "↗") -> None:
        super().__init__(*children, id=f"card-{kind}", classes="focus-target")
        self.kind = kind
        self.card_title = title
        self.card_subtitle = subtitle

    def on_mount(self) -> None:
        self.border_title = self.card_title
        self.border_subtitle = Text(self.card_subtitle)

    def on_click(self, event: Click) -> None:
        self.focus()
        self.action_open()

    def action_open(self) -> None:
        self.post_message(self.Opened(self.kind))


class ServiceList(ListView):

    def action_cursor_up(self) -> None:
        if not self.index:
            self.screen.action_nav(0, -1)
        else:
            super().action_cursor_up()

    def action_cursor_down(self) -> None:
        if self.index is None or self.index >= len(self.children) - 1:
            self.screen.action_nav(0, 1)
        else:
            super().action_cursor_down()


class ServiceItem(ListItem):

    def __init__(self, service: str, port: int, state: str, latency: float | None):
        super().__init__()
        self.service, self.port, self.state = service, port, state
        self.latency = latency
        self.w_status = self.w_latency = None

    def compose(self) -> ComposeResult:
        yield Static("❱", classes="col-cursor")
        yield Static(Text(self.service), classes="col-name")
        yield Static(f":{self.port}", classes="col-port")
        yield Static(f"{SERVICE_ICON[self.state]}  {SERVICE_LABEL[self.state]}",
                     classes=f"col-status {self.state}")
        yield Static("—" if self.latency is None else f"{self.latency:.0f} ms", classes="col-latency")

    def show(self, state: str, latency: float | None) -> None:
        changed = state != self.state
        self.state = state
        if self.w_status is None:
            self.w_status = self.query_one(".col-status", Static)
            self.w_latency = self.query_one(".col-latency", Static)
        put(self.w_status, f"{SERVICE_ICON[state]}  {SERVICE_LABEL[state]}")
        if changed:
            self.w_status.set_classes(f"col-status {state}")
        put(self.w_latency, "—" if latency is None else f"{latency:.0f} ms")


class RangeOption(Static):

    def __init__(self, label: str, index: int):
        super().__init__(label, classes="range-opt")
        self.index = index

    def on_click(self, event: Click) -> None:
        self.screen.action_pick_range(self.index)


class LiveBadge(Static):

    def show(self, seconds: int) -> None:
        text = Text(no_wrap=True)
        text.append(f"● LIVE: {interval_short(seconds)}")
        text.append("  [i] edit", style="dim")
        put(self, text)

    def on_click(self, event: Click) -> None:
        self.screen.action_edit_interval()
