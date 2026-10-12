#!/usr/bin/env python3
"""Record AT-SPI events and resolve real pointer clicks through AT-SPI."""

from __future__ import annotations

import collections
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

os.environ.setdefault("DISPLAY", ":0")
if not os.environ.get("XAUTHORITY") and os.path.exists(f"/run/user/{os.getuid()}/gdm/Xauthority"):
    os.environ["XAUTHORITY"] = f"/run/user/{os.getuid()}/gdm/Xauthority"
os.environ.setdefault(
    "DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus"
)

import gi  # noqa: E402
from Xlib import X, display  # noqa: E402
from Xlib.ext import record  # noqa: E402
from Xlib.protocol import rq  # noqa: E402

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402


Atspi.init()
output = os.environ.get("EVENT_OUT", "/tmp/event_clicks.jsonl")
output_file = open(output, "a", encoding="utf-8", buffering=1)
sequence = 0
write_lock = threading.Lock()
click_queue: queue.Queue[
    tuple[
        int,
        int,
        str,
        int,
        str,
        bool,
        list[str],
        list[int] | None,
    ]
] = queue.Queue(
    maxsize=64
)
pointer_state_lock = threading.Lock()
pending_clicks: collections.deque[dict[str, Any]] = collections.deque(maxlen=64)
resolved_pointer_seqs: set[int] = set()
recent_menu_item: dict[str, Any] = {}
recent_chrome_focus_control: dict[str, Any] = {}
recent_transient_hover_control: dict[str, Any] = {}
recent_transient_focus_control: dict[str, Any] = {}
libreoffice_hit_test_lock = threading.Lock()
last_key: object = None
last_time = 0.0
skip_roles = {
    "filler",
    "panel",
    "root pane",
    "scroll pane",
    "layered pane",
    "redundant object",
    "section",
}
skip_apps = ("gjs", "mutter-x11-frames", "gnome-shell")
max_depth = 18
hit_test_budget_seconds = 0.75
hit_test_timeout_seconds = 1.0
pointer_correlation_seconds = 1.5
menu_cache_seconds = 2.0
chrome_focus_cache_seconds = 1.5
null_bbox_correlation_seconds = 0.35
menu_event_correlation_seconds = 0.2
transient_control_cache_seconds = 30.0
transient_hover_poll_seconds = 0.05
transient_hover_refresh_seconds = 5.0
max_fallback_nodes = 600
hit_test_workers = 2
hit_foreground_title = os.environ.get("HIT_FOREGROUND_TITLE", "").strip()
hit_showing_desktop = os.environ.get("HIT_SHOWING_DESKTOP") == "1"
hit_foreground_classes = [
    value.strip()
    for value in os.environ.get("HIT_FOREGROUND_CLASSES", "").split(",")
    if value.strip()
]
try:
    parsed_hit_foreground_bbox = json.loads(
        os.environ.get("HIT_FOREGROUND_BBOX", "null")
    )
except json.JSONDecodeError:
    parsed_hit_foreground_bbox = None
hit_foreground_bbox = (
    [int(value) for value in parsed_hit_foreground_bbox]
    if isinstance(parsed_hit_foreground_bbox, list)
    and len(parsed_hit_foreground_bbox) == 4
    else None
)
coarse_roles = {
    "application",
    "desktop frame",
    "document web",
    "frame",
    "section",
    "window",
}
interactive_roles = {
    "push button",
    "button",
    "link",
    "check box",
    "radio button",
    "combo box",
    "menu item",
    "list item",
    "tab",
    "toggle button",
    "entry",
    "text",
    "spin button",
    "slider",
    "menu",
    "page tab",
}
transient_click_apps = {"org.gnome.nautilus", "thunderbird", "vlc"}
transient_click_roles = {
    "push button",
    "button",
    "check box",
    "combo box",
    "menu item",
    "radio button",
    "slider",
    "spin button",
    "toggle button",
}
chrome_focus_roles = {
    "push button",
    "button",
    "menu item",
    "toggle button",
    "link",
}


def safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def mouse() -> list[int | None]:
    try:
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        values = dict(
            line.split("=", 1) for line in result.stdout.strip().splitlines()
        )
        return [int(values["X"]), int(values["Y"])]
    except Exception:
        return [None, None]


def application_name(node: Any) -> str | None:
    application = safe(node.get_application)
    return safe(application.get_name) if application else None


def application_skipped(name: str | None) -> bool:
    lowered = (name or "").lower()
    return any(value in lowered for value in skip_apps)


def node_info(node: Any, app: str | None = None) -> dict[str, Any]:
    role = safe(node.get_role_name)
    name = safe(node.get_name, "") or ""
    description = safe(node.get_description, "") or ""
    label_source = "name" if name else "description"
    if not name:
        name = description
    if not name:
        parent = safe(node.get_parent)
        if parent is not None:
            name = (
                safe(parent.get_name, "")
                or safe(parent.get_description, "")
                or ""
            )
            if name:
                label_source = "parent"
    extents = safe(lambda: node.get_extents(Atspi.CoordType.SCREEN))
    bbox = (
        [int(extents.x), int(extents.y), int(extents.width), int(extents.height)]
        if extents and extents.width > 0 and extents.height > 0
        else None
    )
    return {
        "app": app if app is not None else application_name(node),
        "role": role,
        "name": name,
        "description": description,
        "label_source": label_source if name else None,
        "bbox": bbox,
    }


def contains(bbox: list[int] | None, x: int, y: int) -> bool:
    return bool(
        bbox
        and bbox[0] <= x < bbox[0] + bbox[2]
        and bbox[1] <= y < bbox[1] + bbox[3]
    )


def normalized_app_identity(value: object) -> str:
    return "".join(
        character
        for character in str(value or "").casefold()
        if character.isalnum()
    )


def is_chromium_app(value: object) -> bool:
    identity = normalized_app_identity(value)
    return identity in {"googlechrome", "chromium", "chromiumbrowser"}


def write_item(item: dict[str, Any]) -> int:
    global sequence
    with write_lock:
        sequence += 1
        item = {
            "seq": sequence,
            "ts": round(time.time(), 3),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **item,
        }
        line = json.dumps(item, ensure_ascii=False)
        output_file.write(line + "\n")
        print(line, flush=True)
        return sequence


def node_is_active(node: Any) -> bool:
    states = safe(node.get_state_set)
    return bool(
        states
        and safe(lambda: states.contains(Atspi.StateType.ACTIVE), False)
    )


def compact_named_surface(info: dict[str, Any] | None) -> bool:
    """Recognize only bounded app-specific rows exposed as a section.

    Thunderbird exposes folder/message rows as 17--46 px high sections, and
    VS Code exposes compact notifications the same way.  Large page/editor
    sections are intentionally excluded.
    """
    if not info:
        return False
    app = str(info.get("app") or "").strip().casefold()
    role = str(info.get("role") or "").strip().casefold()
    name = str(info.get("name") or "").strip()
    bbox = info.get("bbox")
    if not (
        role == "section"
        and name
        and isinstance(bbox, list)
        and len(bbox) == 4
        and 1 < int(bbox[2]) <= 1000
        and 1 < int(bbox[3]) <= 120
    ):
        return False
    if "thunderbird" in app:
        return True
    if app == "code":
        left, top, width, height = (int(value) for value in bbox)
        return left >= 1000 and top >= 700 and width <= 600 and height <= 120
    return False


