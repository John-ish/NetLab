from datetime import datetime

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..config import STYLE_PATH
from ..constants import CHART_KINDS, DETAIL_REFRESH_SECONDS, KIND_TITLES, RANGES, RANGE_MEMORY
from ..detail_builder import DetailBuilder
from ..helpers import nav_hint_text, palette
from ..metrics import monitor
from ..widgets import RangeOption


class MetricDetailScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "close", "Close"),
        ("p", "toggle_pause", "Pause"),
        Binding("left", "shift_range(-1)", "Shorter range", priority=True),
        Binding("right", "shift_range(1)", "Longer range", priority=True),
        Binding("1", "pick_range(0)", "1 min", priority=True),
        Binding("2", "pick_range(1)", "5 min", priority=True),
        Binding("3", "pick_range(2)", "15 min", priority=True),
        Binding("4", "pick_range(3)", "1 hour", priority=True),
    ]

    def __init__(self, host_name: str, kind: str):
        super().__init__()
        self.host_name = host_name
        self.kind = kind
        self.body_signature = None
        self.range_index = RANGE_MEMORY.get(kind, 0)

    def compose(self) -> ComposeResult:
        with Vertical(id="metric-panel"):
            yield Static("", id="metric-meta")
            with Horizontal(id="range-bar"):
                yield Static("Range", id="range-label")
                for index, (label, _) in enumerate(RANGES):
                    yield RangeOption(label, index)
            with VerticalScroll(id="metric-scroll"):
                yield Static("", id="metric-body")

    def on_mount(self) -> None:
        panel = self.query_one("#metric-panel")
        panel.border_title = f"{KIND_TITLES[self.kind]} · {self.host_name}"
        hints = [("[↑/↓]", "Scroll"), ("[Esc]", "Close")]
        if self.kind == "monitor":
            hints.insert(1, ("[p]", "Pause/Resume"))
        if self.kind in CHART_KINDS:
            hints.insert(1, ("[←/→]", "Range"))
        panel.border_subtitle = nav_hint_text(hints)
        self.query_one("#range-bar").display = self.kind in CHART_KINDS
        self._sync_range()
        self.query_one("#metric-scroll").focus()
        self.set_interval(DETAIL_REFRESH_SECONDS, self._draw_body)
        self.call_after_refresh(self._draw_body)

    def _draw_body(self) -> None:
        body = self.query_one("#metric-body", Static)
        builder = DetailBuilder(self.host_name, monitor.get(self.host_name),
                                palette(self.app), (body.size.width or 80) - 1,
                                RANGES[self.range_index][1])
        items = builder.build(self.kind)
        signature = (self.kind, tuple((type(i).__name__, len(i.rows) if isinstance(i, Table) else 0) for i in items))
        try:
            body.update(Group(*items), layout=signature != self.body_signature)
        except TypeError:
            body.update(Group(*items))
        self.body_signature = signature
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.query_one("#metric-meta", Static).update(
            Text(f"Last updated: {stamp}  •  Refresh: {DETAIL_REFRESH_SECONDS}s")
        )

    def _sync_range(self) -> None:
        for option in self.query(RangeOption):
            option.set_class(option.index == self.range_index, "-active")

    def action_pick_range(self, index: int) -> None:
        if self.kind not in CHART_KINDS:
            return
        self.range_index = max(0, min(len(RANGES) - 1, index))
        RANGE_MEMORY[self.kind] = self.range_index
        self._sync_range()
        self._draw_body()

    def action_shift_range(self, step: int) -> None:
        self.action_pick_range(self.range_index + step)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_toggle_pause(self) -> None:
        if self.kind != "monitor":
            return
        m = monitor.get(self.host_name)
        m.paused = not m.paused
        m.note("Monitoring paused" if m.paused else "Monitoring resumed")
        self._draw_body()
