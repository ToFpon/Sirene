"""Interface de Sirène avec de faux écouteurs (FreeBuds 6i, valeurs de la sortie de sirene.probe chez Tof) et un
faux BlueZ. Doit finir par « Aucune erreur. »

    xvfb-run -a python3.12 tests/ui_smoke.py
    LANGUAGE=en xvfb-run -a python3.12 tests/ui_smoke.py
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="sirene-ui-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from fake_buds import FakeWatcher, buds_6i  # noqa: E402
from sirene.app import SireneApp  # noqa: E402
from sirene.backend.protocol import Packet  # noqa: E402
from sirene.i18n import tr  # noqa: E402
from sirene.ui.labels import label  # noqa: E402

errors: list = []


class FakePause:
    def __init__(self):
        self.calls = []

    def pause_later(self):
        self.calls.append("pause")

    def resume_later(self):
        self.calls.append("resume")


fakes = []


def connect(address, channel):
    f = buds_6i()
    fakes.append(f)
    return f.connect(address, channel)


watchers = []
pause = FakePause()
app = SireneApp(watcher=lambda cb: watchers.append(FakeWatcher(cb)) or watchers[-1], connect=connect,
                autopause=pause, timeout=0.5)
steps = []


def step(fn):
    steps.append(fn)
    return fn


class Wait:
    def __init__(self, seconds=0.3, until=None):
        self.seconds, self.until = seconds, until


def check(cond, msg):
    if cond:
        print("✓", msg)
    else:
        errors.append("ÉCHEC : " + msg)
        print("✗", msg)


def walk(w):
    yield w
    c = w.get_first_child()
    while c is not None:
        yield from walk(c)
        c = c.get_next_sibling()


def find(win, kind, pred=lambda w: True):
    return [w for w in walk(win) if isinstance(w, kind) and pred(w)]


def visible_titles(win, kind):
    return [w.get_title() for w in find(win, kind) if w.get_mapped()]


CRITICALS = []
_err_r, _err_w = os.pipe()
_err_orig = os.dup(2)
os.dup2(_err_w, 2)


def _tee():
    with os.fdopen(_err_r, "rb", 0) as f:
        for line in iter(f.readline, b""):
            os.write(_err_orig, line)
            if (b"-CRITICAL **" in line or b"-WARNING **" in line) and b"a11y" not in line:
                CRITICALS.append(line.decode("utf-8", "replace").strip())


threading.Thread(target=_tee, daemon=True).start()


@step
def sans_ecouteurs(win):
    check(win.stack.get_visible_child_name() == "none", "aucun écouteur : page d'attente")


@step
def connexion(win):
    watchers[0].announce(True)
    yield Wait(5, until=lambda: app.state == "device" and app.device.ready.is_set())
    yield Wait(0.4)
    check(win.stack.get_visible_child_name() == "device", "écouteurs connectés : leur page")
    check(fakes and fakes[0].channel == 1, "canal RFCOMM 1 (6i)")
    page = win.device_page
    check(page.left.value.get_label() == "100 %" and page.case.value.get_label() == "67 %",
          "piles : gauche 100 %, boîtier 67 %")
    check(page.left.state.get_label() == tr("Porté"), "écouteur gauche porté (lu au démarrage)")
    check("HarmonyOS" in page.firmware.get_label(), "micrologiciel affiché")


@step
def pas_de_pause_au_demarrage(win):
    check(pause.calls == [], "démarrage (« pas portés » puis l'état lu) : ni pause ni reprise")


@step
def lignes_presentes(win):
    titles = visible_titles(win, Adw.ComboRow)
    for t in (tr("Double tape, écouteur gauche"), tr("Triple tape, écouteur droit"),
              tr("Modes parcourus, écouteur gauche"), tr("Glisser sur la tige"), tr("Égaliseur"), tr("Priorité")):
        check(t in titles, f"ligne « {t} »")
    check(tr("Double tape, écouteur pendant un appel") not in titles, "pas de ligne inventée")
    row = [r for r in find(win, Adw.ComboRow) if r.get_title() == tr("Triple tape, écouteur gauche")][0]
    items = [row.get_model().get_string(i) for i in range(row.get_model().get_n_items())]
    check("4" in items and label("next") in items, "code inconnu « 4 » montré tel quel, à côté des connus")
    check(row.get_selected() == items.index(label("next")), "choix actuel : morceau suivant")


@step
def controle_du_bruit(win):
    page = win.device_page
    check(page.anc_buttons["off"].get_active(), "contrôle du bruit : désactivé")
    fakes[0].answer(Packet.write(b"\x2b\x04", [(1, bytes((1, 0xff)))]), Packet(b"\x2b\x04", [(2, 0)]))
    fakes[0].answer(Packet.read(b"\x2b\x2a", [1, 2]), Packet(b"\x2b\x2a", [(1, b"\x00\x01")]))
    page.anc_buttons["cancellation"].set_active(True)
    yield Wait(3, until=lambda: app.device.get("anc", "mode") == "cancellation")
    check(Packet(b"\x2b\x04", [(1, bytes((1, 0xff)))]).to_bytes() in fakes[0].sent, "trame de réduction envoyée")
    yield Wait(0.2)
    level = [r for r in find(win, Adw.ComboRow) if r.get_title() == tr("Niveau")][0]
    check(level.get_mapped() and level.get_model().get_string(level.get_selected()) == label("normal"),
          "réduction : ligne « Niveau » sur Normal")


@step
def geste_change(win):
    row = [r for r in find(win, Adw.ComboRow) if r.get_title() == tr("Double tape, écouteur droit")][0]
    want = Packet.write(b"\x01\x1f", [(2, 2)])
    fakes[0].answer(want, Packet(b"\x01\x1f", [(127, b"\x00\x01\x86\xa0")]))
    items = [row.get_model().get_string(i) for i in range(row.get_model().get_n_items())]
    row.set_selected(items.index(label("next")))
    yield Wait(3, until=lambda: want.to_bytes() in fakes[0].sent)
    check(want.to_bytes() in fakes[0].sent, "double tape droit → morceau suivant envoyé")


@step
def refus_des_ecouteurs(win):
    """Les écouteurs ne répondent pas : message, et la ligne revient à l'ancienne valeur."""
    row = [r for r in find(win, Adw.SwitchRow) if r.get_title() == tr("Faible latence")][0]
    row.set_active(True)
    yield Wait(3, until=lambda: not row.get_active())
    check(not row.get_active(), "réglage sans réponse : l'interrupteur revient")


