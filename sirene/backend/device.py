"""Connexion à une paire d'écouteurs : canal RFCOMM, fil de lecture, fil de travail, valeurs connues.

Sans GTK. Les changements de valeur sont annoncés par `on_change(groupe, propriété, valeur)` depuis un des
deux fils : l'interface les renvoie dans la boucle GLib (idle_add).

Fils :
  - lecture : découpe les trames ; une réponse attendue réveille la demande, le reste va à la fonction
    concernée (`on_packet`, jamais bloquant) ;
  - travail : démarrage des fonctions (`init`), réglages (`set`), relectures (`later`) — une demande
    bloquante à la fois (verrou), les écouteurs ne traitent qu'une demande à la fois.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
from typing import Callable, Optional

from .protocol import FrameReader, Packet

log = logging.getLogger("sirene.device")

TIMEOUT = 3


def rfcomm_connect(address: str, channel: int, timeout: float = 5) -> socket.socket:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(timeout)
    try:
        sock.connect((address, channel))
    except OSError:
        sock.close()
        raise
    sock.settimeout(None)
    return sock


class Device:
    def __init__(self, model, address: str, on_change: Optional[Callable] = None,
                 connect: Callable = rfcomm_connect, timeout: float = TIMEOUT):
        self.model = model
        self.timeout = timeout
        self.address = address
        self.on_change = on_change
        self._connect = connect
        self.handlers = model.make()
        self.store: dict[str, dict] = {}
        self.unknown: dict[bytes, Packet] = {}          # trames que personne ne comprend (diagnostic)
        self.failed: list[str] = []                     # fonctions qui n'ont jamais répondu
        self._sock = None
        self._ask_lock = threading.Lock()
        self._waiting: dict[bytes, list] = {}           # commande → [Event, Packet]
        self._routes: dict[bytes, object] = {}
        self._writers: dict[tuple, object] = {}
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self.ready = threading.Event()                  # toutes les fonctions démarrées (ou abandonnées)
        for handler in self.handlers:
            for cmd in handler.commands:
                self._routes[cmd] = handler
            for cmd in handler.ignore:
                self._routes.setdefault(cmd, None)
            for key in handler.writes:
                self._writers[key] = handler

    # --- cycle de vie ---

    def start(self):
        """Ouvre le canal (lève OSError si les écouteurs refusent), puis démarre les fonctions en fond."""
        self._sock = self._connect(self.address, self.model.channel)
        threading.Thread(target=self._read_loop, name="sirene-lecture", daemon=True).start()
        threading.Thread(target=self._work_loop, name="sirene-travail", daemon=True).start()
        self._jobs.put(self._init_all)

    def stop(self):
        self._stop.set()
        self._jobs.put(None)
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        for event, _ in list(self._waiting.values()):
            event.set()

    @property
    def alive(self) -> bool:
        return self._sock is not None and not self._stop.is_set()

    def _init_all(self):
        for handler in self.handlers:
            for attempt in range(handler.attempts):
                if self._stop.is_set():
                    return
                try:
                    handler.init(self)
                    break
                except (TimeoutError, ConnectionError):
                    log.debug("%s : pas de réponse (essai %d)", handler.id, attempt + 1)
                except Exception:
                    log.exception("%s : démarrage", handler.id)
                    break
            else:
                self.failed.append(handler.id)
        self.ready.set()
        self._emit("device", "ready", True)

    # --- échanges ---

    def send(self, pkt: Packet):
        sock = self._sock
        if sock is None:
            raise ConnectionError("écouteurs déconnectés")
        log.debug("TX %s", pkt)
        sock.sendall(pkt.to_bytes())

    def request(self, pkt: Packet, timeout: Optional[float] = None) -> Optional[Packet]:
        """Envoie et attend la réponse (`pkt.reply`) ; None si rien n'arrive à temps."""
        if not pkt.reply:
            self.send(pkt)
            return None
        with self._ask_lock:
            slot = [threading.Event(), None]
            self._waiting[pkt.reply] = slot
            try:
                self.send(pkt)
                slot[0].wait(self.timeout if timeout is None else timeout)
            finally:
                self._waiting.pop(pkt.reply, None)
            return slot[1]

    def ask(self, pkt: Packet, timeout: Optional[float] = None) -> Packet:
        """Comme `request`, mais sans réponse → TimeoutError (les fonctions réessaient)."""
        resp = self.request(pkt, timeout)
        if resp is None:
            raise ConnectionError("déconnecté") if not self.alive else TimeoutError(pkt.cmd.hex())
        return resp

    def sleep(self, seconds: float):
        self._stop.wait(seconds)

    def later(self, fn: Callable):
        """`fn()` dans le fil de travail (relecture demandée depuis le fil de lecture…)."""
        self._jobs.put(fn)

    def _read_loop(self):
        reader = FrameReader()
        while not self._stop.is_set():
            sock = self._sock
            try:
                data = sock.recv(4096) if sock else b""
            except OSError:
                data = b""
            if not data:
                break
            for pkt in reader.feed(data):
                log.debug("RX %s", pkt)
                self._dispatch(pkt)
        if not self._stop.is_set():
            self.stop()
            self._emit("device", "connected", False)

    def _dispatch(self, pkt: Packet):
        slot = self._waiting.get(pkt.cmd)
        if slot is not None and not slot[0].is_set():
            slot[1] = pkt
            slot[0].set()
            return
        if pkt.cmd in self._routes:
            handler = self._routes[pkt.cmd]
            if handler is not None:
                try:
                    handler.on_packet(self, pkt)
                except Exception:
                    log.exception("%s : trame %s", handler.id, pkt)
        else:
            self.unknown[pkt.cmd] = pkt

    def _work_loop(self):
        while True:
            job = self._jobs.get()
            if job is None or self._stop.is_set():
                return
            try:
                job()
            except (TimeoutError, ConnectionError) as e:
                log.info("travail abandonné : %s", e)
            except Exception:
                log.exception("travail")

    # --- valeurs ---

    def get(self, group: str, prop: str, default=None):
        return self.store.get(group, {}).get(prop, default)

    def put(self, group: str, prop: str, value):
        if self.store.setdefault(group, {}).get(prop, object()) == value:
            return
        self.store[group][prop] = value
        self._emit(group, prop, value)

    def update(self, group: str, values: dict):
        for prop, value in values.items():
            self.put(group, prop, value)

    def set(self, group: str, prop: str, value, done: Optional[Callable] = None):
        """Change un réglage des écouteurs, dans le fil de travail. `done(erreur ou None)` à la fin."""
        handler = self._writers.get((group, prop)) or self._writers.get((group, ""))
        if handler is None:
            raise KeyError(f"{group}.{prop}")

        def job():
            error = None
            try:
                handler.set(self, group, prop, value)
            except Exception as e:                      # noqa: BLE001 — rendu à l'interface
                error = e
            if done:
                done(error)
        self.later(job)

    def can_set(self, group: str, prop: str) -> bool:
        return (group, prop) in self._writers or (group, "") in self._writers

    def _emit(self, group, prop, value):
        if self.on_change:
            try:
                self.on_change(group, prop, value)
            except Exception:
                log.exception("on_change")
