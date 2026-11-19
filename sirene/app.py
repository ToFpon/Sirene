"""Point d'entrée de Sirène.

Une seule instance. Suit BlueZ (signaux D-Bus, aucune interrogation) : des écouteurs pris en charge se
connectent → canal ouvert (dans un fil : la connexion RFCOMM peut prendre quelques secondes) ; ils partent →
canal fermé. Jamais de tentative vers des écouteurs absents (la boucle « RFCOMM failed » de MyBuds).
Les valeurs des écouteurs arrivent des fils du moteur et passent dans la boucle GLib par idle_add.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, features  # noqa: E402
from .backend import models  # noqa: E402
from .backend.device import Device, rfcomm_connect  # noqa: E402
from .i18n import tr  # noqa: E402

log = logging.getLogger("sirene")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RETRY_S = (2, 5, 10)            # écouteurs tout juste connectés : leur canal n'est pas toujours prêt


class SireneApp(Adw.Application):
    def __init__(self, watcher=None, connect=rfcomm_connect, autopause=None, timeout=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self._watcher_factory = watcher
        self._connect = connect
        self._timeout = timeout
        self.autopause = autopause
        self.watcher = None
        self.window = None
        self.device: Device | None = None
        self.state = "none"             # none, busy, fail, device
        self.bt = None                  # BtDevice suivi
        self.bt_name = ""
        self.fail_detail = ""
        self._attempt = 0
        self._retry_id = 0
        self._worn = None

    # --- démarrage ---

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is not None:
            css = Gtk.CssProvider()
            css.load_from_path(os.path.join(DATA_DIR, "base.css"))
            Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        from .ui.preferences import apply_theme
        apply_theme()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (self.quit(), False)[1])
        for name, cb, accels in (("preferences", self._prefs, ["<Control>comma"]),
                                 ("about", self._about, []),
                                 ("quit", self.quit, ["<Control>q"])):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(a)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        if self.autopause is None:
            from .backend.autopause import AutoPause
            self.autopause = AutoPause()
        if self._watcher_factory is None:
            from .backend.bluez import Watcher
            self._watcher_factory = Watcher
        self.watcher = self._watcher_factory(self._bt_changed)
        self._pick()

    def do_activate(self):
        if self.window is None:
            from .ui.window import MainWindow
            self.window = MainWindow(self)
        self.window.present()

    def do_shutdown(self):
        if self.device is not None:
            self.device.stop()
        if self.watcher is not None:
            self.watcher.stop()
        Adw.Application.do_shutdown(self)

    # --- suivi de BlueZ ---

    def _pick(self):
        """Premiers écouteurs pris en charge et connectés, si on n'en suit pas déjà."""
        if self.bt is not None:
            return
        for d in self.watcher.devices.values():
            if d.connected and models.find(d.name):
                self._open(d)
                return

    def _bt_changed(self, d):
        if self.bt is not None and d.address == self.bt.address:
            if not d.connected:
                self._close()
                self._set_state("none")
                self._pick()                    # d'autres écouteurs connectés ?
            elif self.state == "fail":
                self._open(d)
            return
        if d.connected and self.bt is None and models.find(d.name):
            self._open(d)

    def _open(self, d, attempt=0):
        self._cancel_retry()
        self.bt, self.bt_name, self._attempt = d, d.name, attempt
        model = models.find(d.name)
        self._set_state("busy")
        kw = {} if self._timeout is None else {"timeout": self._timeout}
        # « prêt » noté AU MOMENT de l'annonce (dans le fil du moteur) : l'idle_add passe plus tard, quand
        # dev.ready est déjà posé — les « pas portés / portés » du démarrage déclenchaient pause puis reprise.
        dev = Device(model, d.address, connect=self._connect, **kw,
                     on_change=lambda g, p, v: GLib.idle_add(self._on_change, dev, g, p, v, dev.ready.is_set()))

        def run():
            try:
                dev.start()
            except OSError as e:
                GLib.idle_add(self._open_failed, dev, d, e)
                return
            GLib.idle_add(self._opened, dev)
        threading.Thread(target=run, name="sirene-connexion", daemon=True).start()

    def _opened(self, dev):
        if self.bt is None or dev.address != self.bt.address or self.device is not None:
            dev.stop()                          # parti entre-temps
            return False
        self.device = dev
        # Les valeurs arrivées pendant la connexion n'ont pas été relayées (self.device pas encore posé) :
        # la page relit tout (show_state), le port part de la valeur connue.
        self._worn = dev.get("state", "in_ear")
        self._set_state("device")
        return False

    def _open_failed(self, dev, d, error):
        if self.bt is None or d.address != self.bt.address:
            return False
        log.info("connexion à %s : %s", d.address, error)
        if self._attempt < len(RETRY_S):
            delay = RETRY_S[self._attempt]
            self._retry_id = GLib.timeout_add_seconds(delay, self._retry_now, d, self._attempt + 1)
            return False
        self.fail_detail = tr("Le canal des écouteurs ne répond pas, ou un autre programme l'occupe "
                              "(OpenFreebuds, MyBuds…). Fermez-le, puis réessayez.") + f"\n({error})"
        self._set_state("fail")
        return False

    def _retry_now(self, d, attempt):
        self._retry_id = 0
        if self.bt is not None and d.address == self.bt.address and self.device is None:
            self._open(d, attempt)
        return False

    def _cancel_retry(self):
        if self._retry_id:
            GLib.source_remove(self._retry_id)
            self._retry_id = 0

    def retry(self):
        if self.bt is not None:
            self._open(self.bt)

    def _close(self):
        self._cancel_retry()
        if self.device is not None:
            self.device.stop()
        self.device = None
        self.bt = None
        self._worn = None

    def _set_state(self, state):
        self.state = state
        if self.window is not None:
            self.window.show_state()

    # --- valeurs des écouteurs ---

    def _on_change(self, dev, group, prop, value, ready=True):
        if dev is not self.device:
            return False
        if (group, prop) == ("device", "connected") and value is False:
            # Canal fermé par les écouteurs alors que BlueZ les dit connectés : on le rouvre
            bt = self.bt
            self._close()
            if bt is not None and bt.connected:
                self._open(bt)
            else:
                self._set_state("none")
            return False
        if (group, prop) == ("state", "in_ear"):
            self._wear_changed(value, ready)
        if self.window is not None:
            self.window.changed(group, prop)
        return False

    def _wear_changed(self, worn, ready):
        before, self._worn = self._worn, worn
        if not ready:                               # démarrage : « pas portés » d'office, puis l'état lu
            return
        if before is None or before == worn or not features.enabled("auto_pause"):
            return
        if not worn:
            self.autopause.pause_later()
        else:
            self.autopause.resume_later()

    def set_value(self, group, prop, value, on_fail=None):
        """Réglage choisi dans la fenêtre ; échec → message et `on_fail()` (la ligne reprend l'ancienne valeur)."""
        dev = self.device
        if dev is None:
            return

        def done(error):
            if error is not None:
                GLib.idle_add(self._set_failed, error, on_fail)
        dev.set(group, prop, value, done=done)

    def _set_failed(self, error, on_fail):
        log.info("réglage refusé : %s", error)
        if self.window is not None:
            from .ui.common import toast
            toast(self.window, tr("Les écouteurs n'ont pas pris en compte ce réglage"))
        if on_fail:
            on_fail()
        return False

    # --- fenêtres ---

    def _prefs(self):
        from .ui.preferences import PreferencesWindow
        PreferencesWindow(self.window).present()

    def _about(self):
        about = Adw.AboutWindow(
            transient_for=self.window, application_name=APP_NAME, application_icon=APP_ID, version=VERSION,
            developer_name="Tof", license_type=Gtk.License.GPL_3_0,
            comments=tr("Réglages des écouteurs HUAWEI FreeBuds"),
            website="https://github.com/ToFpon/Sirene", issue_url="https://github.com/ToFpon/Sirene/issues")
        about.add_credit_section(tr("Protocole et pilotes"), [
            "OpenFreebuds (melianmiko) https://github.com/melianmiko/OpenFreebuds",
            "FreeBuds 7i (vicrodh) https://github.com/vicrodh/OpenFreebuds"])
        about.add_credit_section(tr("Remerciements"), ["Ponce De Leon https://forum.zorin.com/u/Ponce-De-Leon"])
        about.present()


def main(argv=None) -> int:
    if "--version" in (argv or sys.argv[1:]):
        print(f"{APP_NAME} {VERSION}")
        return 0
    if os.environ.get("SIRENE_DEBUG"):
        logging.basicConfig(level=logging.DEBUG)
    return SireneApp().run(argv if argv is not None else sys.argv)
