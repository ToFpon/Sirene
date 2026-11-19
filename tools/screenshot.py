"""Capture de la fenêtre avec de faux écouteurs 6i (valeurs de Tof), sous Xvfb :

    xvfb-run -a -s "-screen 0 1280x1000x24" python3.12 tools/screenshot.py SORTIE.png [--dark] [--empty]
        [--size=LxH] [--scroll=PIXELS] [--tab=status|gestures|sound|device]
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="sirene-shot-")
_size = next((a[7:] for a in sys.argv if a.startswith("--size=")), "560x900").split("x")
os.makedirs(os.path.join(os.environ["XDG_CONFIG_HOME"], "sirene"))
with open(os.path.join(os.environ["XDG_CONFIG_HOME"], "sirene", "settings.json"), "w") as _fh:
    _fh.write('{"window_width": %d, "window_height": %d}' % (int(_size[0]), int(_size[1])))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from fake_buds import FakeWatcher, buds_6i  # noqa: E402
from sirene.app import SireneApp  # noqa: E402

out = sys.argv[1]
opts = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in sys.argv[2:] if a.startswith("--"))
watchers, fakes = [], []


class NoPause:
    def pause_later(self):
        pass

    def resume_later(self):
        pass


def connect(address, channel):
    fakes.append(buds_6i())
    return fakes[-1].connect(address, channel)


app = SireneApp(watcher=lambda cb: watchers.append(FakeWatcher(cb)) or watchers[-1], connect=connect,
                autopause=NoPause(), timeout=0.5)


def shoot(win):
    snap = Gtk.WidgetPaintable.new(win)
    width, height = win.get_width(), win.get_height()
    s = Gtk.Snapshot()
    snap.snapshot(s, width, height)
    node = s.to_node()
    tex = win.get_native().get_renderer().render_texture(node, None)
    tex.save_to_png(out)
    print(out, width, "x", height)
    app.quit()
    return False


def ready(win):
    if "tab" in opts:
        win.device_page.stack.set_visible_child_name(opts["tab"])
    if "scroll" in opts:
        GLib.timeout_add(300, lambda: (win.device_page.stack.get_visible_child().get_first_child().get_vadjustment().set_value(float(opts["scroll"])), False)[1])
    GLib.timeout_add(900, shoot, win)
    return False


def start(_a, win):
    if "dark" in opts:
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    if "empty" not in opts:
        watchers[0].announce(True)

    def wait():
        if "empty" in opts or app.state == "device" and app.device.ready.is_set():
            GLib.timeout_add(400, ready, win)
            return False
        return True
    GLib.timeout_add(100, wait)


app.connect("window-added", start)
app.run([sys.argv[0]])
for f in fakes:
    f.close()