def refine_compact_named_surface(
    info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Replace provider-generic ``section`` with a truthful semantic role."""
    if not compact_named_surface(info):
        return info
    assert info is not None
    app = str(info.get("app") or "").strip().casefold()
    bbox = info.get("bbox") or [0, 0, 0, 0]
    if app == "code":
        role = "notification"
        label_source = "vscode-notification"
    elif int(bbox[2]) <= 260 and int(bbox[3]) <= 25:
        role = "folder row"
        label_source = "thunderbird-folder-row"
    else:
        role = "message row"
        label_source = "thunderbird-message-row"
    return {
        **info,
        "role": role,
        "label_source": label_source,
    }


def gimp_canvas_allowed(foreground_title: str) -> bool:
    """Return true for a GIMP document window, never a transient dialog."""
    title = foreground_title.strip().casefold()
    return bool(
        title
        and (
            title.endswith(" - gimp")
            or title.endswith(" – gimp")
            or title == "gnu image manipulation program"
        )
    )


def coarse_surface_target(
    info: dict[str, Any] | None,
    foreground_title: str,
    x: int,
    y: int,
) -> dict[str, Any] | None:
    """Give inaccessible painted canvases an app-scoped semantic name."""
    if not info:
        return None
    app = str(info.get("app") or "").strip().casefold()
    role = str(info.get("role") or "").strip().casefold()
    bbox = info.get("bbox")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and contains(bbox, x, y)
    ):
        return None
    title = foreground_title.strip() or str(info.get("name") or "").strip()
    lowered_title = title.casefold()

    if app == "gedit" and role in {"frame", "panel"} and title:
        document = title.rsplit(" - gedit", 1)[0].lstrip("*").strip()
        return {
            **info,
            "role": "text editor",
            "name": f"Text editor — {document}" if document else "Text editor",
            "description": "Editable text document surface",
            "label_source": "gedit-document-surface",
        }

    if app == "eog" and role in {"frame", "panel"} and title:
        return {
            **info,
            "role": "image canvas",
            "name": f"Image canvas — {title}",
            "description": "Displayed image surface",
            "label_source": "eog-image-surface",
        }

    if (
        app == "gimp"
        and role in {"filler", "panel", "frame"}
        and gimp_canvas_allowed(title)
        and lowered_title != "gnu image manipulation program"
    ):
        left, top, width, height = (int(value) for value in bbox)
        # Exclude the toolbox/options dock, right brushes/layers dock, menu and
        # rulers, plus the bottom status bar. Only the stable central document
        # workspace is eligible for this fallback.
        side_margin = max(210, int(width * 0.12))
        if (
            width >= 900
            and height >= 600
            and left + side_margin <= x < left + width - side_margin
            and top + 128 <= y < top + height - 38
        ):
            return {
                **info,
                "role": "canvas",
                "name": gimp_canvas_label(title),
                "description": "Editable image canvas",
                "label_source": "gimp-document-workspace",
            }

    if (
        app == "vlc"
        and role in {"filler", "panel"}
        and "vlc media player" in lowered_title
        and not any(
            value in lowered_title
            for value in {"preferences", "adjustments and effects", "open media"}
        )
    ):
        media = title.rsplit(" - VLC media player", 1)[0].strip()
        return {
            **info,
            "role": "media canvas",
            "name": f"Media canvas — {media}" if media else "Media canvas",
            "description": "VLC playback surface",
            "label_source": "vlc-media-surface",
        }

    if (
        app == "code"
        and role in {"panel", "section"}
        and "visual studio code" in lowered_title
        and not lowered_title.startswith(("settings", "welcome"))
    ):
        left, top, width, height = (int(value) for value in bbox)
        document = title.rsplit(" - Visual Studio Code", 1)[0].strip()
        if y >= top + height - 34:
            surface_role = "status bar"
            surface_name = "Visual Studio Code status bar"
        elif y >= top + int(height * 0.68):
            surface_role = "terminal"
            surface_name = "Integrated Terminal"
        elif x >= left + 250 and y >= top + 55:
            surface_role = "code editor"
            surface_name = (
                f"Code editor — {document}" if document else "Code editor"
            )
        else:
            return None
        return {
            **info,
            "role": surface_role,
            "name": surface_name,
            "description": "Visual Studio Code painted surface",
            "label_source": "vscode-layout-surface",
        }
    return None


def target_is_precise(info: dict[str, Any] | None) -> bool:
    if not info:
        return False
    if compact_named_surface(info):
        return True
    role = str(info.get("role") or "").strip().lower()
    name = str(info.get("name") or "").strip()
    app = str(info.get("app") or "").strip().lower()
    if (
        app == "code"
        and info.get("label_source") == "parent"
        and role in {"table cell", "list item", "tree item"}
    ):
        return False
    if role in skip_roles and info.get("label_source") != "name":
        return False
    # A bounding box alone is not semantic control information. In particular,
    # LibreOffice can emit focus events from an unnamed internal text child
    # while the named combo-box panel is available through point lookup. Do
    # not let that empty event win the correlation race.
    return bool(role and role not in coarse_roles and name)


def refine_calc_name_box(
    info: dict[str, Any] | None,
    foreground_title: str,
) -> dict[str, Any] | None:
    """Name Calc's range selector when LibreOffice exposes only its wrapper.

    This is deliberately tied to Calc's unique accessibility hint and compact
    Name Box geometry.  Writer and Impress can expose similar internal panels,
    so the foreground application check is part of the rule rather than merely
    a ranking preference.
    """
    if not info or "libreoffice calc" not in foreground_title.casefold():
        return info
    role = str(info.get("role") or "").strip().casefold()
    name = str(info.get("name") or "").strip().casefold()
    bbox = info.get("bbox")
    if (
        str(info.get("app") or "").strip().casefold() == "soffice"
        and role == "panel"
        and info.get("label_source") == "parent"
        and name
        == "please press enter to go into child control for more operations"
        and isinstance(bbox, list)
        and len(bbox) == 4
        and 50 <= int(bbox[2]) <= 260
        and 20 <= int(bbox[3]) <= 50
    ):
        return {
            **info,
            "role": "combo box",
            "name": "Name Box",
            "description": "Cell or range name selector",
            "label_source": "libreoffice-name-box",
        }
    return info


def settings_descendant_label(node: Any, max_nodes: int = 120) -> str:
    """Read an Adwaita action-row title without applying it to other apps."""
    pending: collections.deque[Any] = collections.deque([node])
    visited = 0
    labels: list[tuple[int, int, str]] = []
    depths: collections.deque[int] = collections.deque([0])
    while pending and visited < max_nodes:
        current = pending.popleft()
        depth = depths.popleft()
        visited += 1
        role = str(safe(current.get_role_name, "") or "").strip().lower()
        name = str(safe(current.get_name, "") or "").strip()
        if (
            current is not node
            and role == "label"
            and name
            and name.casefold() not in {"on", "off"}
        ):
            extents = safe(lambda: current.get_extents(Atspi.CoordType.SCREEN))
            visible = int(
                bool(
                    extents
                    and extents.x > -100000
                    and extents.y > -100000
                    and extents.width > 1
                    and extents.height > 1
                )
            )
            labels.append((visible, -depth, name))
        count = int(safe(current.get_child_count, 0) or 0)
        for index in range(count):
            child = safe(lambda index=index: current.get_child_at_index(index))
            if child is not None:
                pending.append(child)
                depths.append(depth + 1)
    return max(labels, default=(0, 0, ""))[2]


def code_table_cell_label(node: Any, max_nodes: int = 40) -> str:
    """Read the actual filename below a VS Code GTK file-dialog table cell."""
    parent = safe(node.get_parent)
    parent_name = str(safe(parent.get_name, "") or "").strip().casefold()
    pending: collections.deque[Any] = collections.deque()
    count = int(safe(node.get_child_count, 0) or 0)
    for index in range(count):
        child = safe(lambda index=index: node.get_child_at_index(index))
        if child is not None:
            pending.append(child)
    visited = 0
    labels: list[tuple[int, str]] = []
    while pending and visited < max_nodes:
        current = pending.popleft()
        visited += 1
        name = str(safe(current.get_name, "") or "").strip()
        description = str(safe(current.get_description, "") or "").strip()
        value = name or description
        role = str(safe(current.get_role_name, "") or "").strip().lower()
        if value and value.casefold() != parent_name:
            semantic = int(role in {"label", "static", "text", "table cell"})
            labels.append((semantic, value))
        child_count = int(safe(current.get_child_count, 0) or 0)
        for index in range(child_count):
            child = safe(lambda index=index: current.get_child_at_index(index))
            if child is not None:
                pending.append(child)
    return max(labels, default=(0, ""))[1]


def claim_pointer_resolution(pointer_seq: int) -> bool:
    with pointer_state_lock:
        if pointer_seq in resolved_pointer_seqs:
            return False
        resolved_pointer_seqs.add(pointer_seq)
        return True


def pointer_is_resolved(pointer_seq: int) -> bool:
    with pointer_state_lock:
        return pointer_seq in resolved_pointer_seqs


def code_narrow_control_at_point(
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]],
    x: int,
    y: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, int]:
    """Recover focused VS Code controls exposed only as a 1px caret box."""
    pending: collections.deque[Any] = collections.deque()
    visited = 0
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    code_roots = [
        value
        for value in roots
        if str(value[2] or "").strip().casefold() == "code"
    ]
    selected_roots = [value for value in code_roots if value[0]] or code_roots[:1]
    for _, root, _, _ in selected_roots:
        pending.append(root)
    while pending and visited < 500 and time.monotonic() < deadline:
        node = pending.popleft()
        visited += 1
        info = node_info(node, "code")
        role = str(info.get("role") or "").strip().lower()
        name = str(info.get("name") or "").strip()
        bbox = info.get("bbox")
        if (
            role in {"entry", "text"}
            and name
            and bbox
            and bbox[2] <= 2
            and bbox[1] <= y < bbox[1] + bbox[3]
        ):
            states = safe(node.get_state_set)
            focused = int(
                bool(
                    states
                    and safe(
                        lambda: states.contains(Atspi.StateType.FOCUSED),
                        False,
                    )
                )
            )
            candidates.append((focused, -abs(bbox[0] - x), info))
            if focused:
                break
        count = int(safe(node.get_child_count, 0) or 0)
        for index in range(count):
            child = safe(lambda index=index: node.get_child_at_index(index))
            if child is not None:
                pending.append(child)
    if not candidates:
        return None, visited
    target = max(candidates, key=lambda value: value[:2])[2]
    return {**target, "label_source": "focused-caret"}, visited


def bounded_interactive_control_at_point(
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]],
    app_names: set[str],
    x: int,
    y: int,
    deadline: float,
    max_nodes: int = 700,
) -> tuple[dict[str, Any] | None, int]:
    """Find a named app control despite a provider's stale parent bounds.

    This fallback is entered only after the normal point descent failed and is
    restricted to the foreground application's roots. Children whose own
    bounds contain the point are visited first, while a hard node/deadline cap
    preserves watcher responsiveness.
    """
    selected = [
        value
        for value in roots
        if str(value[2] or "").strip().casefold() in app_names
    ]
    selected = [value for value in selected if value[0]] or selected[:1]
    pending: collections.deque[tuple[Any, int, str | None]] = collections.deque(
        (root, 0, app_name) for _, root, app_name, _ in selected[:1]
    )
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    visited = 0
    while pending and visited < max_nodes and time.monotonic() < deadline:
        node, depth, app_name = pending.popleft()
        visited += 1
        info = node_info(node, app_name)
        role = str(info.get("role") or "").strip().casefold()
        name = str(info.get("name") or "").strip()
        bbox = info.get("bbox")
        if role in interactive_roles and name and contains(bbox, x, y):
            area = int(bbox[2]) * int(bbox[3])
            direct = int(info.get("label_source") in {"name", "description"})
            candidates.append((direct, depth, -area, info))

        priority: list[Any] = []
        others: list[Any] = []
        count = int(safe(node.get_child_count, 0) or 0)
        for index in range(count):
            child = safe(lambda index=index: node.get_child_at_index(index))
            if child is None:
                continue
            extents = safe(
                lambda child=child: child.get_extents(Atspi.CoordType.SCREEN)
            )
            child_bbox = (
                [
                    int(extents.x),
                    int(extents.y),
                    int(extents.width),
                    int(extents.height),
                ]
                if extents and extents.width > 0 and extents.height > 0
                else None
            )
            (priority if contains(child_bbox, x, y) else others).append(child)
        for child in reversed(priority):
            pending.appendleft((child, depth + 1, app_name))
        for child in others:
            pending.append((child, depth + 1, app_name))
    if not candidates:
        return None, visited
    return max(candidates, key=lambda value: value[:3])[3], visited


def special_surface_at_point(
    desktop: Any,
    app_name: str,
    x: int,
    y: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, int]:
    """Query a normally-skipped system surface without affecting app hits."""
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    visited = 0

    pending: collections.deque[tuple[Any, int]] = collections.deque()
    for app_index in range(int(safe(desktop.get_child_count, 0) or 0)):
        if time.monotonic() >= deadline:
            break
        app = safe(lambda app_index=app_index: desktop.get_child_at_index(app_index))
        if app is None or str(safe(app.get_name, "") or "") != app_name:
            continue
        count = int(safe(app.get_child_count, 0) or 0)
        for root_index in range(count):
            root = safe(lambda root_index=root_index: app.get_child_at_index(root_index))
            if root is not None:
                pending.append((root, 0))

    # Breadth-first traversal reaches the shallow top-bar/Dock controls before
    # GNOME Shell's large applications grid, while coordinate pruning prevents
    # unrelated valid subtrees from entering the queue.
    while pending and visited < 3000 and time.monotonic() < deadline:
        node, depth = pending.popleft()
        visited += 1
        info = node_info(node, app_name)
        bbox = info.get("bbox")
        bbox_contains_point = contains(bbox, x, y)
        if bbox is not None and not bbox_contains_point:
            # Ubuntu Dock can report a scrolled parent whose vertical clip no
            # longer contains still-visible child icons. Follow only narrow
            # left-dock containers through that inconsistency; each named icon
            # must still match its own valid bounding box before becoming a
            # candidate.
            dock_container = bool(
                app_name == "gnome-shell"
                and x < 70
                and y >= 27
                and bbox[0] <= x < bbox[0] + bbox[2]
                and bbox[2] <= 100
            )
            # After an xrandr mode change GNOME Shell can retain the old
            # full-screen root bounds while its Dock children already expose
            # their new/overflowing locations.  Permit only the first two
            # ancestors in the left-edge corridor to bridge that stale root.
            shell_root_container = bool(
                app_name == "gnome-shell" and x < 70 and depth <= 2
            )
            if not dock_container and not shell_root_container:
                continue
        name = str(info.get("name") or "").strip()
        if bbox_contains_point and name:
            area = bbox[2] * bbox[3]
            role = str(info.get("role") or "").strip().lower()
            candidates.append(
                (1 if role in interactive_roles else 0, depth, -area, info)
            )
        count = int(safe(node.get_child_count, 0) or 0)
        priority_children: list[Any] = []
        other_children: list[Any] = []
        for index in range(count):
            child = safe(lambda index=index: node.get_child_at_index(index))
            if child is not None:
                child_extents = safe(
                    lambda child=child: child.get_extents(Atspi.CoordType.SCREEN)
                )
                left_corridor = bool(
                    app_name == "gnome-shell"
                    and x < 70
                    and child_extents
                    and child_extents.x <= x
                    < child_extents.x + child_extents.width
                    and child_extents.width <= 100
                )
                top_corridor = bool(
                    app_name == "gnome-shell"
                    and y < 27
                    and child_extents
                    and child_extents.y <= y
                    < child_extents.y + child_extents.height
                    and child_extents.height <= 60
                )
                (priority_children if left_corridor or top_corridor else other_children).append(
                    child
                )
        for child in reversed(priority_children):
            pending.appendleft((child, depth + 1))
        for child in other_children:
            pending.append((child, depth + 1))

    if not candidates:
        return None, visited
    target = max(candidates, key=lambda value: value[:3])[3]
    if app_name == "gjs":
        bbox = target.get("bbox")
        area = bbox[2] * bbox[3] if bbox else 10**18
        desktop_icon = area < 100000
        target = {
            **target,
            "app": "Desktop",
            "role": "desktop icon" if desktop_icon else "desktop",
            "name": target.get("name") if desktop_icon else "Desktop",
            "label_source": "desktop-provider",
        }
    return target, visited


def settings_row_at_point(
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]],
    x: int,
    y: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, int]:
    """Recover the label of an unnamed GNOME Settings action-row control."""
    rows: list[tuple[int, int, Any, dict[str, Any]]] = []
    controls: list[tuple[int, int, dict[str, Any]]] = []
    visited = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal visited
        if node is None or visited >= 1000 or time.monotonic() >= deadline:
            return
        visited += 1
        info = node_info(node, "gnome-control-center")
        bbox = info.get("bbox")
        if bbox is not None and not contains(bbox, x, y):
            return
        role = str(info.get("role") or "").strip().lower()
        if bbox is not None:
            area = bbox[2] * bbox[3]
            if role == "list item":
                rows.append((area, depth, node, info))
            if role in interactive_roles:
                controls.append((depth, -area, info))
        count = int(safe(node.get_child_count, 0) or 0)
        for index in range(count):
            if visited >= 1000 or time.monotonic() >= deadline:
                break
            walk(safe(lambda index=index: node.get_child_at_index(index)), depth + 1)

    def row_label(node: Any) -> str:
        nonlocal visited
        visited += 1
        return settings_descendant_label(node)

    for active, root, app_name, _ in roots:
        if active and app_name == "gnome-control-center":
            walk(root, 0)
    for _, _, node, row_info in sorted(rows, key=lambda value: (value[0], -value[1])):
        label = row_label(node)
        if not label:
            continue
        control = max(controls, default=None, key=lambda value: value[:2])
        if control is not None:
            control_info = control[2]
            return {
                **control_info,
                "name": label,
                "description": "",
                "label_source": "settings-row-label",
            }, visited
        return {
            **row_info,
            "name": label,
            "description": "",
            "label_source": "settings-row-label",
        }, visited
    return None, visited


def nautilus_target_needs_refinement(
    info: dict[str, Any] | None,
) -> bool:
    """Return true only for Nautilus view containers, never file items."""
    if not info or "nautilus" not in str(info.get("app") or "").casefold():
        return False
    role = str(info.get("role") or "").strip().casefold()
    name = str(info.get("name") or "").strip().casefold()
    return role in {"filler", "layered pane", "panel", "scroll pane"} and name in {
        "grid view",
        "icon view",
        "list view",
    }


def nautilus_control_at_point(
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]],
    x: int,
    y: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, int]:
    """Recover a Nautilus toolbar control hidden behind its view container.

    Nautilus can attach header-bar buttons below an accessibility ancestor
    whose reported bounds do not contain the visible child.  Consequently this
    app-scoped fallback must not prune descendants by the ancestor bounds.  It
    remains bounded to 500 nodes and only returns a named interactive control
    whose own real bounds contain the click.
    """
    nautilus_roots = [
        value
        for value in roots
        if "nautilus" in str(value[2] or "").casefold()
    ]
    selected_roots = [value for value in nautilus_roots if value[0]] or nautilus_roots[:1]
    pending: collections.deque[tuple[Any, int]] = collections.deque(
        (root, 0) for _, root, _, _ in selected_roots[:1]
    )
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    visited = 0
    while pending and visited < 500 and time.monotonic() < deadline:
        node, depth = pending.popleft()
        visited += 1
        info = node_info(node, "org.gnome.Nautilus")
        role = str(info.get("role") or "").strip().casefold()
        name = str(info.get("name") or "").strip()
        bbox = info.get("bbox")
        if role in interactive_roles and name and contains(bbox, x, y):
            area = int(bbox[2]) * int(bbox[3])
            direct_label = int(info.get("label_source") in {"name", "description"})
            candidates.append((direct_label, depth, -area, info))
        count = int(safe(node.get_child_count, 0) or 0)
        for index in range(count):
            child = safe(lambda index=index: node.get_child_at_index(index))
            if child is not None:
                pending.append((child, depth + 1))
    if not candidates:
        return None, visited
    return max(candidates, key=lambda value: value[:3])[3], visited


def gimp_canvas_label(foreground_title: str) -> str:
    """Build a stable canvas label from GIMP's current document title."""
    title = foreground_title.strip()
    for suffix in (" – GIMP", " - GIMP"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].rstrip()
            break
    if "-1.0 (" in title:
        title = title.split("-1.0 (", 1)[0].rstrip()
    return f"Image canvas — {title}" if title else "Image canvas"


def gimp_canvas_at_point(
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]],
    x: int,
    y: int,
    deadline: float,
) -> tuple[dict[str, Any] | None, int]:
    """Identify GIMP's unnamed central image surface without guessing pixels."""
    gimp_roots = [
        value
        for value in roots
        if str(value[2] or "").strip().casefold() == "gimp"
    ]
    selected_roots = [value for value in gimp_roots if value[0]] or gimp_roots[:1]
    if not selected_roots:
        return None, 0
    _, root, _, root_info = selected_roots[0]
    root_bbox = root_info.get("bbox")
    if not root_bbox:
        return None, 0
    pending: collections.deque[tuple[Any, int]] = collections.deque([(root, 0)])
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    visited = 0
    while pending and visited < 500 and time.monotonic() < deadline:
        node, depth = pending.popleft()
        visited += 1
        info = node_info(node, "gimp")
        bbox = info.get("bbox")
        if bbox is not None and not contains(bbox, x, y):
            continue
        role = str(info.get("role") or "").strip().casefold()
        raw_name = str(safe(node.get_name, "") or "").strip()
        raw_description = str(safe(node.get_description, "") or "").strip()
        child_count = int(safe(node.get_child_count, 0) or 0)
        if (
            role == "panel"
            and not raw_name
            and not raw_description
            and child_count == 0
            and bbox
            and int(bbox[2]) >= max(160, int(root_bbox[2]) * 35 // 100)
            and int(bbox[3]) >= max(160, int(root_bbox[3]) * 35 // 100)
        ):
            area = int(bbox[2]) * int(bbox[3])
            candidates.append((depth, -area, info))
        for index in range(child_count):
            child = safe(lambda index=index: node.get_child_at_index(index))
            if child is not None:
                pending.append((child, depth + 1))
    if not candidates:
        return None, visited
    target = max(candidates, key=lambda value: value[:2])[2]
    return {
        **target,
        "role": "canvas",
        "name": gimp_canvas_label(
            hit_foreground_title or str(root_info.get("name") or "")
        ),
        "description": "Editable image canvas",
        "label_source": "gimp-canvas-surface",
    }, visited


def accessible_at_point(x: int, y: int) -> tuple[dict[str, Any] | None, int]:
    """Return a hit using bounded native AT-SPI point lookups.

    Never enumerate every application's full tree. Top-level windows are cheap
    to enumerate and their component interface can descend directly. If an
    active application only returns a coarse frame (notably GIMP), perform a
    tightly bounded, coordinate-pruned fallback inside that active window.
    """
    desktop = Atspi.get_desktop(0)
    deadline = time.monotonic() + hit_test_budget_seconds
    candidates: list[tuple[bool, int, dict[str, Any]]] = []
    roots: list[tuple[bool, Any, str | None, dict[str, Any]]] = []
    visited = 0

    # GNOME Shell is globally present but intentionally excluded from normal
    # application ranking. Query it only where its UI is actually painted.
    if x < 70 or y < 27:
        target, special_visited = special_surface_at_point(
            desktop, "gnome-shell", x, y, deadline
        )
        visited += special_visited
        if target_is_precise(target):
            return target, visited
    # The desktop provider is globally present behind every application.  It
    # is safe to query either when X11 says all windows are hidden, or when the
    # click lies outside the foreground window.  In the latter case accept
    # only a concrete icon so an exposed background app is not masked by the
    # provider's generic desktop surface.
    foreground_exposes_point = bool(
        hit_foreground_bbox
        and not contains(hit_foreground_bbox, x, y)
    )
    desktop_foreground = any(
        value.strip().casefold() == "gjs" for value in hit_foreground_classes
    )
    if (
        hit_showing_desktop or foreground_exposes_point or desktop_foreground
    ) and x >= 70 and y >= 27:
        target, special_visited = special_surface_at_point(
            desktop, "gjs", x, y, deadline
        )
        visited += special_visited
        if target_is_precise(target) and (
            hit_showing_desktop
            or desktop_foreground
            or target.get("role") == "desktop icon"
        ):
            return target, visited
        if hit_showing_desktop or desktop_foreground:
            return {
                "app": "Desktop",
                "role": "desktop",
                "name": "Desktop",
                "description": "",
                "label_source": "desktop-provider",
                "bbox": [70, 27, 1210, 773],
            }, visited

    for app_index in range(int(safe(desktop.get_child_count, 0) or 0)):
        if time.monotonic() >= deadline:
            break
        app = safe(lambda: desktop.get_child_at_index(app_index))
        if app is None:
            continue
        app_name = safe(app.get_name)
        if application_skipped(app_name):
            continue
        count = int(safe(app.get_child_count, 0) or 0)
        for index in range(count):
            if time.monotonic() >= deadline:
                break
            root = safe(lambda: app.get_child_at_index(index))
            if root is None:
                continue
            visited += 1
            info = node_info(root, app_name)
            if contains(info["bbox"], x, y):
                active = node_is_active(root)
                roots.append((active, root, app_name, info))

    # Prefer the active window when overlapping applications both contain the
    # point. This avoids resolving a click against a covered Calc window.
    if hit_foreground_title:
        expected = hit_foreground_title.casefold()
        matching_roots = [
            value
            for value in roots
            if (
                str(value[3].get("name") or "").casefold() == expected
                or (
                    len(expected) >= 8
                    and expected
                    in str(value[3].get("name") or "").casefold()
                )
                or (
                    len(str(value[3].get("name") or "")) >= 8
                    and str(value[3].get("name") or "").casefold()
                    in expected
                )
            )
        ]
        if matching_roots:
            roots = matching_roots
    roots.sort(key=lambda value: value[0], reverse=True)
    if any(value.casefold() == "code" for value in hit_foreground_classes):
        code_roots = [
            value
            for value in roots
            if str(value[2] or "").strip().casefold() == "code"
        ]
        # A transient GTK dialog can disappear before the child hit-test
        # starts. Never replace that vanished Code control with a coordinate-
        # overlapping element from a covered application such as Chrome.
        roots = code_roots
    for active, root, app_name, root_info in roots:
        if time.monotonic() >= deadline:
            break
        candidates.append((active, 0, root_info))
        current = root
        deepest_depth = 0
        for depth in range(1, max_depth + 1):
            if time.monotonic() >= deadline:
                break
            child = safe(
                lambda: current.get_accessible_at_point(
                    x, y, Atspi.CoordType.SCREEN
                )
            )
            if child is None or child == current:
                break
            current = child
            deepest_depth = depth
            visited += 1
            info = node_info(current, app_name)
            if contains(info["bbox"], x, y):
                candidates.append((active, depth, info))

        # Some providers return the deepest painted child directly (for
        # example a VS Code icon glyph or Chrome button text). Walk a short
        # parent chain so the ranking step can prefer the named interactive
        # control that owns that child.
        ancestor = current
        for parent_hop in range(1, 9):
            if time.monotonic() >= deadline:
                break
            parent = safe(ancestor.get_parent)
            if parent is None or parent == ancestor:
                break
            ancestor = parent
            visited += 1
            info = node_info(ancestor, app_name)
            if contains(info["bbox"], x, y):
                candidates.append(
                    (
                        active,
                        max(0, deepest_depth - parent_hop),
                        info,
                    )
                )
            if ancestor == root:
                break

    def rank(
        value: tuple[bool, int, dict[str, Any]]
    ) -> tuple[int, int, int, int, int]:
        active, depth, info = value
        name = (info["name"] or "").strip()
        role = info["role"] or ""
        bbox = info["bbox"]
        area = bbox[2] * bbox[3] if bbox else 10**18
        return (
            1 if active else 0,
            1 if name and role in interactive_roles else 0,
            1 if name else 0,
            depth,
            -area,
        )

    best = max(candidates, key=rank)[2] if candidates else None
    best = refine_calc_name_box(best, hit_foreground_title)
    best = refine_compact_named_surface(best)
    if nautilus_target_needs_refinement(best):
        nautilus_target, nautilus_visited = nautilus_control_at_point(
            roots, x, y, deadline
        )
        visited += nautilus_visited
        if target_is_precise(nautilus_target):
            return nautilus_target, visited
    # GIMP's central canvas is an unnamed painted panel.  Its point-pruned
    # walk is both cheaper and more specific than the broad stale-parent
    # control scan below, so run it first for document windows.  Dialog titles
    # are deliberately rejected by gimp_canvas_allowed and continue to the
    # named-control scan without ever being guessed as an image canvas.
    if (
        not target_is_precise(best)
        and any("gimp" in value.casefold() for value in hit_foreground_classes)
        and gimp_canvas_allowed(hit_foreground_title)
    ):
        gimp_target, gimp_visited = gimp_canvas_at_point(
            roots, x, y, deadline
        )
        visited += gimp_visited
        if target_is_precise(gimp_target):
            return gimp_target, visited
    if not target_is_precise(best):
        scoped_apps: set[str] = set()
        foreground_identities = {
            value.strip().casefold() for value in hit_foreground_classes
        }
        for app_name in {"code", "gimp", "vlc"}:
            if app_name in foreground_identities:
                scoped_apps.add(app_name)
        # Calc's provider can block for longer than the pointer worker timeout
        # when its full tree is scanned. Impress has a substantially smaller
        # sidebar tree and needs this fallback for a repeated Keep ratio click,
        # so scope the breadth scan to Impress only; Writer and Calc stay on
        # bounded point descent and their dedicated refinements.
        if "libreoffice impress" in hit_foreground_title.casefold():
            scoped_apps.add("soffice")
        if scoped_apps:
            control_target, control_visited = bounded_interactive_control_at_point(
                roots, scoped_apps, x, y, deadline
            )
            visited += control_visited
            if target_is_precise(control_target):
                return control_target, visited
    if (
        not target_is_precise(best)
        and any(value.casefold() == "code" for value in hit_foreground_classes)
    ):
        code_target, code_visited = code_narrow_control_at_point(
            roots, x, y, deadline
        )
        visited += code_visited
        if target_is_precise(code_target):
            return code_target, visited
    if not target_is_precise(best):
        fallback_visited = 0

        def bounded_walk(
            node: Any, app_name: str | None, depth: int, active: bool
        ) -> None:
            nonlocal fallback_visited, visited
            if (
                node is None
                or depth > max_depth
                or fallback_visited >= max_fallback_nodes
                or time.monotonic() >= deadline
            ):
                return
            fallback_visited += 1
            visited += 1
            info = node_info(node, app_name)
            bbox = info["bbox"]
            if bbox is not None and not contains(bbox, x, y):
                return
            if bbox is not None:
                candidates.append((active, depth, info))
            count = int(safe(node.get_child_count, 0) or 0)
            for index in range(count):
                if (
                    fallback_visited >= max_fallback_nodes
                    or time.monotonic() >= deadline
                ):
                    break
                child = safe(lambda: node.get_child_at_index(index))
                bounded_walk(child, app_name, depth + 1, active)

        active_roots = [value for value in roots if value[0]] or roots[:1]
        for active, root, app_name, _ in active_roots[:1]:
            bounded_walk(root, app_name, 0, active)

    if not candidates:
        return None, visited
    best = max(candidates, key=rank)[2]
    best = refine_calc_name_box(best, hit_foreground_title)
    best = refine_compact_named_surface(best)
    if nautilus_target_needs_refinement(best):
        nautilus_target, nautilus_visited = nautilus_control_at_point(
            roots, x, y, deadline
        )
        visited += nautilus_visited
        if target_is_precise(nautilus_target):
            return nautilus_target, visited
    if not target_is_precise(best):
        settings_target, settings_visited = settings_row_at_point(
            roots, x, y, deadline
        )
        visited += settings_visited
        if target_is_precise(settings_target):
            return settings_target, visited
    surface_target = coarse_surface_target(
        best, hit_foreground_title, x, y
    )
    if target_is_precise(surface_target):
        return surface_target, visited
    return best, visited


def record_pointer_resolution(
    x: int,
    y: int,
    button: str,
    pointer_seq: int,
    foreground_title: str,
    showing_desktop: bool,
    foreground_classes: list[str],
    foreground_bbox: list[int] | None,
) -> None:
    started_at = time.monotonic()
    target: dict[str, Any] | None = None
    visited = 0
    resolution = "unresolved"
    error: str | None = None
    try:
        child_env = os.environ.copy()
        if foreground_title:
            child_env["HIT_FOREGROUND_TITLE"] = foreground_title
        if showing_desktop:
            child_env["HIT_SHOWING_DESKTOP"] = "1"
        if foreground_classes:
            child_env["HIT_FOREGROUND_CLASSES"] = ",".join(foreground_classes)
        if foreground_bbox:
            child_env["HIT_FOREGROUND_BBOX"] = json.dumps(foreground_bbox)
        command = [
            sys.executable,
            __file__,
            "--hit-test",
            str(x),
            str(y),
        ]

        def run_hit_test() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=hit_test_timeout_seconds,
                check=False,
                env=child_env,
            )

        if "libreoffice" in foreground_title.casefold():
            with libreoffice_hit_test_lock:
                result = run_hit_test()
        else:
            result = run_hit_test()
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            candidate = payload.get("target")
            if isinstance(candidate, dict):
                target = candidate
            visited = int(payload.get("visited_nodes", 0))
            if target_is_precise(target):
                resolution = "resolved"
            elif target is not None:
                resolution = "coarse"
            else:
                resolution = "unresolved"
        else:
            resolution = "error"
            error = (result.stderr or result.stdout).strip()[-500:]
    except subprocess.TimeoutExpired:
        resolution = "timeout"
        error = f"AT-SPI hit test exceeded {hit_test_timeout_seconds:.1f}s"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        resolution = "error"
        error = str(exc)
    if resolution != "resolved":
        # A provider may emit an exact focus/selection event just after the
        # child hit-test reaches its timeout. Keep the base pointer durable,
        # but defer a non-exact terminal record until the semantic correlation
        # window closes so one click still receives exactly one resolution.
        remaining = pointer_correlation_seconds - (
            time.monotonic() - started_at
        )
        if remaining > 0:
            time.sleep(remaining)
    if not claim_pointer_resolution(pointer_seq):
        return
    write_item(
        {
            "event": "pointer-resolution",
            "pointer_event": f"pointer:{button}",
            "pointer_seq": pointer_seq,
            "mouse": [x, y],
            "source": "atspi-hit-test",
            "resolution": resolution,
            "visited_nodes": visited,
            **({"error": error} if error else {}),
            **(
                target
                if target is not None
                else {"app": None, "role": None, "name": "", "bbox": None}
            ),
        }
    )


def click_resolution_loop() -> None:
    while True:
        (
            x,
            y,
            button,
            pointer_seq,
            foreground_title,
            showing_desktop,
            foreground_classes,
            foreground_bbox,
        ) = click_queue.get()
        try:
            record_pointer_resolution(
                x,
                y,
                button,
                pointer_seq,
                foreground_title,
                showing_desktop,
                foreground_classes,
                foreground_bbox,
            )
        except Exception as exc:
            write_item(
                {
                    "event": "pointer-resolution",
                    "pointer_event": f"pointer:{button}",
                    "pointer_seq": pointer_seq,
                    "mouse": [x, y],
                    "source": "atspi-hit-test",
                    "resolution": "error",
                    "error": str(exc),
                    "app": None,
                    "role": None,
                    "name": "",
                    "bbox": None,
                }
            )
        finally:
            click_queue.task_done()


def transient_hover_loop() -> None:
    """Cache the control under the pointer only in transient-button apps.

    XRecord observes ButtonPress after the target toolkit may already have
    destroyed a dialog.  A low-rate, app-scoped hover probe preserves the
    last named button without adding AT-SPI traversal to Calc or other apps.
    This thread owns its X connection and performs at most one bounded probe
    per pointer position, with a one-second refresh while stationary.
    """
    hover_display = display.Display()
    hover_root = hover_display.screen().root
    active_atom = hover_display.intern_atom("_NET_ACTIVE_WINDOW")
    wm_class_atom = hover_display.intern_atom("WM_CLASS")
    last_point: tuple[int, int] | None = None
    last_probe_at = 0.0
    while True:
        foreground_classes: list[str] = []
        foreground_title = ""
        try:
            prop = hover_root.get_full_property(
                active_atom, X.AnyPropertyType
            )
            if not prop or not prop.value:
                raise RuntimeError("No active window")
            window = hover_display.create_resource_object(
                "window", int(prop.value[0])
            )
            wm_class = window.get_full_property(
                wm_class_atom, X.AnyPropertyType
            )
            raw = bytes(wm_class.value) if wm_class else b""
            foreground_classes = [
                item.decode(errors="replace")
                for item in raw.rstrip(b"\0").split(b"\0")
                if item
            ]
            foreground_title = str(window.get_wm_name() or "")
        except Exception:
            time.sleep(transient_hover_poll_seconds)
            continue
        classes_lower = {
            value.strip().casefold() for value in foreground_classes
        }
        if not classes_lower & transient_click_apps:
            with pointer_state_lock:
                recent_transient_hover_control.clear()
                recent_transient_focus_control.clear()
            last_point = None
            time.sleep(0.25)
            continue
        try:
            pointer = hover_root.query_pointer()
            point = (int(pointer.root_x), int(pointer.root_y))
        except Exception:
            time.sleep(transient_hover_poll_seconds)
            continue
        with pointer_state_lock:
            cached_info = recent_transient_hover_control.get("info")
            if (
                isinstance(cached_info, dict)
                and not contains(cached_info.get("bbox"), *point)
            ):
                recent_transient_hover_control.clear()
        now = time.monotonic()
        if (
            point == last_point
            and now - last_probe_at < transient_hover_refresh_seconds
        ):
            time.sleep(transient_hover_poll_seconds)
            continue
        last_point = point
        last_probe_at = now
        child_env = os.environ.copy()
        if foreground_title:
            child_env["HIT_FOREGROUND_TITLE"] = foreground_title
        child_env["HIT_FOREGROUND_CLASSES"] = ",".join(
            foreground_classes
        )
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "--hit-test",
                    str(point[0]),
                    str(point[1]),
                ],
                capture_output=True,
                text=True,
                timeout=hit_test_timeout_seconds,
                check=False,
                env=child_env,
            )
            payload = json.loads(result.stdout) if result.returncode == 0 else {}
            target = payload.get("target")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            target = None
        target_app = str((target or {}).get("app") or "").casefold()
        target_role = str((target or {}).get("role") or "").lower()
        if (
            target_is_precise(target)
            and target_role in transient_click_roles
            and contains((target or {}).get("bbox"), *point)
            and any(value in target_app for value in transient_click_apps)
        ):
            with pointer_state_lock:
                recent_transient_hover_control.clear()
                recent_transient_hover_control.update(
                    {
                        "created_at": time.monotonic(),
                        "trigger": "pointer-stationary",
                        "info": dict(target),
                    }
                )
        time.sleep(transient_hover_poll_seconds)


