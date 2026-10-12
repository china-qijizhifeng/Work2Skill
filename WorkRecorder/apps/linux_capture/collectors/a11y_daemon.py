#!/usr/bin/env python3
"""Warm AT-SPI a11y daemon for the MyPCBench persist VM.

Initialises Atspi ONCE and serves the active-window (or all-windows)
accessibility tree over HTTP. Point hit-tests are scoped to the WM foreground
app by default, with `scope=all` kept for diagnostics. Reuses the exact walk/score logic from
scripts/a11y_collector.py's GUEST_DUMP so output is identical, minus the
per-request `python3` + `Atspi.init()` cold-start.

Endpoints (GET):
  /health                          -> {"ok": true, ...}
  /a11y?depth=6&max_nodes=400&all_windows=0  -> accessibility tree JSON
  /at_point?x=&y=&scope=foreground -> foreground-scoped point hit-test

Bind: 127.0.0.1:7070 (reach from a Mac via:  ssh -L 7070:127.0.0.1:7070 ...).
"""
import os, json, time, threading, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

os.environ.setdefault('DISPLAY', ':0')
if not os.environ.get('XAUTHORITY') and os.path.exists(f'/run/user/{os.getuid()}/gdm/Xauthority'):
    os.environ['XAUTHORITY'] = f'/run/user/{os.getuid()}/gdm/Xauthority'
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
Atspi.init()  # ONCE — this is the expensive part we keep warm

_ST = ('ACTIVE', 'FOCUSED', 'FOCUSABLE', 'SELECTED', 'CHECKED',
       'EDITABLE', 'ENABLED', 'SHOWING', 'VISIBLE')
# Apps we must never walk: querying their AT-SPI components (get_extents)
# trips an `ATK_IS_COMPONENT` assertion bug that crashes gnome-shell / the whole
# session. 'gjs' is the desktop-icons (DING) extension; 'gnome-shell' hosts
# DING's objects + the shell chrome; 'mutter-x11-frames' is window decorations.
# None carry app content worth hit-testing (shell chrome is reachable by coords).
SKIP_APPS = ['mutter-x11-frames', 'gjs', 'gnome-shell']

# AT-SPI / GLib is not thread-safe; serialise all tree access.
_LOCK = threading.Lock()


def states(n):
    try:
        ss = n.get_state_set(); out = []
        for s in _ST:
            try:
                if ss.contains(getattr(Atspi.StateType, s)):
                    out.append(s)
            except Exception:
                pass
        return out
    except Exception:
        return []


def bbox(n):
    try:
        e = n.get_extents(Atspi.CoordType.SCREEN)
        return [e.x, e.y, e.width, e.height]
    except Exception:
        return None


def role_name(n):
    try:
        return n.get_role_name()
    except Exception:
        return None


def is_active(n):
    try:
        return n.get_state_set().contains(Atspi.StateType.ACTIVE)
    except Exception:
        return False


def node_name(n):
    try:
        return n.get_name()
    except Exception:
        return ''


def app_name(app):
    try:
        return app.get_name()
    except Exception:
        return ''


def app_skipped(name):
    low = (name or '').lower()
    return any(s in low for s in SKIP_APPS)


def process_id(n):
    try:
        return n.get_process_id()
    except Exception:
        return None


def _prop_text(dpy, win, atom_name):
    try:
        atom = dpy.intern_atom(atom_name, only_if_exists=True)
        if not atom:
            return None
        prop = win.get_full_property(atom, 0)
        if prop is None:
            return None
        value = prop.value
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            raw = value
        else:
            try:
                raw = bytes(value)
            except Exception:
                return str(value)
        return raw.replace(b'\x00', b' ').decode('utf-8', 'replace').strip()
    except Exception:
        return None


def _prop_ints(dpy, win, atom_name):
    try:
        atom = dpy.intern_atom(atom_name, only_if_exists=True)
        if not atom:
            return []
        prop = win.get_full_property(atom, 0)
        if prop is None:
            return []
        return [int(v) for v in prop.value]
    except Exception:
        return []


