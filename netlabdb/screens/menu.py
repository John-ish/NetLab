from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from ..config import STYLE_PATH
from ..constants import MENU_ENTRIES


class MenuItem(ListItem):
    def compose(self) -> ComposeResult:
        prefix = "❱ " if self.start_active else " "
        yield Label(f"{prefix}{self.item_text}", id="label")

    def __init__(self, text: str, id: str, active: bool = False):
        self.item_text = text
        self.start_active = active
        super().__init__(id=id, classes="-active" if active else "")

    def set_highlighted(self, is_highlighted: bool) -> None:
        label = self.query_one("#label", Label)
        prefix = "❱ " if is_highlighted else " "
        label.update(f"{prefix}{self.item_text}")
        self.set_class(is_highlighted, "-active")


class Main_menu(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("m", "dismiss", "Close Menu"),
        ("escape", "dismiss", "Close Menu"),
        *[(key, f"go('{route}')", text) for text, route, key in MENU_ENTRIES],
    ]

    def __init__(self, current: str | None = None):
        super().__init__()
        self.current_route = current

    def compose(self) -> ComposeResult:
        start = next((n for n, (_, route, _) in enumerate(MENU_ENTRIES) if route == self.current_route), 0)
        yield ListView(
            *[MenuItem(text, id=route, active=(n == start))
              for n, (text, route, _) in enumerate(MENU_ENTRIES)],
            initial_index=start,
        )

    def on_mount(self):
        list_view = self.query_one(ListView)
        list_view.border_title = "Main Menu"
        list_view.border_subtitle = "[↑/↓] nav [↵] Select"
        if list_view.highlighted_child:
            list_view.highlighted_child.set_highlighted(True)

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        for item in self.query(MenuItem):
            item.set_highlighted(False)
        if event.item is not None:
            event.item.set_highlighted(True)

    def on_list_view_selected(self, event: ListView.Selected):
        self.dismiss(event.item.id)

    def action_go(self, route: str) -> None:
        self.dismiss(route)