def record_pointer_click(
    x: int,
    y: int,
    button: str,
    foreground: dict[str, Any],
) -> None:
    classes = foreground.get("wm_class") or []
    app = classes[-1] if classes else None
    pointer_seq = write_item(
        {
            "event": f"pointer:{button}",
            "mouse": [x, y],
            "source": "xrecord",
            "resolution": "pending",
            "foreground": foreground,
            "app": app,
            "role": "window" if foreground else None,
            "name": foreground.get("title", ""),
            "bbox": foreground.get("window_bbox"),
        }
    )
    cached_menu: dict[str, Any] | None = None
    cached_chrome_focus: dict[str, Any] | None = None
    cached_transient: dict[str, Any] | None = None
    cached_transient_trigger = ""
    cached_transient_age = 0.0
    transient_foreground = False
    with pointer_state_lock:
        now = time.monotonic()
        while (
            pending_clicks
            and now - float(pending_clicks[0]["created_at"])
            > pointer_correlation_seconds
        ):
            pending_clicks.popleft()
        classes_lower = {
            str(value).strip().casefold()
            for value in foreground.get("wm_class") or []
        }
        chrome_foreground = any(
            is_chromium_app(value)
            for value in foreground.get("wm_class") or []
        )
        chrome_focus_info = recent_chrome_focus_control.get("info")
        chrome_focus_age = now - float(
            recent_chrome_focus_control.get("created_at", 0.0)
        )
        if (
            chrome_foreground
            and isinstance(chrome_focus_info, dict)
            and is_chromium_app(chrome_focus_info.get("app"))
            and chrome_focus_age <= chrome_focus_cache_seconds
            and contains(chrome_focus_info.get("bbox"), x, y)
        ):
            cached_chrome_focus = dict(chrome_focus_info)
            recent_chrome_focus_control.clear()
            resolved_pointer_seqs.add(pointer_seq)
        transient_foreground = bool(
            classes_lower & transient_click_apps
            or foreground.get("window_error")
        )
        transient_candidates = sorted(
            (
                recent_transient_hover_control,
                recent_transient_focus_control,
            ),
            key=lambda value: float(value.get("created_at", 0.0)),
            reverse=True,
        )
        if cached_chrome_focus is None and transient_foreground:
            for transient_candidate in transient_candidates:
                transient_info = transient_candidate.get("info")
                transient_age = now - float(
                    transient_candidate.get("created_at", 0.0)
                )
                if (
                    isinstance(transient_info, dict)
                    and transient_age <= transient_control_cache_seconds
                    and contains(transient_info.get("bbox"), x, y)
                ):
                    cached_transient = dict(transient_info)
                    cached_transient_trigger = str(
                        transient_candidate.get("trigger") or ""
                    )
                    cached_transient_age = transient_age
                    recent_transient_hover_control.clear()
                    recent_transient_focus_control.clear()
                    resolved_pointer_seqs.add(pointer_seq)
                    break
        menu_info = recent_menu_item.get("info")
        menu_age = now - float(recent_menu_item.get("created_at", 0.0))
        menu_app = str(
            menu_info.get("app") if isinstance(menu_info, dict) else ""
        ).strip().casefold()
        foreground_context = " ".join(
            [
                *classes_lower,
                str(foreground.get("title") or "").casefold(),
            ]
        )
        same_menu_app = bool(
            menu_app
            and (
                menu_app in foreground_context
                or (
                    menu_app == "soffice"
                    and "libreoffice" in foreground_context
                )
            )
        )
        if cached_chrome_focus is not None or cached_transient is not None:
            pass
        elif (
            same_menu_app
            and isinstance(menu_info, dict)
            and menu_age <= menu_cache_seconds
            and contains(menu_info.get("bbox"), x, y)
        ):
            cached_menu = dict(menu_info)
            recent_menu_item.clear()
            resolved_pointer_seqs.add(pointer_seq)
        else:
            if menu_age > menu_cache_seconds:
                recent_menu_item.clear()
            pending_clicks.append(
                {
                    "seq": pointer_seq,
                    "created_at": now,
                    "button": button,
                    "mouse": [x, y],
                    "foreground_classes": sorted(classes_lower),
                    "foreground_error": bool(
                        foreground.get("window_error")
                    ),
                    "foreground_title": str(
                        foreground.get("title") or ""
                    ),
                }
            )
    if cached_chrome_focus is not None:
        write_item(
            {
                "event": "pointer-resolution",
                "pointer_event": f"pointer:{button}",
                "pointer_seq": pointer_seq,
                "mouse": [x, y],
                "source": "atspi-preclick-focus-cache",
                "resolution": "resolved",
                "atspi_event": "object:state-changed:focused",
                **cached_chrome_focus,
            }
        )
        return
    if cached_transient is not None:
        write_item(
            {
                "event": "pointer-resolution",
                "pointer_event": f"pointer:{button}",
                "pointer_seq": pointer_seq,
                "mouse": [x, y],
                "source": "atspi-transient-cache",
                "resolution": "resolved",
                "cache_trigger": cached_transient_trigger,
                "cache_age_seconds": round(cached_transient_age, 3),
                **cached_transient,
            }
        )
        return
    if cached_menu is not None:
        write_item(
            {
                "event": "pointer-resolution",
                "pointer_event": f"pointer:{button}",
                "pointer_seq": pointer_seq,
                "mouse": [x, y],
                "source": "atspi-menu-cache",
                "resolution": "resolved",
                "atspi_event": "object:state-changed:selected",
                **cached_menu,
            }
        )
        return
    if pointer_is_resolved(pointer_seq):
        return
    try:
        click_queue.put_nowait(
            (
                x,
                y,
                button,
                pointer_seq,
                str(foreground.get("title") or ""),
                bool(foreground.get("showing_desktop")),
                [str(value) for value in foreground.get("wm_class") or []],
                (
                    [int(value) for value in foreground.get("window_bbox")]
                    if isinstance(foreground.get("window_bbox"), list)
                    and len(foreground.get("window_bbox")) == 4
                    else None
                ),
            )
        )
    except queue.Full:
        # The base pointer event is already durable. Never queue an unbounded
        # amount of work behind a slow or broken accessibility provider.
        pass