def _x_window_info(dpy, win_id, source):
    try:
        from Xlib import X
        root = dpy.screen().root
        win = dpy.create_resource_object('window', int(win_id))
        attrs = win.get_attributes()
        if attrs.map_state != X.IsViewable:
            return None
        wm_state = _prop_ints(dpy, win, 'WM_STATE')
        if wm_state and wm_state[0] == 3:  # IconicState/minimized.
            return None
        geom = win.get_geometry()
        if geom.width <= 0 or geom.height <= 0:
            return None
        pos = win.translate_coords(root, 0, 0)
        x, y, w, h = int(pos.x), int(pos.y), int(geom.width), int(geom.height)
        ext = _prop_ints(dpy, win, '_NET_FRAME_EXTENTS')
        if len(ext) >= 4:
            left, right, top, bottom = ext[:4]
            x -= left
            y -= top
            w += left + right
            h += top + bottom
        try:
            wm_instance, wm_class = win.get_wm_class() or (None, None)
        except Exception:
            wm_instance, wm_class = None, None
        pid = None
        vals = _prop_ints(dpy, win, '_NET_WM_PID')
        if vals:
            pid = vals[0]
        name = _prop_text(dpy, win, '_NET_WM_NAME') or _prop_text(dpy, win, 'WM_NAME')
        return {
            'window_id': hex(int(win_id)),
            'pid': pid,
            'wm_class': wm_class,
            'wm_instance': wm_instance,
            'name': name,
            'bbox': [x, y, w, h],
            'source': source,
            'reliable': True,
        }
    except Exception:
        return None


def _x_any_window_info(dpy, win, source):
    try:
        from Xlib import X
        root = dpy.screen().root
        attrs = win.get_attributes()
        if attrs.map_state != X.IsViewable:
            return None
        geom = win.get_geometry()
        if geom.width <= 0 or geom.height <= 0:
            return None
        pos = win.translate_coords(root, 0, 0)
        try:
            wm_instance, wm_class = win.get_wm_class() or (None, None)
        except Exception:
            wm_instance, wm_class = None, None
        pid = None
        vals = _prop_ints(dpy, win, '_NET_WM_PID')
        if vals:
            pid = vals[0]
        name = _prop_text(dpy, win, '_NET_WM_NAME') or _prop_text(dpy, win, 'WM_NAME')
        return {
            'window_id': hex(int(win.id)),
            'pid': pid,
            'wm_class': wm_class,
            'wm_instance': wm_instance,
            'name': name,
            'bbox': [int(pos.x), int(pos.y), int(geom.width), int(geom.height)],
            'override_redirect': bool(attrs.override_redirect),
            'source': source,
        }
    except Exception:
        return None


def _x_lineage_at_point(dpy, x, y, maxdepth=40):
    root = dpy.screen().root
    parent = root
    lineage = []
    for _ in range(maxdepth):
        try:
            children = parent.query_tree().children
        except Exception:
            break
        picked = None
        # XQueryTree returns children bottom-to-top; reverse to test topmost first.
        for child in reversed(children):
            info = _x_any_window_info(dpy, child, 'point')
            if info is not None and contains(info.get('bbox'), x, y):
                picked = (child, info)
                break
        if picked is None:
            break
        child, info = picked
        lineage.append(info)
        parent = child
    return lineage


def _lineage_matches_window(lineage, win_info):
    if not lineage or not win_info:
        return True
    target_id = win_info.get('window_id')
    target_pid = win_info.get('pid')
    target_names = [win_info.get('wm_class'), win_info.get('wm_instance')]
    has_identity = False
    for info in lineage:
        if info.get('window_id') == target_id:
            return True
        if info.get('pid') is not None:
            has_identity = True
            if target_pid is not None and int(info.get('pid')) == int(target_pid):
                return True
        names = [info.get('wm_class'), info.get('wm_instance')]
        if any(names):
            has_identity = True
        if any(_related_names(a, b) for a in names for b in target_names):
            return True
        if info.get('override_redirect'):
            has_identity = True
    return not has_identity


def _pointer_overlay_foreground(lineage, client):
    overlay = next(
        (i for i in reversed(lineage)
         if i.get('wm_class') or i.get('wm_instance') or i.get('pid') is not None or i.get('name')),
        lineage[-1] if lineage else None,
    )
    if overlay is None:
        return None
    out = dict(overlay)
    out.update({
        'source': 'point_window',
        'reliable': False,
        'error': 'point_window_not_foreground_client',
        'client_under_point': client,
        'pointer_lineage': lineage[-8:],
    })
    return out


