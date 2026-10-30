import platform
import random
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.color import Color as TColor
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Static

from ..config import APP_VERSION, STYLE_PATH, TEXTUAL_VERSION
from ..constants import HOST_ICON, SPINNER_FRAMES
from ..helpers import newtext, palette
from ..state import SERVICES
from ..store import store
from ..theme import PALETTE
from .startup import LOGO_LINES


BOOT_LINE = 0.30
BOOT_GROW = 0.30
BOOT_FADE = 0.30
BOOT_LOG_START = BOOT_LINE + BOOT_GROW + BOOT_FADE
BOOT_STEP = 0.13
BOOT_HOLD = 0.5


class BootScreen(Screen):

    CSS_PATH = STYLE_PATH

    def __init__(self):
        super().__init__()
        self.begin = time.monotonic()
        self.finished = False
        hosts = store.all()
        services = sum(len(s[2]) for s in SERVICES)
        self.entries = [
            ("Initialising display", ""),
            ("Loading settings", "ok"),
            ("Mounting data store", "in-memory"),
            ("Reading host registry", f"{len(hosts)} hosts"),
            ("Loading service catalogue", f"{services} services"),
            ("Starting metric collectors", f"{len(hosts)} workers"),
            ("Calibrating latency probes", ""),
            ("Applying theme", ""),
        ]
        self.total = BOOT_LOG_START + len(self.entries) * BOOT_STEP + BOOT_HOLD

    def compose(self) -> ComposeResult:
        yield Static("", id="boot")

    def on_mount(self) -> None:
        self.set_interval(1 / 30, self._frame)

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()
        self._finish()

    def on_click(self, event: Click) -> None:
        self._finish()

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.dismiss(None)

    def _background(self) -> TColor:
        return PALETTE["bg"]

    def _band(self, width: int, height: int, half: int, length: int, color: str) -> Text:
        mid, left = height // 2, (width - length) // 2
        lines = []
        for row in range(height):
            if abs(row - mid) <= half:
                lines.append(Text.assemble(
                    (" " * left, ""),
                    (" " * length, f"on {color}"),
                    (" " * (width - left - length), ""),
                ))
            else:
                lines.append(Text(" " * width))
        return Text("\n").join(lines)

    def _log(self, t: float, width: int, pal: dict) -> Text:
        elapsed = t - BOOT_LOG_START
        shown = min(len(self.entries), int(elapsed / BOOT_STEP) + 1)
        lines = [Text()]
        head = newtext()
        head.append("  NETLAB DB", style=f"bold {pal['accent']}")
        head.append(f"  BIOS v{APP_VERSION}", style="dim")
        lines.append(head)
        lines.append(newtext(f"  {platform.system()} · Python {platform.python_version()} · Textual {TEXTUAL_VERSION}", style="dim"))
        lines.append(Text())
        for text, detail in self.entries[:shown]:
            line = newtext()
            line.append("  [  OK  ] ", style=pal["ok"])
            line.append(f"{text:<30}")
            line.append(detail, style="dim")
            lines.append(line)
        lines.append(Text())
        progress = max(0.0, min(1.0, elapsed / (len(self.entries) * BOOT_STEP)))
        cells = max(10, min(32, width - 20))
        filled = round(cells * progress)
        bar = newtext()
        bar.append("  Booting  ", style="dim")
        bar.append("▰" * filled, style=pal["ok"])
        bar.append("▱" * (cells - filled), style="dim")
        bar.append(f"  {progress * 100:>3.0f}%", style="bold")
        bar.append(" █" if int(t * 4) % 2 == 0 else "  ", style=pal["accent"])
        lines.append(bar)
        return newtext("\n").join(lines)

    def _frame(self) -> None:
        t = time.monotonic() - self.begin
        boot = self.query_one("#boot", Static)
        width, height = boot.size
        if width < 4 or height < 3:
            return
        if t >= self.total:
            self._finish()
            return
        white = TColor(255, 255, 255)
        if t < BOOT_LINE:
            progress = t / BOOT_LINE
            boot.update(self._band(width, height, 0, max(2, round(width * progress * progress)), white.hex))
        elif t < BOOT_LINE + BOOT_GROW:
            progress = (t - BOOT_LINE) / BOOT_GROW
            boot.update(self._band(width, height, round(height / 2 * progress), width, white.hex))
        elif t < BOOT_LOG_START:
            progress = (t - BOOT_LINE - BOOT_GROW) / BOOT_FADE
            boot.update(self._band(width, height, height, width, white.blend(self._background(), progress).hex))
        else:
            boot.update(self._log(t, width, palette(self.app)))