def on_event(event: object) -> None:
    global last_key, last_time
    if event.type.startswith("object:state-changed") and event.detail1 != 1:
        return
    source = event.source
    if source is None:
        return
    any_data = getattr(event, "any_data", None)
    target = (
        any_data
        if any_data is not None and hasattr(any_data, "get_role_name")
        else source
    )
    app = application_name(target)
    if application_skipped(app):
        return
    info = node_info(target, app)
    info = refine_compact_named_surface(info)
    if (
        str(app or "").strip().casefold() == "code"
        and str(info.get("role") or "").strip().lower() == "table cell"
        and info.get("label_source") == "parent"
    ):
        cell_label = code_table_cell_label(target)
        if cell_label:
            info = {
                **info,
                "name": cell_label,
                "description": "",
                "label_source": "cell-descendant",
            }
    if app == "gnome-control-center" and not str(info.get("name") or "").strip():
        row_label = settings_descendant_label(target)
        if row_label:
            info = {
                **info,
                "name": row_label,
                "description": "",
                "label_source": "settings-row-label",
            }
    if info["role"] in skip_roles and not info["name"].strip():
        return
    key = (
        app,
        info["role"],
        info["name"],
        tuple(info["bbox"]) if info["bbox"] else None,
    )
    now = time.time()
    if key == last_key and now - last_time < 0.3:
        return
    last_key, last_time = key, now
    event_mouse = mouse()
    write_item(
        {
            "event": event.type,
            "mouse": event_mouse,
            "source": "atspi-event",
            **(
                {"event_container": node_info(source)}
                if target is not source
                else {}
            ),
            **info,
        }
    )
    role = str(info.get("role") or "").strip().lower()
    code_event = str(app or "").strip().casefold() == "code"
    transient_event = any(
        value in str(app or "").strip().casefold()
        for value in transient_click_apps
    )
    if (
        is_chromium_app(app)
        and event.type in {"focus:", "object:state-changed:focused"}
        and role in chrome_focus_roles
        and target_is_precise(info)
        and info.get("bbox") is not None
    ):
        with pointer_state_lock:
            recent_chrome_focus_control.clear()
            recent_chrome_focus_control.update(
                {"created_at": time.monotonic(), "info": dict(info)}
            )
    if (
        transient_event
        and event.type
        in {
            "focus:",
            "object:state-changed:focused",
            "object:state-changed:armed",
        }
        and role in transient_click_roles
        and target_is_precise(info)
        and info.get("bbox") is not None
    ):
        with pointer_state_lock:
            recent_transient_focus_control.clear()
            recent_transient_focus_control.update(
                {
                    "created_at": time.monotonic(),
                    "trigger": event.type,
                    "info": dict(info),
                }
            )
    if (
        role.endswith("menu item")
        and event.type == "object:state-changed:selected"
        and target_is_precise(info)
    ):
        with pointer_state_lock:
            recent_menu_item.clear()
            recent_menu_item.update(
                {"created_at": time.monotonic(), "info": dict(info)}
            )
    semantic_state = event.type.rsplit(":", 1)[-1] in {
        "selected",
        "checked",
        "pressed",
        "expanded",
    }
    strong_target = target is not source or (
        event.type.startswith("object:state-changed")
        and event.detail1 == 1
        and (semantic_state or role in interactive_roles)
        and target_is_precise(info)
    ) or (
        code_event
        and event.type == "focus:"
        and role in interactive_roles
        and target_is_precise(info)
    )
    if not strong_target or not target_is_precise(info):
        return
    # VS Code's Chromium accessibility tree often selects a large Settings
    # row before focusing the smaller button inside it. Let the point hit-test
    # choose the descendant instead of allowing that ancestor event to win.
    if code_event and role == "tree item":
        return
    correlated: dict[str, Any] | None = None
    correlation_reason: str | None = None
    with pointer_state_lock:
        now_mono = time.monotonic()
        while (
            pending_clicks
            and now_mono - float(pending_clicks[0]["created_at"])
            > pointer_correlation_seconds
        ):
            pending_clicks.popleft()
        for pending in reversed(pending_clicks):
            pointer_seq = int(pending["seq"])
            pointer_x, pointer_y = pending["mouse"]
            bbox = info.get("bbox")
            age = now_mono - float(pending["created_at"])
            pending_classes = {
                str(value).strip().casefold()
                for value in pending.get("foreground_classes") or []
            }
            app_lower = str(app or "").strip().casefold()
            pending_app_context = " ".join(
                [
                    *pending_classes,
                    str(pending.get("foreground_title") or "").casefold(),
                ]
            )
            same_transient_app = bool(
                (
                    pending_classes & transient_click_apps
                    or pending.get("foreground_error")
                )
                and any(
                    value in app_lower for value in transient_click_apps
                )
            )
            null_bbox_transient = bool(
                bbox is None
                and role in transient_click_roles
                and age <= null_bbox_correlation_seconds
                and same_transient_app
                and event_mouse == [pointer_x, pointer_y]
            )
            narrow_code_control = bool(
                code_event
                and role in {"entry", "text"}
                and bbox
                and bbox[2] <= 2
                and bbox[1] <= pointer_y < bbox[1] + bbox[3]
            )
            # Transient menus can disappear before the asynchronous point
            # hit-test runs. LibreOffice, in particular, emits the exact
            # selected menu item immediately but sometimes reports an invalid
            # off-screen bbox (INT_MIN). Prefer that short-lived semantic
            # event over a later hit-test at the same coordinates, which now
            # point to the document underneath the closed menu.
            semantic_menu_event = bool(
                event.type == "object:state-changed:selected"
                and role.endswith("menu item")
                and age <= menu_event_correlation_seconds
                and event_mouse == [pointer_x, pointer_y]
                and not contains(bbox, pointer_x, pointer_y)
                and (
                    app_lower in pending_app_context
                    or (
                        app_lower == "soffice"
                        and "libreoffice" in pending_app_context
                    )
                )
            )
            if (
                pointer_seq not in resolved_pointer_seqs
                and (
                    contains(bbox, pointer_x, pointer_y)
                    or narrow_code_control
                    or null_bbox_transient
                    or semantic_menu_event
                )
            ):
                resolved_pointer_seqs.add(pointer_seq)
                correlated = pending
                if semantic_menu_event:
                    correlation_reason = "transient-menu-semantic"
                break
    if correlated is None:
        return
    write_item(
        {
            "event": "pointer-resolution",
            "pointer_event": f"pointer:{correlated['button']}",
            "pointer_seq": correlated["seq"],
            "mouse": correlated["mouse"],
            "source": "atspi-event-correlation",
            "resolution": "resolved",
            "atspi_event": event.type,
            **(
                {"correlation": correlation_reason}
                if correlation_reason
                else (
                    {"correlation": "transient-null-bbox"}
                    if info.get("bbox") is None
                    else {}
                )
            ),
            **info,
        }
    )


