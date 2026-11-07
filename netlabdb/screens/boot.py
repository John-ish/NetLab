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
from ..dashboard import animation_logo, animation_tagline, boot_title, kind_of, mix_color
from ..helpers import newtext, palette
from ..state import SERVICES
from ..store import store
from ..theme import PALETTE


BOOT_LINE = 0.30
BOOT_GROW = 0.30
BOOT_FADE = 0.30
BOOT_LOG_START = BOOT_LINE + BOOT_GROW + BOOT_FADE
BOOT_STEP = 0.13
BOOT_HOLD = 0.5
TYPE_STEP = 0.03
WHITE = TColor(255, 255, 255)


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
        head.append(f"  {boot_title()}", style=f"bold {pal['accent']}")
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


class LogoBootScreen(BootScreen):

    def __init__(self):
        super().__init__()
        self.total = 3.0
        self.ready = False
        self.lines = []
        self.font = "block"
        self.logo_width = 0
        self.left = 0
        self.tagline = ""
        self.fill = self.shadow = self.accent = ""

    def prepare(self, width: int) -> None:
        pass

    def compose_frame(self, t: float, width: int, height: int) -> Text:
        raise NotImplementedError

    def _frame(self) -> None:
        t = time.monotonic() - self.begin
        boot = self.query_one("#boot", Static)
        width, height = boot.size
        if width < 4 or height < 3:
            return
        if t >= self.total:
            self._finish()
            return
        if not self.ready:
            self.lines, self.font, self.fill, self.shadow = animation_logo(width - 2)
            self.logo_width = len(self.lines[0])
            self.accent = PALETTE["accent"]
            self.tagline = animation_tagline()
            self.ready = True
            self.prepare(width)
        self.left = max(0, (width - self.logo_width) // 2)
        boot.update(self.compose_frame(t, width, height))

    def glyph_style(self, char: str) -> str:
        kind = kind_of(char, self.font)
        if kind == "fill":
            return f"bold {self.fill}"
        return self.shadow if kind == "shadow" else ""

    def assemble(self, height: int, row, tag: Text) -> Text:
        count = len(self.lines)
        top = max(0, (height - count - 2) // 2)
        out = []
        for r in range(height):
            if top <= r < top + count:
                out.append(row(r - top))
            elif r == top + count + 1:
                out.append(tag)
            else:
                out.append(Text())
        return Text("\n").join(out)

    def tag_line(self, width: int, typed: int, cursor: str) -> Text:
        pad = " " * max(0, (width - len(self.tagline)) // 2)
        return Text.assemble(pad, (self.tagline[:typed], "dim"), (cursor, self.accent))

    def faded_tag(self, width: int, t: float, start: float) -> Text:
        alpha = max(0.0, min(1.0, (t - start) / 0.6))
        pad = " " * max(0, (width - len(self.tagline)) // 2)
        return Text.assemble(pad, (self.tagline, mix_color(self.fill, PALETTE["bg"], 1 - 0.55 * alpha)))

    def row_start(self) -> Text:
        line = Text(no_wrap=True, overflow="crop")
        line.append(" " * self.left)
        return line


class GlitchBootScreen(LogoBootScreen):

    NOISE = "░▒▓█▚▞▌▐#%&@01<>/\\|"

    def prepare(self, width: int) -> None:
        rng = random.Random(7)
        size = self.logo_width
        self.settle = [0.2 + (c / size) * 1.1 + rng.uniform(0, 0.3) for c in range(size)]
        self.total = max(3.0, 1.7 + len(self.tagline) * TYPE_STEP + 0.5)

    def compose_frame(self, t: float, width: int, height: int) -> Text:
        glitching = 0.3 < t < 1.9

        def row(index: int) -> Text:
            line = Text(no_wrap=True, overflow="crop")
            shift = random.choice((-4, -3, 3, 4)) if glitching and random.random() < 0.12 else 0
            line.append(" " * max(0, self.left + shift))
            for column, char in enumerate(self.lines[index]):
                if t >= self.settle[column]:
                    line.append(char, style=self.glyph_style(char))
                elif char != " " or random.random() < 0.03:
                    line.append(random.choice(self.NOISE), style=random.choice((self.accent, "dim", self.fill)))
                else:
                    line.append(" ")
            return line

        typed = int(max(0.0, t - 1.7) / TYPE_STEP)
        cursor = "█" if int(t * 4) % 2 == 0 else " "
        return self.assemble(height, row, self.tag_line(width, typed, cursor))


class SweepBootScreen(LogoBootScreen):

    def prepare(self, width: int) -> None:
        self.fade_end = 0.9
        self.sweep_start = 0.7
        self.sweep_time = 1.2
        self.band = max(5, self.logo_width // 9)
        self.slant = 2
        self.tag_start = self.sweep_start + 0.5
        self.total = self.sweep_start + self.sweep_time + 1.1
        self.glow = {}

    def glow_color(self, base: str, level: int) -> str:
        key = (base, level)
        if key not in self.glow:
            self.glow[key] = mix_color(base, WHITE, level / 8 * 0.9)
        return self.glow[key]

    def compose_frame(self, t: float, width: int, height: int) -> Text:
        bg = PALETTE["bg"]
        k = min(1.0, t / self.fade_end)
        k = k * k * (3 - 2 * k)
        fill = mix_color(self.fill, bg, 1 - k)
        shadow = mix_color(self.shadow, bg, 1 - k)
        progress = (t - self.sweep_start) / self.sweep_time
        span = self.logo_width + len(self.lines) * self.slant + 2 * self.band
        center = -self.band + progress * span

        def row(index: int) -> Text:
            line = self.row_start()
            offset = index * self.slant
            for column, char in enumerate(self.lines[index]):
                kind = kind_of(char, self.font)
                if kind is None:
                    line.append(char)
                    continue
                base = fill if kind == "fill" else shadow
                distance = abs(column + offset - center)
                if distance < self.band:
                    level = round((1 - distance / self.band) * 8)
                    line.append(char, style=f"bold {self.glow_color(base, level)}")
                else:
                    line.append(char, style=f"bold {base}" if kind == "fill" else base)
            return line

        return self.assemble(height, row, self.faded_tag(width, t, self.tag_start))


class SlideBootScreen(LogoBootScreen):

    def prepare(self, width: int) -> None:
        self.stagger = 0.09
        self.duration = 0.8
        self.tag_start = len(self.lines) * self.stagger + self.duration + 0.1
        self.total = self.tag_start + 1.4

    def compose_frame(self, t: float, width: int, height: int) -> Text:
        bg = PALETTE["bg"]

        def row(index: int) -> Text:
            progress = max(0.0, min(1.0, (t - index * self.stagger) / self.duration))
            ease = 1 - (1 - progress) ** 3
            direction = -1 if index % 2 == 0 else 1
            position = self.left + direction * round((1 - ease) * width)
            fade = (1 - ease) * 0.7
            fill = mix_color(self.fill, bg, fade)
            shadow = mix_color(self.shadow, bg, fade)
            start, skip = max(0, position), max(0, -position)
            visible = self.lines[index][skip:skip + max(0, width - start)]
            line = Text(no_wrap=True, overflow="crop")
            line.append(" " * start)
            for char in visible:
                kind = kind_of(char, self.font)
                if kind == "fill":
                    line.append(char, style=f"bold {fill}")
                elif kind == "shadow":
                    line.append(char, style=shadow)
                else:
                    line.append(char)
            return line

        return self.assemble(height, row, self.faded_tag(width, t, self.tag_start))


class FadeBootScreen(LogoBootScreen):

    def prepare(self, width: int) -> None:
        self.fade_end = 1.3
        self.tag_start = 1.2
        self.total = self.fade_end + 1.4

    def compose_frame(self, t: float, width: int, height: int) -> Text:
        bg = PALETTE["bg"]
        k = min(1.0, t / self.fade_end)
        k = k * k * (3 - 2 * k)
        fill = mix_color(self.fill, bg, 1 - k)
        shadow = mix_color(self.shadow, bg, 1 - k)

        def row(index: int) -> Text:
            line = self.row_start()
            for char in self.lines[index]:
                kind = kind_of(char, self.font)
                if kind == "fill":
                    line.append(char, style=f"bold {fill}")
                elif kind == "shadow":
                    line.append(char, style=shadow)
                else:
                    line.append(char)
            return line

        return self.assemble(height, row, self.faded_tag(width, t, self.tag_start))


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
        head.append(f"  {boot_title()}", style=f"bold {pal['accent']}")
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
    "sweep": SweepBootScreen,
    "slide": SlideBootScreen,
    "fade": FadeBootScreen,
}