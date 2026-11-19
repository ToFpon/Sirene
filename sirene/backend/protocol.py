"""Trames du protocole Huawei sur le canal série (SPP / RFCOMM) des écouteurs.

Format repris d'OpenFreebuds (melianmiko/OpenFreebuds, GPL-3.0) :

    5A | longueur (2 octets, gros-boutiste) | 00 | commande (2 octets) | paramètres… | CRC-16 XMODEM (2 octets)

La longueur compte l'octet 00, la commande et les paramètres. Chaque paramètre = type (1 octet),
taille (1 octet), valeur. Le CRC porte sur tout ce qui précède (5A compris).
Une demande de lecture envoie les types voulus avec une valeur vide ; les écouteurs répondent par la
même commande, valeurs remplies.
"""

from __future__ import annotations

MARK = 0x5A


def crc16_xmodem(data: bytes) -> bytes:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc.to_bytes(2, "big")


def _value(v) -> bytes:
    if isinstance(v, int):
        return v.to_bytes(1, "big", signed=True)        # -1 = « désactivé » dans les gestes
    return bytes(v)


class Packet:
    """Une trame. `reply` : commande de la réponse attendue (b"" = rien à attendre)."""

    def __init__(self, cmd: bytes, params=None, reply: bytes = b""):
        if len(cmd) != 2:
            raise ValueError("commande sur 2 octets")
        self.cmd = bytes(cmd)
        self.reply = reply
        self.params: dict[int, bytes] = {}
        for kind, value in (params.items() if isinstance(params, dict) else params or ()):
            self.params[kind] = _value(value)

    @classmethod
    def read(cls, cmd: bytes, kinds) -> "Packet":
        """Demande de lecture : types demandés, valeurs vides ; réponse = même commande."""
        return cls(cmd, [(k, b"") for k in kinds], reply=cmd)

    @classmethod
    def write(cls, cmd: bytes, params, wait: bool = True) -> "Packet":
        return cls(cmd, params, reply=cmd if wait else b"")

    def get(self, *kinds) -> bytes:
        """Valeur du premier de ces types présent (b"" sinon)."""
        for k in kinds:
            if k in self.params:
                return self.params[k]
        return b""

    def byte(self, kind: int, signed: bool = False):
        """Valeur d'un paramètre d'un seul octet, ou None."""
        v = self.params.get(kind, b"")
        return int.from_bytes(v, "big", signed=signed) if len(v) == 1 else None

    def to_bytes(self) -> bytes:
        body = self.cmd
        for kind, value in self.params.items():
            body += bytes((kind, len(value))) + value
        head = bytes((MARK,)) + (len(body) + 1).to_bytes(2, "big") + b"\x00" + body
        return head + crc16_xmodem(head)

    @classmethod
    def from_bytes(cls, data: bytes, check: bool = True) -> "Packet":
        if len(data) < 8 or data[0] != MARK or data[3] != 0:
            raise ValueError("pas une trame")
        length = int.from_bytes(data[1:3], "big")
        if len(data) != length + 5:
            raise ValueError("longueur incohérente")
        if check and crc16_xmodem(data[:-2]) != data[-2:]:
            raise ValueError("CRC faux")
        pkt = cls(data[4:6])
        pos, end = 6, length + 3
        while pos + 1 < end:
            kind, size = data[pos], data[pos + 1]
            pkt.params[kind] = data[pos + 2:pos + 2 + size]
            pos += 2 + size
        return pkt

    def __str__(self):
        """Même écriture que le journal de MyBuds : « cmd=2B25 p1=01 p2=00 »."""
        out = "cmd=" + self.cmd.hex().upper()
        for kind, value in self.params.items():
            out += f" p{kind}={value.hex()}"
        return out

    __repr__ = __str__


class FrameReader:
    """Découpe le flux reçu en trames ; se recale sur le prochain 5A après un octet perdu ou une trame fausse."""

    MAX_FRAME = 4096

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0                    # trames jetées (CRC faux…), pour le diagnostic

    def feed(self, data: bytes) -> list[Packet]:
        self.buf += data
        out = []
        while True:
            start = self.buf.find(MARK)
            if start < 0:
                self.buf.clear()
                return out
            del self.buf[:start]
            if len(self.buf) < 3:
                return out
            length = int.from_bytes(self.buf[1:3], "big")
            if length < 3 or length > self.MAX_FRAME:
                del self.buf[:1]
                continue
            total = length + 5
            if len(self.buf) < total:
                return out
            frame = bytes(self.buf[:total])
            try:
                out.append(Packet.from_bytes(frame))
                del self.buf[:total]
            except ValueError:
                self.bad += 1
                del self.buf[:1]        # faux départ : on cherche le 5A suivant