def xrecord_loop() -> None:
    record_display = display.Display()
    window_display = display.Display()
    root = window_display.screen().root
    active_window_atom = window_display.intern_atom("_NET_ACTIVE_WINDOW")
    showing_desktop_atom = window_display.intern_atom("_NET_SHOWING_DESKTOP")
    wm_class_atom = window_display.intern_atom("WM_CLASS")
    pointer_buttons = {1: "left", 2: "middle", 3: "right"}

    def foreground_window() -> dict[str, Any]:
        try:
            showing_desktop_prop = root.get_full_property(
                showing_desktop_atom, X.AnyPropertyType
            )
            showing_desktop = bool(
                showing_desktop_prop
                and showing_desktop_prop.value
                and int(showing_desktop_prop.value[0])
            )
            prop = root.get_full_property(
                active_window_atom, X.AnyPropertyType
            )
            if not prop or not prop.value:
                return {}
            window = window_display.create_resource_object(
                "window", int(prop.value[0])
            )
            wm_class = window.get_full_property(
                wm_class_atom, X.AnyPropertyType
            )
            raw = bytes(wm_class.value) if wm_class else b""
            classes = [
                item.decode(errors="replace")
                for item in raw.rstrip(b"\0").split(b"\0")
                if item
            ]
            geometry = window.get_geometry()
            position = window.translate_coords(root, 0, 0)
            return {
                "wm_class": classes,
                "title": window.get_wm_name() or "",
                "showing_desktop": showing_desktop,
                "window_bbox": [
                    int(position.x),
                    int(position.y),
                    int(geometry.width),
                    int(geometry.height),
                ],
            }
        except Exception as exc:
            return {"window_error": str(exc)}

    def handle(reply: object) -> None:
        if not reply.data or reply.category != record.FromServer:
            return
        data = reply.data
        while data:
            event, data = rq.EventField(None).parse_binary_value(
                data, record_display.display, None, None
            )
            if (
                event.type == X.ButtonPress
                and event.detail in pointer_buttons
            ):
                record_pointer_click(
                    int(event.root_x),
                    int(event.root_y),
                    pointer_buttons[event.detail],
                    foreground_window(),
                )

    context = record_display.record_create_context(
        0,
        [record.AllClients],
        [
            {
                "core_requests": (0, 0),
                "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0),
                "ext_replies": (0, 0, 0, 0),
                "delivered_events": (0, 0),
                "device_events": (X.ButtonPress, X.ButtonRelease),
                "errors": (0, 0),
                "client_started": False,
                "client_died": False,
            }
        ],
    )
    record_display.record_enable_context(context, handle)
    record_display.record_free_context(context)


if len(sys.argv) == 4 and sys.argv[1] == "--hit-test":
    hit_target, hit_visited = accessible_at_point(
        int(sys.argv[2]), int(sys.argv[3])
    )
    print(
        json.dumps(
            {"target": hit_target, "visited_nodes": hit_visited},
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)


listener = Atspi.EventListener.new(on_event)
for event_type in (
    "focus:",
    "object:state-changed:focused",
    "object:state-changed:selected",
    "object:state-changed:checked",
    "object:state-changed:pressed",
    "object:state-changed:expanded",
    "object:state-changed:armed",
    "object:active-descendant-changed",
    "object:selection-changed",
):
    listener.register(event_type)

for worker_index in range(hit_test_workers):
    threading.Thread(
        target=click_resolution_loop,
        daemon=True,
        name=f"atspi-hit-test-{worker_index + 1}",
    ).start()
threading.Thread(
    target=transient_hover_loop,
    daemon=True,
    name="atspi-transient-hover",
).start()
threading.Thread(target=xrecord_loop, daemon=True, name="xrecord").start()
print(f"AT-SPI event/click watcher armed: {output}", flush=True)
Atspi.event_main()
