def logo(color="blue", text="NETLAB", font="block", **extra):
    return {"type": "logo", "text": text, "font": font, "color": color, "fill_color": color, **extra}


def menu(**extra):
    return {"type": "menu", **extra}


def text(content, **extra):
    return {"type": "text", "text": content, **extra}


def box(content, title, color="yellow", **extra):
    return text(content, title=title, border="round", border_color=color, color=color, bold=True, **extra)


def stats(**extra):
    return {"type": "stats", **extra}


def hosts(**extra):
    return {"type": "hosts", **extra}


def alerts(**extra):
    return {"type": "alerts", **extra}


def activity(**extra):
    return {"type": "activity", **extra}


def column(width, *sections):
    return {"width": width, "sections": list(sections)}


def columns(*parts, **extra):
    return {"type": "columns", "columns": list(parts), **extra}


def preset(label, width, *sections):
    return {"label": label, "width": width, "sections": list(sections)}


PRESETS = {
    "classic": preset(
        "Classic", 72,
        logo("red"),
        menu(margin=2, width=36, keys=False),
        text("{user} on {system}", margin=2, color="blue"),
    ),
    "ecovim": preset(
        "Ecovim", 72,
        logo("blue"),
        box("◷ {now:%H:%M}", "Today is {now:%a %d %b}", margin=1, width=50),
        menu(margin=2, width=56),
        text("{online}/{hosts} hosts online   {services} services", margin=2, color="yellow", bold=True),
    ),
    "stats": preset(
        "Stats", 124,
        columns(
            column(
                "1fr",
                logo("blue"),
                stats(margin=1, border="round", border_color="blue", title="FLEET"),
                text("{now:%a %d %b %Y  %H:%M:%S}", color="blue"),
                text("NETLAB watching {hosts} hosts and {services} services", color="cyan", priority=5),
            ),
            column(
                "1fr",
                menu(margin=0),
                hosts(margin=2, lines=5, title="HOSTS"),
                alerts(margin=1, lines=4, title="ATTENTION"),
                activity(margin=1, lines=3, title="RECENT EVENTS", padding=0),
            ),
            gap=4, valign="middle",
        ),
    ),
    "snacks": preset(
        "Snacks", 124,
        columns(
            column(
                "5fr",
                logo("blue"),
                menu(margin=2),
                text("⚡ {online}/{hosts} hosts online, {services_up}/{services} services up",
                     margin=2, color="cyan", priority=5),
            ),
            column(
                "4fr",
                hosts(lines=6, title="Hosts", border="round", border_color="blue"),
                alerts(lines=4, title="Attention", border="round", border_color="yellow"),
                activity(lines=3, title="Recent events", border="round", border_color="cyan"),
            ),
            gap=6, valign="middle",
        ),
    ),
    "minimal": preset(
        "Minimal", 60,
        logo("accent", font="plain"),
        menu(margin=2, width=30, keys=False),
    ),
}