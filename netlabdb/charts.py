import math
from datetime import datetime, timedelta

from rich.color import Color
from rich.style import Style
from rich.text import Text

from .constants import BRAILLE_DOTS


PARTIAL_BLOCKS = " ▏▎▍▌▋▊▉"


def braille_grid(values, cols: int, rows: int, low: float, high: float, fill: bool = False) -> list[list[int]]:
    grid = [[0] * cols for _ in range(rows)]
    values = list(values)
    n, px_w, px_h = len(values), cols * 2, rows * 4
    if n == 0 or px_w < 2:
        return grid
    span = (high - low) or 1.0
    ys = []
    for x in range(px_w):
        if n > px_w:
            start = x * n // px_w
            v = max(values[start:max(start + 1, (x + 1) * n // px_w)])
        else:
            pos = x * (n - 1) / (px_w - 1)
            i = int(pos)
            v = values[i] if i >= n - 1 else values[i] + (values[i + 1] - values[i]) * (pos - i)
        ys.append(round(max(0.0, min(1.0, (v - low) / span)) * (px_h - 1)))
    previous = None
    for x, y in enumerate(ys):
        bottom, top = (y, y) if previous is None else (min(previous, y), max(previous, y))
        for dot in range(0 if fill else bottom, top + 1):
            grid[rows - 1 - dot // 4][x // 2] |= BRAILLE_DOTS[3 - dot % 4][x % 2]
        previous = y
    return grid


def line_chart(values, window: int, width: int, rows: int, low: float, high: float,
               label, stamp: datetime, pal: dict, max_cols: int = 96) -> list[Text]:
    step = 2 if rows < 13 else (rows - 1) // 4
    levels = [label(low + (high - low) * (1 - r / (rows - 1))) for r in range(0, rows, step)]
    gutter = max(len(t) for t in levels) + 1
    cols = max(10, min(width - gutter - 1, max_cols))
    grid = braille_grid(values, cols, rows, low, high)
    lines = []
    for r in range(rows):
        line = Text(no_wrap=True, overflow="crop")
        line.append(f"{levels[r // step] if r % step == 0 else '':>{gutter - 1}} ", style="dim")
        for bits in grid[r]:
            if bits:
                line.append(chr(0x2800 + bits), style=pal["accent"])
            else:
                line.append("┈" if r % step == 0 else " ", style="dim")
        lines.append(line)
    fmt = "%H:%M:%S" if window <= 300 else "%H:%M"
    count = max(2, min(5, cols // 14))
    axis = [" "] * cols
    for k in range(count):
        frac = k / (count - 1)
        text = (stamp - timedelta(seconds=window * (1 - frac))).strftime(fmt)
        start = max(0, min(cols - len(text), round(frac * (cols - 1)) - len(text) // 2))
        axis[start:start + len(text)] = list(text)
    lines.append(Text(" " * gutter + "".join(axis), style="dim", no_wrap=True, overflow="crop"))
    return lines


def contrast_color(color: str) -> str:
    c = Color.parse(color).get_truecolor()
    return "#121212" if 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue > 140 else "#ffffff"


def stacked_bar(slices: list[tuple], width: int, height: int = 3, labels: list | None = None,
                frame: str = "dim") -> list[Text]:
    total = sum(v for _, v, _ in slices) or 1.0
    spans, start = [], 0.0
    for _, value, color in slices:
        end = start + value / total * width
        spans.append((start, end, color))
        start = end
    spans[-1] = (spans[-1][0], float(width), spans[-1][2])

    def colour_at(position: float) -> str:
        return next((c for _, limit, c in spans if position < limit), spans[-1][2])

    base = []
    for cell in range(width):
        left, right = colour_at(cell + 0.001), colour_at(cell + 0.999)
        if left == right:
            base.append(("█", Style(color=left)))
            continue
        boundary = next(limit for _, limit, _ in spans if limit > cell + 0.001)
        eighths = round((boundary - cell) * 8)
        if eighths <= 0:
            base.append(("█", Style(color=right)))
        elif eighths >= 8:
            base.append(("█", Style(color=left)))
        else:
            base.append((PARTIAL_BLOCKS[eighths], Style(color=left, bgcolor=right)))

    overlay = {}
    for (begin, finish, color), label in zip(spans, labels or []):
        first, last = math.ceil(begin), math.floor(finish)
        if label and last - first >= len(label) + 2:
            for k, char in enumerate(label):
                overlay[first + 1 + k] = (char, color)

    rows = []
    for r in range(height):
        line = Text(no_wrap=True)
        line.append("│", style=frame)
        for cell in range(width):
            if r == height // 2 and cell in overlay:
                char, color = overlay[cell]
                line.append(char, style=Style(color=contrast_color(color), bgcolor=color, bold=True))
            else:
                line.append(base[cell][0], style=base[cell][1])
        line.append("│", style=frame)
        rows.append(line)
    return rows


def bar_ruler(width: int, marks: list[tuple], pal: dict) -> list[Text]:
    def place(chars: list, text: str, position: int, align: str) -> None:
        if align == "left":
            begin = 0
        elif align == "right":
            begin = width - len(text)
        else:
            begin = max(0, min(width - len(text), position - len(text) // 2))
        chars[begin:begin + len(text)] = list(text)

    labels = [" "] * width
    for fraction in (0, 25, 50, 75, 100):
        position = round(fraction / 100 * (width - 1))
        place(labels, f"{fraction}%", position, "left" if fraction == 0 else "right" if fraction == 100 else "mid")
    ticks = Text(" ", no_wrap=True)
    pointers = {round(pct / 100 * (width - 1)): color for pct, color in marks}
    for cell in range(width):
        ticks.append("▲" if cell in pointers else " ", style=pointers.get(cell))
    return [ticks, Text(" " + "".join(labels), style="dim", no_wrap=True)]
