"""Faux écouteurs : l'autre bout d'un socketpair, qui répond aux demandes d'après un modèle
{trame demandée (octets): [réponses (octets)…]} — comme le banc d'essai d'OpenFreebuds — et peut envoyer
des trames spontanées (retrait d'un écouteur…)."""

import socket
import threading
import time

from sirene.backend.protocol import FrameReader, Packet


class FakeBuds:
    def __init__(self, model: dict | None = None):
        self.model = dict(model or {})
        self.sent: list[bytes] = []                 # ce que Sirène a envoyé
        self.ours, self.theirs = socket.socketpair()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def connect(self, address, channel):
        """À passer à Device(connect=…)."""
        self.channel = channel
        return self.theirs

    def answer(self, request: Packet | bytes, *responses):
        key = request.to_bytes() if isinstance(request, Packet) else request
        self.model[key] = [r.to_bytes() if isinstance(r, Packet) else r for r in responses]

    def push(self, pkt: Packet | bytes):
        self.ours.sendall(pkt.to_bytes() if isinstance(pkt, Packet) else pkt)

    def close(self):
        try:
            self.ours.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.ours.close()
        self.theirs.close()             # déjà fermé par Device.stop, en général

    def _loop(self):
        reader = FrameReader()
        while True:
            try:
                data = self.ours.recv(4096)
            except OSError:
                return
            if not data:
                return
            for pkt in reader.feed(data):
                raw = pkt.to_bytes()
                self.sent.append(raw)
                for resp in self.model.get(raw, []):
                    self.ours.sendall(resp)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False