def foreground_window(x=None, y=None):
    """Return the top WM client at the point, falling back to active window."""
    try:
        from Xlib import display
        dpy = display.Display()
    except Exception as e:
        return {'reliable': False, 'error': 'x11_unavailable: %s' % e}
    try:
        root = dpy.screen().root
        lineage = _x_lineage_at_point(dpy, x, y) if x is not None and y is not None else []
        stacking = _prop_ints(dpy, root, '_NET_CLIENT_LIST_STACKING')
        if x is not None and y is not None:
            for win_id in reversed(stacking):
                info = _x_window_info(dpy, win_id, 'stacking')
                if info is not None and contains(info.get('bbox'), x, y):
                    if not _lineage_matches_window(lineage, info):
                        overlay = _pointer_overlay_foreground(lineage, info)
                        if overlay is not None:
                            return overlay
                    return info
        active = _prop_ints(dpy, root, '_NET_ACTIVE_WINDOW')
        if active:
            info = _x_window_info(dpy, active[0], 'active')
            if info is not None:
                return info
        return {'reliable': False, 'error': 'no_active_or_stacking_window'}
    finally:
        try:
            dpy.close()
        except Exception:
            pass


def _compact_name(value):
    text = (value or '').lower()
    text = text.replace('mozilla firefox', 'firefox')
    text = text.replace('org.gnome.', '')
    return re.sub(r'[^a-z0-9]+', '', text)


def _name_aliases(value):
    compact = _compact_name(value)
    out = {compact} if compact else set()
    aliases = {
        'firefox': {'firefox', 'navigator'},
        'navigator': {'firefox', 'navigator'},
        'nautilus': {'nautilus', 'files'},
        'files': {'nautilus', 'files'},
        'soffice': {'soffice', 'libreoffice'},
        'libreoffice': {'soffice', 'libreoffice'},
    }
    out |= aliases.get(compact, set())
    return {v for v in out if v}


def _related_names(a, b):
    aa = _name_aliases(a)
    bb = _name_aliases(b)
    if aa & bb:
        return True
    for x in aa:
        for y in bb:
            if len(x) >= 4 and len(y) >= 4 and (x in y or y in x):
                return True
    return False


def _matches_foreground(app, root, fg):
    if not fg or not fg.get('reliable'):
        return False
    fg_pid = fg.get('pid')
    for app_pid in (process_id(app), process_id(root)):
        if fg_pid is not None and app_pid is not None:
            try:
                if int(fg_pid) == int(app_pid):
                    return True
            except Exception:
                pass
    app_values = [app_name(app)]
    wm_identity_values = [fg.get('wm_class'), fg.get('wm_instance')]
    if any(_related_names(a, w) for a in app_values for w in wm_identity_values):
        return True
    # Window titles are not app identities ("Home", "Settings", etc. collide
    # across apps). Use them only when the WM did not expose class/instance.
    if not any(wm_identity_values):
        return _related_names(node_name(root), fg.get('name'))
    return any(_related_names(a, fg.get('name')) for a in app_values)


def scoped_toplevels(tops, fg):
    if not fg or not fg.get('reliable'):
        return [], 'no_foreground_window'
    scoped = [(app, root) for app, root in tops if _matches_foreground(app, root, fg)]
    if not scoped:
        return [], 'foreground_app_not_in_atspi'
    return scoped, None


def list_toplevels():
    desk = Atspi.get_desktop(0); out = []
    for i in range(desk.get_child_count()):
        app = desk.get_child_at_index(i)
        if app is None:
            continue
        # Skip DING (the desktop-icons extension runs as the 'gjs' app) and
        # 'mutter-x11-frames'. Querying their AT-SPI components (get_extents /
        # get_child_*) trips an `ATK_IS_COMPONENT` assertion bug inside
        # gnome-shell that, under continuous probing, crashes the whole session
        # ("Oh no! Something has gone wrong"). They carry no useful content for
        # hit-testing anyway (the only desktop content is a few icons).
        if app_skipped(app_name(app)):
            continue
        out.append((app, app))
        try:
            nc = app.get_child_count()
        except Exception:
            nc = 0
        for j in range(nc):
            n = app.get_child_at_index(j)
            if n is not None:
                out.append((app, n))
    return out


def walk(n, depth, cnt, maxdepth, maxnodes):
    if cnt[0] >= maxnodes or depth > maxdepth:
        return None
    try:
        role = n.get_role_name(); name = n.get_name()
    except Exception:
        return None
    d = {'role': role, 'name': name, 'bbox': bbox(n), 'states': states(n)}
    cnt[0] += 1
    kids = []
    try:
        nc = n.get_child_count()
    except Exception:
        nc = 0
    d['child_count'] = nc
    for i in range(nc):
        if cnt[0] >= maxnodes:
            break
        try:
            c = n.get_child_at_index(i)
        except Exception:
            continue
        if c is not None:
            cd = walk(c, depth + 1, cnt, maxdepth, maxnodes)
            if cd is not None:
                kids.append(cd)
    if kids:
        d['children'] = kids
    if len(kids) < nc:
        d['omitted_children'] = nc - len(kids)
    return d