@step
def pause_au_retrait(win):
    fakes[0].push(Packet(b"\x2b\x25", [(1, 1), (2, 0), (3, 0), (4, 0)]))
    yield Wait(2, until=lambda: pause.calls)
    check(pause.calls == ["pause"], "écouteur droit retiré : pause")
    check(win.device_page.right.state.get_label() == tr("Retiré"), "droit : « Retiré »")
    fakes[0].push(Packet(b"\x2b\x25", [(1, 1), (2, 1), (3, 0), (4, 0)]))
    yield Wait(2, until=lambda: len(pause.calls) == 2)
    check(pause.calls == ["pause", "resume"], "remis : reprise")


@step
def canal_ferme_puis_rouvert(win):
    """Les écouteurs ferment leur canal alors que BlueZ les dit connectés : Sirène le rouvre."""
    first = app.device
    fakes[0].close()
    yield Wait(5, until=lambda: app.device is not None and app.device is not first and app.device.ready.is_set())
    check(app.device is not first and len(fakes) == 2, "canal rouvert")


@step
def deconnexion(win):
    dev = app.device
    watchers[0].announce(False)
    yield Wait(0.4)
    check(win.stack.get_visible_child_name() == "none" and app.device is None and not dev.alive,
          "écouteurs partis : canal fermé, page d'attente")


@step
def modele_inconnu(win):
    watchers[0].announce(True, name="Souris")
    yield Wait(0.4)
    check(app.state == "none" and len(fakes) == 2, "appareil non pris en charge : rien n'est tenté")


@step
def preferences_et_a_propos(win):
    app.activate_action("preferences", None)
    app.activate_action("about", None)
    yield Wait(0.5)
    wins = [w for w in Gtk.Window.list_toplevels() if w is not win and w.get_visible()]
    check(any(isinstance(w, Adw.PreferencesWindow) for w in wins), "préférences ouvertes")
    check(any(isinstance(w, Adw.AboutWindow) for w in wins), "« À propos » ouvert")
    for w in wins:
        w.close()


def run_all(win):
    def driver():
        for fn in steps:
            gen = fn(win)
            if gen is not None and hasattr(gen, "__next__"):
                yield from gen
            yield Wait(0.1)

    it = driver()

    def tick():
        try:
            w = next(it)
        except StopIteration:
            app.quit()
            return False
        except Exception:
            errors.append(traceback.format_exc())
            app.quit()
            return False
        end = time.time() + w.seconds

        def waiting():
            if w.until is None and time.time() < end or w.until is not None and not w.until() \
                    and time.time() < end:
                return True
            GLib.idle_add(tick)
            return False
        GLib.timeout_add(20, waiting)
        return False

    GLib.idle_add(tick)
    return False


started = []


def on_window(_a, w):
    if not started:
        started.append(w)
        GLib.timeout_add(300, run_all, w)


app.connect("window-added", on_window)
app.run([sys.argv[0]])
for f in fakes:
    f.close()
shutil.rmtree(TMP, ignore_errors=True)
sys.stderr.flush()
time.sleep(0.2)
for line in CRITICALS:
    errors.append("ÉCHEC : avertissement critique de GTK / GLib : " + line)
print("\n".join(errors) if errors else "\nAucune erreur.")
sys.exit(1 if errors else 0)