class GlitchBootScreen(BootScreen):

    NOISE = "░▒▓█▚▞▌▐#%&@01<>/\\|"
    TAGLINE = "server monitoring terminal"

    def __init__(self):
        super().__init__()
        self.logo_width = len(LOGO_LINES[0])
        rng = random.Random(7)
        self.settle = [0.2 + (c / self.logo_width) * 1.1 + rng.uniform(0, 0.3) for c in range(self.logo_width)]
        self.total = 3.0
        self.tones = None

    def _frame(self) -> None:
        t = time.monotonic() - self.begin
        boot = self.query_one("#boot", Static)
        width, height = boot.size
        if width < 4 or height < 3:
            return
        if t >= self.total:
            self._finish()
            return
        if self.tones is None:
            self.tones = (PALETTE["fill"], PALETTE["shadow"], PALETTE["accent"])
        boot.update(self._compose_frame(t, width, height))

    def _compose_frame(self, t: float, width: int, height: int) -> Text:
        fill, shadow, accent = self.tones
        top = max(0, (height - 8) // 2)
        left = max(0, (width - self.logo_width) // 2)
        glitching = 0.3 < t < 1.9
        lines = []
        for row in range(height):
            if top <= row < top + 6:
                line = Text(no_wrap=True, overflow="crop")
                shift = random.choice((-4, -3, 3, 4)) if glitching and random.random() < 0.12 else 0
                line.append(" " * max(0, left + shift))
                for column, char in enumerate(LOGO_LINES[row - top]):
                    if t >= self.settle[column]:
                        if char == "█":
                            line.append(char, style=f"bold {fill}")
                        else:
                            line.append(char, style=shadow if char != " " else "")
                    elif char != " " or random.random() < 0.03:
                        line.append(random.choice(self.NOISE), style=random.choice((accent, "dim", fill)))
                    else:
                        line.append(" ")
                lines.append(line)
            elif row == top + 7:
                typed = int(max(0.0, t - 1.7) / 0.03)
                shown = self.TAGLINE[:typed]
                cursor = "█" if int(t * 4) % 2 == 0 else " "
                pad = " " * ((width - len(self.TAGLINE)) // 2)
                lines.append(Text.assemble(pad, (shown, "dim"), (cursor, accent)))
            else:
                lines.append(Text())
        return Text("\n").join(lines)


class ScanBootScreen(BootScreen):

    def __init__(self):
        super().__init__()
        self.hosts = list(store.all())
        count = max(1, len(self.hosts))
        self.step = min(0.2, 2.0 / count)
        self.start = 0.5
        self.total = self.start + count * self.step + 1.0

    def _frame(self) -> None:
        t = time.monotonic() - self.begin
        boot = self.query_one("#boot", Static)
        width, height = boot.size
        if width < 4 or height < 3:
            return
        if t >= self.total:
            self._finish()
            return
        boot.update(self._compose_frame(t, width, height, palette(self.app)))

    def _host_line(self, host: tuple, pal: dict) -> Text:
        name, status, _, _, _, latency = host
        color = {"online": pal["ok"], "warning": pal["warn"]}.get(status, "dim")
        line = newtext()
        line.append(f"  {HOST_ICON.get(status, '○')} ", style=color)
        line.append(f"{name:<12}", style="bold")
        line.append(f"{store.details(name)['address'] or '—':<14}", style="dim")
        line.append(f"{'—' if latency is None else f'{latency} ms':>8}  ")
        line.append(status.upper(), style=color)
        return line

    def _compose_frame(self, t: float, width: int, height: int, pal: dict) -> Text:
        total = len(self.hosts)
        done = max(0, min(total, int((t - self.start) / self.step))) if t >= self.start else 0
        spin = SPINNER_FRAMES[int(t * 15) % len(SPINNER_FRAMES)]
        head = newtext()
        head.append("  NETLAB DB", style=f"bold {pal['accent']}")
        head.append("  network scan", style="dim")
        status = newtext()
        if done < total:
            status.append(f"  {spin} ", style=pal["accent"])
            status.append(f"Probing {total} hosts…", style="dim")
        else:
            status.append("  ✓ ", style=pal["ok"])
            status.append("Scan complete", style="dim")
        rows = [self._host_line(host, pal) for host in self.hosts[:done]]
        if done < total:
            probing = newtext()
            probing.append(f"  {spin} ", style=pal["accent"])
            probing.append(f"{self.hosts[done][0]:<12}", style="bold")
            probing.append(f"{store.details(self.hosts[done][0])['address'] or '—':<14}", style="dim")
            probing.append("   probing…", style="dim")
            rows.append(probing)
        rows = rows[-max(1, height - 8):]
        states = [h[1] for h in self.hosts[:done]]
        summary = newtext()
        if done >= total:
            summary.append(f"  {states.count('online')} online", style=pal["ok"])
            summary.append(f"  ·  {states.count('warning')} warning", style=pal["warn"])
            summary.append(f"  ·  {states.count('offline')} offline", style="dim")
        cells = max(10, min(32, width - 20))
        progress = done / total if total else 1.0
        filled = round(cells * progress)
        bar = newtext()
        bar.append("  ")
        bar.append("▰" * filled, style=pal["ok"])
        bar.append("▱" * (cells - filled), style="dim")
        bar.append(f"  {progress * 100:>3.0f}%", style="bold")
        lines = [Text(), head, Text(), status, Text(), *rows, Text(), bar, summary]
        return newtext("\n").join(lines)


BOOT_STYLES = {
    "crt": BootScreen,
    "glitch": GlitchBootScreen,
    "scan": ScanBootScreen,
}