def meta(app, n):
    return {'app': app_name(app), 'window': node_name(n),
            'role': role_name(n), 'bbox': bbox(n), 'active': is_active(n),
            'pid': process_id(app) or process_id(n),
            'states': states(n)}


def score(item):
    app, n = item
    an = app_name(app); name = node_name(n); sc = 0
    if is_active(n):
        sc += 1000
    if app_skipped(an):
        sc -= 400
    if name:
        sc += 20
    if role_name(n) == 'frame':
        sc += 10
    try:
        if n.get_child_count() > 0:
            sc += 5
    except Exception:
        pass
    return sc


def dump(maxdepth, maxnodes, all_windows):
    tops = list_toplevels()
    summary = []
    for app, n in tops:
        try:
            summary.append(meta(app, n))
        except Exception:
            pass
    if all_windows:
        windows = []; total = 0; any_trunc = False
        for app, n in sorted(tops, key=score, reverse=True):
            cnt = [0]
            tree = walk(n, 0, cnt, maxdepth, maxnodes)
            trunc = cnt[0] >= maxnodes
            any_trunc = any_trunc or trunc
            total += cnt[0]
            windows.append({'meta': meta(app, n), 'tree': tree,
                            'nodes': cnt[0], 'truncated': trunc})
        return {'frames': summary, 'windows': windows, 'nodes': total,
                'truncated': any_trunc, 'mode': 'all_windows'}
    target = sorted(tops, key=score, reverse=True)[0] if tops else None
    cnt = [0]
    return {'frames': summary,
            'active_app': app_name(target[0]) if target else None,
            'active_window': node_name(target[1]) if target else None,
            'active_role': role_name(target[1]) if target else None,
            'tree': walk(target[1], 0, cnt, maxdepth, maxnodes) if target else None,
            'nodes': cnt[0], 'truncated': cnt[0] >= maxnodes,
            'mode': 'best_window'}


def contains(box, x, y):
    return (box is not None and box[0] <= x < box[0] + box[2]
            and box[1] <= y < box[1] + box[3])


def node_info(n, app, depth):
    box = bbox(n)
    return {'app': app_name(app) if app is not None else None,
            'app_pid': process_id(app) if app is not None else None,
            'role': role_name(n), 'name': node_name(n), 'bbox': box,
            'states': states(n), 'depth': depth,
            'area': (box[2] * box[3]) if box else None}


def _walk_hits(n, app, x, y, depth, path, hits, cnt, maxdepth, maxnodes):
    # Pruning walk: descend only into nodes whose bbox contains (x, y). Fast,
    # and correct for any element actually visible on screen (its ancestor
    # chain contains the click). Off-screen / scrolled-out nodes are not
    # reachable this way, but you cannot click what you cannot see.
    if cnt[0] >= maxnodes or depth > maxdepth:
        return
    cnt[0] += 1
    info = node_info(n, app, depth)
    if not contains(info['bbox'], x, y):
        return
    npath = path + [info]
    hits.append(npath)
    try:
        nc = n.get_child_count()
    except Exception:
        nc = 0
    for i in range(nc):
        if cnt[0] >= maxnodes:
            break
        try:
            c = n.get_child_at_index(i)
        except Exception:
            continue
        if c is not None:
            _walk_hits(c, app, x, y, depth + 1, npath, hits, cnt, maxdepth, maxnodes)


def _gap_descend(root, x, y):
    """Native AT-SPI get_accessible_at_point, descended to the leaf."""
    cur = root; path = []
    for _ in range(60):
        try:
            child = cur.get_accessible_at_point(x, y, Atspi.CoordType.SCREEN)
        except Exception:
            child = None
        if child is None:
            break
        try:
            same = (child == cur)
        except Exception:
            same = False
        if same:
            break
        path.append(node_info(child, None, len(path)))
        cur = child
    return path


def mouse_position():
    try:
        out = __import__('subprocess').check_output(
            ['xdotool', 'getmouselocation', '--shell'], text=True)
        v = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
        return int(v['X']), int(v['Y']), 'xdotool'
    except Exception:
        pass
    try:
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk
        _s, x, y = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
        return int(x), int(y), 'gdk'
    except Exception as e:
        raise RuntimeError('no mouse pos: %s' % e)


