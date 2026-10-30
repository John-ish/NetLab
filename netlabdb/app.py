import gc
import random
import time

from textual.app import App, ComposeResult
from textual.geometry import Region
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer

from .config import STYLE_PATH
from .constants import LIVE_REFRESH_SECONDS
from .crt import BAND_SPEED, CRT, TONE_MEMO, sync_crt
from .errors import DatabaseError
from .live import live
from .screens.boot import BOOT_STYLES, BootScreen
from .screens.hosts import HostClass
from .screens.logs import LogsClass
from .screens.menu import Main_menu
from .screens.services import ServicesClass
from .screens.settings_screen import SettingsScreen
from .screens.startup import StartupScreen
from .settings import settings
from .store import store
from .theme import PALETTE, THEME_FALLBACKS, THEME_STATE, build_theme_state


class netlabdb(App):

    CSS_PATH = STYLE_PATH

    BINDINGS = [("m", "main_menu", "Main Menu")]

    menu_origin: str | None = None

    routes = {
        "startup": StartupScreen,
        "hosts": HostClass,
        "services": ServicesClass,
        "logs": LogsClass,
        "settings": SettingsScreen,
    }

    def compose(self) -> ComposeResult:
        yield Footer()

    def __init__(self):
        super().__init__()
        self.apply_theme()
        self.next_flicker = time.monotonic() + random.uniform(2, 5)
        self.band_pos = None
        self.next_band = time.monotonic() + random.uniform(2, 4)
        self.live_queued = False
        self.fast_depth = 0
        self.fast_block = 0.0

    def on_mount(self) -> None:
        self.load_database()
        self.start_live()
        gc.collect()
        gc.freeze()
        gc.set_threshold(50000, 50, 1000)
        self.set_interval(1 / 15, self.crt_tick)
        if settings.get("startup_animation") == "on":
            self.push_screen(self.boot_screen(), callback=self.boot_finished)
        else:
            self.open_default()

    def load_database(self) -> None:
        try:
            store.load()
        except DatabaseError as error:
            self.notify(f"Database unavailable: {error}. Hosts will not be saved.",
                        severity="error", timeout=12)
            return
        if store.unreadable:
            self.notify(f"{store.unreadable} saved password(s) could not be decrypted. Is ~/.netlabdb/secret.key the original?",
                        severity="error", timeout=12)

    def start_live(self) -> None:
        if store.persistent:
            store.start_writer(self.writer_error)
            live.start(self.live_refresh, self.live_error)

    def live_refresh(self) -> None:
        if self.live_queued:
            return
        self.live_queued = True
        self.set_timer(LIVE_REFRESH_SECONDS, self.live_flush)

    def live_flush(self) -> None:
        self.live_queued = False
        for screen in reversed(self.screen_stack):
            if isinstance(screen, ModalScreen):
                continue
            update = getattr(screen, "live_update", None)
            if update is not None:
                try:
                    update()
                except Exception:
                    pass
            break

    def writer_error(self, message: str) -> None:
        try:
            self.call_from_thread(live._db_failed, message)
        except Exception:
            pass

    def live_error(self, message: str) -> None:
        self.notify(message, severity="error", timeout=10)

    def on_unmount(self) -> None:
        live.stop()
        store.stop_writer()
        store.db.close()

    def boot_screen(self) -> Screen:
        style = settings.get("startup_style")
        if style == "random":
            style = random.choice(list(BOOT_STYLES))
        return BOOT_STYLES.get(style, BootScreen)()

    def boot_finished(self, result) -> None:
        self.open_default()

    def open_default(self) -> None:
        screen_class = self.routes.get(settings.get("default_screen"), StartupScreen)
        self.push_screen(screen_class())

    def fast_repaint(self, rows: tuple) -> bool:
        try:
            screen = self.screen
            compositor = screen._compositor
            if screen._layout_required or self._batch_count or not screen.is_current:
                return False
            if compositor.size != self.size or compositor._full_map_invalidated:
                return False
            width, height = self.size
            top, bottom = max(0, int(rows[0])), min(height, int(rows[1]))
            if bottom <= top:
                return True
            if len(compositor.cuts) < bottom:
                return False
            if screen._dirty_widgets:
                compositor.update_widgets(screen._dirty_widgets)
            compositor._dirty_regions.add(Region(0, top, width, bottom - top))
            update = compositor.render_update(screen_stack=self._background_screens)
            spans, chops = getattr(update, "spans", None), getattr(update, "chops", None)
            if spans and chops is not None and max(y for y, _, _ in spans) >= len(chops):
                screen.refresh()
                return True
            self._display(screen, update)
            screen._dirty_widgets.clear()
            return True
        except Exception:
            return False

    def repaint(self, rows: tuple | None = None) -> None:
        if rows is not None and self.fast_repaint(rows):
            return
        for screen in reversed(self.screen_stack):
            try:
                targets = [(widget, geometry[0]) for widget, geometry in screen._compositor.visible_widgets.items()]
            except Exception:
                targets = None
            if targets is None:
                for widget in screen.walk_children(with_self=True):
                    if rows is not None:
                        try:
                            region = widget.region
                        except Exception:
                            continue
                        if region.bottom <= rows[0] or region.y >= rows[1]:
                            continue
                    widget.refresh()
            else:
                for widget, region in targets:
                    if rows is not None and (region.bottom <= rows[0] or region.y >= rows[1]):
                        continue
                    widget.refresh()
            if not isinstance(screen, ModalScreen):
                break

    def apply_theme(self) -> None:
        state = build_theme_state(settings.get("theme"), settings.get("accent"), settings.get("transparent") == "on")
        THEME_STATE["terminal"], THEME_STATE["ansi"] = state["terminal"], state["ansi"]
        PALETTE.update(state["palette"])
        TONE_MEMO.clear()
        self.register_theme(state["theme"])
        self.ansi_color = state["ansi"]
        self.theme = state["theme"].name

    def get_css_variables(self) -> dict:
        variables = super().get_css_variables()
        for key, value in THEME_FALLBACKS.items():
            variables.setdefault(key, value)
        return variables

    def apply_settings(self) -> None:
        self.apply_theme()
        sync_crt()
        self.repaint()

    def crt_tick(self) -> None:
        if not CRT["enabled"] or not (CRT["flicker_strength"] or CRT["roll"]):
            return
        now = time.monotonic()
        strength = CRT["flicker_strength"]
        height = max(1, self.size.height)
        if strength:
            old = CRT["patches"]
            fresh = [(top, bottom, -level * 0.75, life - 1) for top, bottom, level, life in old if life > 1]
            if now >= self.next_flicker:
                for _ in range(random.randint(1, 3)):
                    span = random.randint(2, 9)
                    top = random.randint(0, max(0, height - span))
                    level = strength * 1.6 * random.choice((1, 1, -1))
                    fresh.append((top, top + span, level, random.randint(3, 6)))
                self.next_flicker = now + random.uniform(1.2, 4.5)
            CRT["patches"] = fresh
            CRT["seed"] += 1
            spans = [(top, bottom) for top, bottom, _, _ in old + fresh]
            if spans:
                self.repaint((min(t for t, _ in spans), max(b for _, b in spans)))
        if CRT["roll"]:
            old_pos = self.band_pos
            if self.band_pos is None:
                if now >= self.next_band:
                    self.band_pos = -4.0
            else:
                self.band_pos += BAND_SPEED
                if self.band_pos > height + 4:
                    self.band_pos = None
                    self.next_band = now + random.uniform(2, 5)
            half = 4.0
            CRT["band"] = None if self.band_pos is None else (self.band_pos, half, 0.06 + CRT["amount"] * 0.5)
            points = [pos for pos in (old_pos, self.band_pos) if pos is not None]
            if points:
                self.repaint((int(min(points) - half) - 1, int(max(points) + half) + 2))

    def action_main_menu(self):
        if isinstance(self.screen, BootScreen):
            return
        current = next(
            (key for key, cls in self.routes.items() if isinstance(self.screen, cls)),
            None,
        )
        self.menu_origin = current
        self.push_screen(Main_menu(current), callback=self.routing)

    def routing(self, result: str | None):
        if result is None or result == self.menu_origin:
            return
        screen_class = self.routes.get(result)
        if screen_class is not None:
            while len(self.screen_stack) > 2:
                self.pop_screen()
            if len(self.screen_stack) == 2:
                self.switch_screen(screen_class())
            else:
                self.push_screen(screen_class())


def main() -> None:
    netlabdb().run()
