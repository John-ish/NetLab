from functools import lru_cache

from rich.color import Color, ColorType
from rich.segment import Segment
from rich.style import Style
from textual.color import Color as TColor
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget

from .settings import CRT_GLOW, CRT_INTENSITY, FLICKER_STRENGTH, settings
from .theme import THEME_STATE


BAND_SPEED = 1.1

CRT = {
    "enabled": False, "amount": 0.0, "glow": 0.0, "flicker_strength": 0.0,
    "patches": [], "seed": 0, "roll": False, "band": None,
}
CRT_DEPTH = [0]
TONE_MEMO = {}


def sync_crt() -> None:
    CRT["enabled"] = settings.get("crt_effect") == "on" and not THEME_STATE["terminal"]
    CRT["amount"] = CRT_INTENSITY.get(settings.get("crt_intensity"), 0.10)
    CRT["glow"] = CRT_GLOW.get(settings.get("crt_glow"), 0.0)
    CRT["flicker_strength"] = FLICKER_STRENGTH.get(settings.get("crt_flicker"), 0.0)
    CRT["roll"] = settings.get("crt_roll") == "on"
    if not CRT["enabled"]:
        CRT["glow"] = 0.0
    if not CRT["enabled"] or not CRT["flicker_strength"]:
        CRT["patches"] = []
    if not CRT["enabled"] or not CRT["roll"]:
        CRT["band"] = None


def _mix(value, target: float, amount: float):
    red, green, blue = value.get_truecolor()
    return (red + (target - red) * amount, green + (target - green) * amount, blue + (target - blue) * amount)


@lru_cache(maxsize=16384)
def _tone_style(style: Style, amount: float, glow: float) -> Style:
    changes = {}
    fg, bg = style.color, style.bgcolor
    if bg is not None and bg.type not in (ColorType.TRUECOLOR, ColorType.EIGHT_BIT):
        bg = None
    if fg is not None and fg.type not in (ColorType.TRUECOLOR, ColorType.EIGHT_BIT):
        fg = None
    if bg is not None:
        channels = _mix(bg, 255, glow * 0.05) if glow else tuple(bg.get_truecolor())
        if amount >= 0:
            channels = tuple(c * (1 - amount) for c in channels)
        else:
            channels = tuple(c + (255 - c) * -amount for c in channels)
        changes["bgcolor"] = Color.from_rgb(*(int(c) for c in channels))
    if fg is not None:
        channels = _mix(fg, 255, glow * 0.3) if glow else tuple(fg.get_truecolor())
        factor = amount * 0.5
        if factor >= 0:
            channels = tuple(c * (1 - factor) for c in channels)
        else:
            channels = tuple(c + (255 - c) * -factor for c in channels)
        changes["color"] = Color.from_rgb(*(int(c) for c in channels))
    return style + Style(**changes) if changes else style


def _tone_strip(strip: Strip, amount: float, glow: float) -> Strip:
    segments = [
        segment if segment.control or segment.style is None
        else Segment(segment.text, _tone_style(segment.style, amount, glow), segment.control)
        for segment in strip
    ]
    return Strip(segments, strip.cell_length)


def _tone_cached(strip: Strip, amount: float, glow: float) -> Strip:
    hit = TONE_MEMO.get(id(strip))
    if hit is not None and hit[0] is strip and hit[1] == amount and hit[2] == glow:
        return hit[3]
    toned = _tone_strip(strip, amount, glow)
    if len(TONE_MEMO) > 6000:
        TONE_MEMO.clear()
    TONE_MEMO[id(strip)] = (strip, amount, glow, toned)
    return toned


def _row_amount(row: int) -> float:
    amount = CRT["amount"] if row % 2 else 0.0
    for top, bottom, level, _ in CRT["patches"]:
        if top <= row < bottom:
            amount += level * (0.5 + ((row * 2654435761 + CRT["seed"] * 40503) % 1000) / 1000)
    band = CRT["band"]
    if band is not None:
        center, half, peak = band
        distance = abs(row - center)
        if distance < half:
            amount -= peak * (1 - distance / half)
    return round(amount * 50) / 50


def _crt_wrap(original):
    def render_lines(self, crop):
        CRT_DEPTH[0] += 1
        try:
            strips = original(self, crop)
        finally:
            CRT_DEPTH[0] -= 1
        if CRT_DEPTH[0] or not CRT["enabled"]:
            return strips
        try:
            top = self.region.y + crop.y
        except Exception:
            return strips
        glow = CRT["glow"]
        result = []
        for index, strip in enumerate(strips):
            amount = _row_amount(top + index)
            result.append(_tone_cached(strip, amount, glow) if amount or glow else strip)
        return result
    return render_lines


def install_crt() -> None:
    for cls in (Widget, ScrollView):
        original = cls.__dict__.get("render_lines")
        if original is not None:
            setattr(cls, "render_lines", _crt_wrap(original))


@lru_cache(maxsize=8192)
def _tint_style(style, color) -> Style:
    base = Style() if style is None else style.clear_meta_and_links()
    if color.a == 0:
        return base
    return base + Style.from_color(
        (TColor.from_rich_color(base.color) + color).rich_color if base.color is not None else None,
        (TColor.from_rich_color(base.bgcolor) + color).rich_color if base.bgcolor is not None else None,
    )


def _fast_process_segments(cls, segments, color):
    for segment in segments:
        if segment.control:
            yield segment
        else:
            yield Segment(segment.text, _tint_style(segment.style, color), segment.control)


def install_fast_background() -> None:
    try:
        from textual.renderables.background_screen import BackgroundScreen
        BackgroundScreen.process_segments = classmethod(_fast_process_segments)
    except Exception:
        pass


sync_crt()
install_crt()
install_fast_background()