def at_point(x, y, maxdepth, maxnodes, scope='foreground'):
    tops = list_toplevels()
    fg = None
    rejection_reason = None
    if scope in ('foreground', 'front', 'active'):
        fg = foreground_window(x, y)
        tops, rejection_reason = scoped_toplevels(tops, fg)
    hits = []; cnt = [0]
    for app, root in tops:
        _walk_hits(root, app, x, y, 0, [], hits, cnt, maxdepth, maxnodes)

    INTERACTIVE = {'push button', 'button', 'link', 'check box', 'radio button',
                   'combo box', 'menu item', 'list item', 'tab', 'toggle button',
                   'entry', 'text', 'spin button', 'slider', 'menu', 'page tab'}

    def rank(p):
        # higher is better: prefer named + interactive, then named, then
        # smaller (more specific) area.
        leaf = p[-1]
        nm = (leaf.get('name') or '').strip()
        role = (leaf.get('role') or '')
        area = leaf.get('area') or 10**18
        return (1 if (nm and role in INTERACTIVE) else 0,
                1 if nm else 0,
                -area)

    best = None      # smartest pick: named/interactive, most specific
    deepest = None   # raw deepest node
    smallest = None  # raw smallest-area node
    ranked = []
    if hits:
        ranked = sorted(hits, key=rank, reverse=True)
        best = ranked[0]
        deepest = sorted(hits, key=lambda p: (len(p), -(p[-1]['area'] or 10**18)),
                         reverse=True)[0]
        smallest = min(hits, key=lambda p: (p[-1]['area'] or 10**18))
    # native get_accessible_at_point, best (deepest) over scanned toplevels
    gap_best = []
    for app, root in tops:
        try:
            if not contains(bbox(root), x, y):
                continue
        except Exception:
            pass
        p = _gap_descend(root, x, y)
        if len(p) > len(gap_best):
            gap_best = p
    # de-dup candidates by (role,name,bbox), keep best-ranked, top 6
    seen = {}; cands = []
    for p in ranked:
        leaf = p[-1]
        k = (leaf.get('role'), leaf.get('name'), tuple(leaf.get('bbox') or []))
        if k in seen:
            continue
        seen[k] = 1
        cands.append(leaf)
        if len(cands) >= 6:
            break
    return {'x': x, 'y': y,
            'scope': scope,
            'foreground': fg,
            'reliable': rejection_reason is None and scope in ('foreground', 'front', 'active'),
            'rejection_reason': rejection_reason,
            'hit': best[-1] if best else None,          # smart pick
            'hit_path': best,
            'smallest_hit': smallest[-1] if smallest else None,
            'deepest_hit': deepest[-1] if deepest else None,
            'candidates': cands,
            'n_containing': len(hits),
            'n_scanned_toplevels': len(tops),
            'gap_hit': gap_best[-1] if gap_best else None,
            'gap_path_len': len(gap_best)}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)

        def qi(k, d):
            try:
                return int(q.get(k, [d])[0])
            except Exception:
                return d
        if u.path == '/health':
            return self._send(200, {'ok': True, 'ts': time.time()})
        if u.path == '/at_point':
            depth = qi('depth', 14); maxn = qi('max_nodes', 12000)
            scope = q.get('scope', ['foreground'])[0].lower()
            if q.get('all_apps', ['0'])[0].lower() in ('1', 'true', 'yes'):
                scope = 'all'
            if scope not in ('foreground', 'front', 'active', 'all'):
                scope = 'foreground'
            t0 = time.time()
            try:
                with _LOCK:
                    if 'x' in q and 'y' in q:
                        x = qi('x', 0); y = qi('y', 0); src = 'param'
                    else:
                        x, y, src = mouse_position()
                    res = at_point(x, y, depth, maxn, scope)
                res['source'] = src
                res['elapsed_ms'] = round((time.time() - t0) * 1000, 1)
                return self._send(200, res)
            except Exception as e:
                return self._send(500, {'error': str(e)})
        if u.path == '/a11y':
            depth = min(32, max(1, qi('depth', 6))); maxn = min(20000, max(1, qi('max_nodes', 400)))
            allw = q.get('all_windows', ['0'])[0].lower() in ('1', 'true', 'yes')
            t0 = time.time()
            try:
                with _LOCK:
                    res = dump(depth, maxn, allw)
                res['elapsed_ms'] = round((time.time() - t0) * 1000, 1)
                return self._send(200, res)
            except Exception as e:
                return self._send(500, {'error': str(e)})
        return self._send(404, {'error': 'use /a11y or /health'})


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('WORKRECORDER_TREE_PORT', '7070'))), H)
    print(f'AT-SPI tree service on {srv.server_address}', flush=True)
    srv.serve_forever()
