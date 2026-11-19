"""Faux écouteurs : l'autre bout d'un socketpair, qui répond aux demandes d'après un modèle
{trame demandée (octets): [réponses (octets)…]} — comme le banc d'essai d'OpenFreebuds — et peut envoyer
des trames spontanées (retrait d'un écouteur…)."""

import socket
import threading
import time

from sirene.backend.protocol import FrameReader, Packet

ADDR = "CC:B0:A8:AB:43:43"


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


def buds_6i() -> FakeBuds:
    """Réponses des 6i de Tof (sortie de sirene.probe)."""
    f = FakeBuds()
    f.answer(Packet.read(b"\x01\x07", range(32)), Packet(b"\x01\x07", [
        (7, b"HarmonyOS 6.0.0.292(F001H003C90ALL)"), (15, b"BTFT0019"), (9, b"2NGTQ24B06005784")]))
    f.answer(Packet.read(b"\x01\x08", [1, 2, 3]), Packet(b"\x01\x08", [
        (1, 100), (2, bytes((100, 100, 67))), (3, b"\x00\x00\x00")]))
    f.answer(Packet.read(b"\x2b\x2a", [1, 2]), Packet(b"\x2b\x2a", [(1, b"\x00\x00")]))
    f.answer(Packet.read(b"\x01\x20", [1, 2]), Packet(b"\x01\x20", [
        (1, 1), (2, 1), (3, bytes((1, 7, 2, 0, 0xff))), (4, 0)]))
    f.answer(Packet.read(b"\x01\x26", [1, 2]), Packet(b"\x01\x26", [
        (1, 2), (2, 2), (3, bytes((2, 4, 5, 6, 7, 0xff)))]))
    f.answer(Packet.read(b"\x2b\x17", [1, 2]), Packet(b"\x2b\x17", [(1, -1), (2, -1)]))
    f.answer(Packet.read(b"\x2b\x19", [1, 2]), Packet(b"\x2b\x19", [(1, 2), (2, 2)]))
    f.answer(Packet.read(b"\x2b\x1f", [1, 2]), Packet(b"\x2b\x1f", [(1, 0), (2, 0)]))
    f.answer(Packet.read(b"\x2b\x11", [1]), Packet(b"\x2b\x11", [(1, 1)]))
    f.answer(Packet.read(b"\x2b\xa3", [1]), Packet(b"\x2b\xa3", [(2, 0)]))
    f.answer(Packet.read(b"\x2b\x6c", [2]), Packet(b"\x2b\x6c", [(2, 0)]))
    f.answer(Packet.read(b"\x2b\x4a", range(1, 9)), Packet(b"\x2b\x4a", [
        (1, b"\x01"), (2, b"\x01"), (3, bytes.fromhex("01020309")), (4, b"\x01"), (8, b"")]))
    f.answer(Packet.read(b"\x0c\x02", [1, 2]), Packet(b"\x0c\x02", [(3, b"zh-CN,en-GB")]))
    f.answer(Packet.read(b"\x2b\x2f", [1]), Packet(b"\x2b\x2f", [(1, 0)]))
    f.answer(Packet(b"\x2b\x31", [(1, b"")]), Packet(b"\x2b\x31", [
        (2, 1), (3, 0), (4, bytes.fromhex("2b3c1292a0a8")), (5, 1), (7, 0), (9, b"zorin-tof")]))
    f.answer(Packet.read(b"\x2b\x25", [1, 2]), Packet(b"\x2b\x25", [(1, 1), (2, 1), (3, 0), (4, 0)]))
    return f


class FakeWatcher:
    def __init__(self, on_change):
        self.on_change = on_change
        self.devices = {}

    def stop(self):
        pass

    def announce(self, connected, name="HUAWEI FreeBuds 6i"):
        from sirene.backend.bluez import BtDevice
        d = BtDevice(ADDR, name, connected, "/org/bluez/hci0/dev_" + ADDR.replace(":", "_"), "audio-headphones")
        self.devices[d.path] = d
        self.on_change(d)


