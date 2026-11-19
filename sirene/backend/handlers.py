"""Une classe par fonction des écouteurs : ce qu'elle demande au démarrage, ce qu'elle comprend de ce qu'ils
envoient, ce qu'elle écrit quand on change un réglage.

Commandes, types de paramètres et valeurs repris des pilotes d'OpenFreebuds (melianmiko/OpenFreebuds,
GPL-3.0 ; FreeBuds 7i : pull request #135 de vicrodh). Réécrit sans asyncio : `init` et `set` tournent
dans le fil de travail de `Device` (demandes bloquantes), `on_packet` dans le fil de lecture (jamais de
demande bloquante dedans : on attendrait sa propre lecture).

Valeurs rangées par `dev.put(groupe, propriété, valeur)` en types Python (bool, int, str, listes) ; les
choix sont des identifiants (« cancellation », « tap_action_pause »…) que l'interface traduit.
"""

from __future__ import annotations

import json
import struct
import threading

from .protocol import Packet


def _reverse(d: dict) -> dict:
    return {v: k for k, v in d.items()}


class Handler:
    id = ""
    commands: tuple = ()          # trames reçues qui lui reviennent
    ignore: tuple = ()            # trames connues sans intérêt (accusés de réception…)
    writes: tuple = ()            # (groupe, propriété) qu'il sait écrire ; propriété "" = tout le groupe
    attempts = 3                  # essais de `init` (une demande sans réponse = TimeoutError)

    def init(self, dev):
        pass

    def on_packet(self, dev, pkt: Packet):
        pass

    def set(self, dev, group: str, prop: str, value):
        raise NotImplementedError


class Logs(Handler):
    """Journaux matériels envoyés par certains modèles (4i) : ignorés."""
    id = "logs"
    ignore = (b"\x0a\x0d",)


class Info(Handler):
    id = "info"
    commands = (b"\x01\x07",)
    names = {3: "hardware", 7: "software", 9: "serial", 10: "submodel", 15: "model"}

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x01\x07", range(32))))

    def on_packet(self, dev, pkt):
        out = {}
        for kind, raw in pkt.params.items():
            if kind == 24 and raw[:2] == b"L-":          # « L-numéro,R-numéro »
                try:
                    left, right = raw.decode("utf8", "ignore").split(",")
                    out["serial_left"], out["serial_right"] = left[2:], right[2:]
                except ValueError:
                    pass
                continue
            name = self.names.get(kind, f"field_{kind}")
            for enc in ("utf8", "gbk"):
                try:
                    out[name] = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                out[name] = raw.hex()
        dev.update("info", out)


class Battery(Handler):
    id = "battery"
    commands = (b"\x01\x08", b"\x01\x27")      # lecture, annonce spontanée

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x01\x08", [1, 2, 3])))

    def on_packet(self, dev, pkt):
        out = {}
        if pkt.byte(1) is not None:
            out["global"] = pkt.byte(1)
        levels = pkt.get(2)
        if len(levels) == 3:
            out["left"], out["right"], out["case"] = levels[0], levels[1], levels[2]
        charging = pkt.get(3)
        if charging:
            out["charging"] = b"\x01" in charging
            if len(charging) == 3:
                out["charging_left"], out["charging_right"], out["charging_case"] = (c == 1 for c in charging)
        dev.update("battery", out)


CMD_WEAR = b"\x2b\x25"


class InEar(Handler):
    """Port des écouteurs. Ancienne trame 2B03 (p8 / p9 = 1 : portés). 2B25 : un état par écouteur
    (p1 gauche, p2 droit, 01 = porté) — les 7i y répondent ; les 6i l'envoient d'elles-mêmes, mais leur p1
    reste à 01 (gauche jamais signalé, vu chez Tof)."""
    id = "in_ear"

    def __init__(self, wear: bool = False, wear_read: bool = False):
        self.wear, self.wear_read = wear, wear_read
        self.commands = (b"\x2b\x03", CMD_WEAR) if wear else (b"\x2b\x03",)

    def init(self, dev):
        dev.put("state", "in_ear", False)
        if self.wear_read:
            self.on_packet(dev, dev.ask(Packet.read(CMD_WEAR, [1, 2])))

    def on_packet(self, dev, pkt):
        if pkt.cmd == CMD_WEAR:
            left, right = pkt.byte(1), pkt.byte(2)
            if left is not None and right is not None:
                dev.update("state", {"left": left == 1, "right": right == 1, "in_ear": left == 1 and right == 1})
            return
        value = pkt.get(8, 9)
        if len(value) == 1:
            dev.put("state", "in_ear", value[0] == 1)


class Anc(Handler):
    """Contrôle du bruit : mode (désactivé / réduction / transparence) et niveau."""
    id = "anc"
    commands = (b"\x2b\x2a",)
    ignore = (b"\x2b\x04",)
    writes = (("anc", "mode"), ("anc", "level"))

    MODES = {0: "off", 1: "cancellation", 2: "awareness"}

    def __init__(self, levels: bool = False, dynamic: bool = False, voice_boost: bool = False):
        self.levels, self.voice_boost = levels, voice_boost
        self.active = 0
        self.cancel_levels = {1: "comfort", 0: "normal", 2: "ultra"}
        if dynamic:
            self.cancel_levels[3] = "dynamic"
        self.aware_levels = {1: "voice_boost", 2: "normal"}

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\x2a", [1, 2])))

    def on_packet(self, dev, pkt):
        data = pkt.get(1)
        if len(data) != 2:
            return
        level, self.active = data[0], data[1]
        out = {"mode": self.MODES.get(self.active, self.active), "mode_options": list(self.MODES.values()),
               "level": None, "level_options": []}
        if self.active == 1 and self.levels:
            out["level"] = self.cancel_levels.get(level, level)
            out["level_options"] = list(self.cancel_levels.values())
        elif self.active == 2 and self.voice_boost:
            out["level"] = self.aware_levels.get(level, level)
            out["level_options"] = list(self.aware_levels.values())
        dev.update("anc", out)

    def set(self, dev, group, prop, value):
        if prop == "mode":
            # Comme OpenFreebuds (validé sur les vrais écouteurs) : nouveau mode puis FF = « niveau d'avant ».
            data = bytes((_reverse(self.MODES)[value], 0xFF))
        else:
            options = self.aware_levels if self.active == 2 else self.cancel_levels
            data = bytes((self.active, _reverse(options)[value]))
        dev.ask(Packet.write(b"\x2b\x04", [(1, data)]))
        self.init(dev)


class AutoPause(Handler):
    """Réglage « pause au retrait » rangé dans les écouteurs (ce sont eux qui la font sur les 4i)."""
    id = "auto_pause"
    commands = (b"\x2b\x11", b"\x2b\x10")
    writes = (("config", "auto_pause"),)

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\x11", [1])))

    def on_packet(self, dev, pkt):
        if pkt.cmd == b"\x2b\x11" and pkt.byte(1) is not None:
            dev.put("config", "auto_pause", pkt.byte(1) == 1)

    def set(self, dev, group, prop, value):
        resp = dev.ask(Packet.write(b"\x2b\x10", [(1, 1 if value else 0)]))
        if 127 in resp.params:                          # p127 = code de retour : écrit
            dev.put(group, prop, bool(value))


class LowLatency(Handler):
    id = "low_latency"
    commands = (b"\x2b\x6c",)
    writes = (("config", "low_latency"),)

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\x6c", [2])))

    def on_packet(self, dev, pkt):
        value = pkt.get(2)
        if value:
            dev.put("config", "low_latency", value[0] == 1)

    def set(self, dev, group, prop, value):
        dev.ask(Packet.write(b"\x2b\x6c", [(1, 1 if value else 0)]))
        dev.sleep(1)                                    # relu trop tôt, l'ancienne valeur revient
        self.init(dev)


class SoundQuality(Handler):
    """Priorité à la connexion ou à la qualité du son."""
    id = "sound_quality"
    commands = (b"\x2b\xa3",)
    ignore = (b"\x2b\xa2",)
    writes = (("sound", "quality"),)
    OPTIONS = {0: "connectivity", 1: "quality"}

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\xa3", [1])))

    def on_packet(self, dev, pkt):
        value = pkt.byte(2, signed=True)
        if value in self.OPTIONS:
            dev.update("sound", {"quality": self.OPTIONS[value], "quality_options": list(self.OPTIONS.values())})

    def set(self, dev, group, prop, value):
        dev.ask(Packet.write(b"\x2b\xa2", [(1, _reverse(self.OPTIONS)[value])]))
        self.init(dev)


class VoiceLanguage(Handler):
    """Langue des messages vocaux (la langue en cours n'est pas lisible, seulement la liste)."""
    id = "voice_language"
    commands = (b"\x0c\x02",)
    ignore = (b"\x0c\x01",)
    writes = (("service", "language"),)

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x0c\x02", [1, 2])))

    def on_packet(self, dev, pkt):
        raw = pkt.get(3)
        if len(raw) > 1:
            dev.update("service", {"language": "", "language_options": raw.decode("utf8", "ignore").split(",")})

    def set(self, dev, group, prop, value):
        dev.ask(Packet.write(b"\x0c\x01", [(1, value.encode("utf8")), (2, 1)]))
        dev.put(group, prop, value)


TAP_ACTIONS = {-1: "off", 1: "play_pause", 2: "next", 7: "previous", 0: "assistant"}
CALL_ACTIONS = {-1: "off", 0: "answer"}


class _Taps(Handler):
    """Double / triple tape : un geste par écouteur (p1 gauche, p2 droit), p3 = gestes proposés par les
    écouteurs, p4 = pendant un appel."""
    prefix = ""
    cmd_read = cmd_write = b""

    def __init__(self, in_call: bool = False):
        self.in_call = in_call
        self.commands = (self.cmd_read, self.cmd_write)
        self.writes = tuple(("action", f"{self.prefix}_{side}") for side in ("left", "right", "in_call"))
        self.available: list[int] = []

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(self.cmd_read, [1, 2])))

    def on_packet(self, dev, pkt):
        if pkt.cmd != self.cmd_read:
            return
        out = {}
        for kind, side in ((1, "left"), (2, "right")):
            code = pkt.byte(kind, signed=True)
            if code is not None:
                out[f"{self.prefix}_{side}"] = TAP_ACTIONS.get(code, code)
        offered = pkt.get(3)
        if offered:
            self.available = list(struct.unpack(f"{len(offered)}b", offered))
            names = []
            for code in self.available:
                name = TAP_ACTIONS.get(code, str(code))
                if name not in names:
                    names.append(name)
            out[f"{self.prefix}_options"] = names
        call = pkt.byte(4, signed=True)
        if call is not None and self.in_call:
            out[f"{self.prefix}_in_call"] = CALL_ACTIONS.get(call, call)
            out[f"{self.prefix}_in_call_options"] = list(CALL_ACTIONS.values())
        dev.update("action", out)

    def _code(self, table, value) -> int:
        for code in self.available:                     # le code que les écouteurs ont proposé d'abord
            if table.get(code) == value:
                return code
        for code, name in table.items():
            if name == value:
                return code
        return int(value)

    def set(self, dev, group, prop, value):
        side = prop[len(self.prefix) + 1:]
        kind = {"left": 1, "right": 2, "in_call": 4}[side]
        code = self._code(CALL_ACTIONS if side == "in_call" else TAP_ACTIONS, value)
        dev.ask(Packet.write(self.cmd_write, [(kind, code)]))
        dev.put(group, prop, value)


class DoubleTap(_Taps):
    id = "double_tap"
    prefix = "double_tap"
    cmd_read, cmd_write = b"\x01\x20", b"\x01\x1f"


class TripleTap(_Taps):
    id = "triple_tap"
    prefix = "triple_tap"
    cmd_read, cmd_write = b"\x01\x26", b"\x01\x25"


class LongTap(Handler):
    """Appui long : action (rien / changer le contrôle du bruit) et modes parcourus, par écouteur."""
    id = "long_tap"
    READ, READ_ANC, WRITE, WRITE_ANC = b"\x2b\x17", b"\x2b\x19", b"\x2b\x16", b"\x2b\x18"
    commands = (READ, READ_ANC, WRITE, WRITE_ANC)
    writes = tuple(("action", p) for p in ("long_tap_left", "long_tap_right", "long_tap_in_call",
                                           "noise_control_left", "noise_control_right"))
    ANC_CYCLES = {1: "off_on", 2: "off_on_awareness", 3: "on_awareness", 4: "off_awareness"}

    def __init__(self, left=True, right=False, in_call=False, anc=True, extra=False):
        self.left, self.right, self.in_call, self.anc = left, right, in_call, anc
        self.actions = {-1: "off", 10: "switch_anc"}
        if extra:
            self.actions.update({0: "assistant", 18: "volume_up", 19: "volume_down"})

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(self.READ, [1, 2])))
        if self.anc:
            self.on_packet(dev, dev.ask(Packet.read(self.READ_ANC, [1, 2])))

    def on_packet(self, dev, pkt):
        left, right, call = (pkt.byte(k, signed=True) for k in (1, 2, 4))
        out = {}
        if pkt.cmd == self.READ:
            if left is not None and self.left:
                out["long_tap_left"] = self.actions.get(left, left)
            if right is not None and self.right:
                out["long_tap_right"] = self.actions.get(right, right)
            if call is not None and self.in_call:
                out["long_tap_in_call"] = CALL_ACTIONS.get(call, call)
                out["long_tap_in_call_options"] = list(CALL_ACTIONS.values())
            out["long_tap_options"] = list(self.actions.values())
        elif pkt.cmd == self.READ_ANC:
            if left is not None:
                out["noise_control_left"] = self.ANC_CYCLES.get(left, left)
            if right is not None and self.right:
                out["noise_control_right"] = self.ANC_CYCLES.get(right, right)
            out["noise_control_options"] = list(self.ANC_CYCLES.values())
        dev.update("action", out)

    def set(self, dev, group, prop, value):
        side = prop.rsplit("_", 1)[-1] if not prop.endswith("in_call") else "in_call"
        kind = {"left": 1, "right": 2, "in_call": 4}[side]
        if prop.startswith("long_tap"):
            table = CALL_ACTIONS if side == "in_call" else self.actions
            pkt = Packet.write(self.WRITE, [(kind, _reverse(table)[value])])
        else:
            pkt = Packet.write(self.WRITE_ANC, [(kind, _reverse(self.ANC_CYCLES)[value])])
        dev.ask(pkt)
        dev.put(group, prop, value)


class Swipe(Handler):
    """Glisser sur la tige : volume ou rien (même réglage écrit pour les deux écouteurs)."""
    id = "swipe"
    commands = (b"\x2b\x1f", b"\x2b\x1e")
    writes = (("action", "swipe"),)
    OPTIONS = {-1: "off", 0: "volume"}

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\x1f", [1, 2])))

    def on_packet(self, dev, pkt):
        if pkt.cmd != b"\x2b\x1f":
            return
        code = pkt.byte(1, signed=True)
        out = {"swipe_options": list(self.OPTIONS.values())}
        if code is not None:
            out["swipe"] = self.OPTIONS.get(code, code)
        dev.update("action", out)

    def set(self, dev, group, prop, value):
        code = _reverse(self.OPTIONS)[value]
        dev.ask(Packet.write(b"\x2b\x1e", [(1, code), (2, code)]))
        dev.put(group, prop, value)


# --- Égaliseur ---------------------------------------------------------------------------------------

BUILT_IN = {1: "default", 2: "bass", 3: "treble", 9: "voices"}
# Préréglages d'AI Life que les écouteurs n'ont pas en mémoire : envoyés comme des préréglages
# personnalisés, sous leur numéro écrit en décimal (« 200 », « 201 ») comme le fait AI Life.
FAKE_BUILT_IN = [(-56, "symphony", "0f0f0afb0f190ffb322d"), (-55, "hifi_live", "fb141e0a0000e7f60a00")]
FAKE_IDS = {i for i, _, _ in FAKE_BUILT_IN}
LABEL_MAX = 24          # au-delà, les 7i ignorent l'écriture sans répondre


def eq_rows(data) -> list[int]:
    if isinstance(data, str):
        data = bytes.fromhex(data)
    return [b - 256 if b > 127 else b for b in data]


def _label(text: str) -> bytes:
    raw = text.encode("utf8")
    while len(raw) > LABEL_MAX:
        text = text[:-1]
        raw = text.encode("utf8")
    return raw


def eq_payload(mode_id: int, name: str, data, action: int) -> list:
    """action 1 = créer / modifier, 2 = supprimer."""
    if isinstance(data, str):
        data = bytes.fromhex(data)
    label = str(mode_id & 0xFF).encode() if mode_id in FAKE_IDS else _label(name)
    return [(1, mode_id), (2, len(data)), (3, data), (4, label), (5, action)]


class Equalizer(Handler):
    """Préréglages intégrés + préréglages personnalisés (10 bandes, -128..127 par bande, 3 au plus).
    `presets` : liste (id, nom, données hex | None) ; données None = préréglage intégré."""
    id = "equalizer"
    commands = (b"\x2b\x4a",)
    ignore = (b"\x2b\x49",)
    writes = (("sound", "eq_preset"), ("sound", "eq_rows"), ("sound", "eq_saved"))

    def __init__(self, presets: dict | None = None, custom=False, fake_built_in=False, rows=10, max_custom=3):
        self.custom, self.rows, self.max_custom = custom, rows, max_custom
        self.predefined = presets is not None
        self.defaults = [(i, name, None) for i, name in (presets or {}).items()]
        self.overrides = {}
        if fake_built_in:
            self.defaults += [(i, name, None) for i, name, _ in FAKE_BUILT_IN]
            self.overrides = {i: d for i, _, d in FAKE_BUILT_IN}
        elif custom:
            self.defaults += [(None, name, d) for _, name, d in FAKE_BUILT_IN]
        self.presets = list(self.defaults)
        self.saved = True
        self.rollback = b""

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(b"\x2b\x4a", range(1, 9))))

    def on_packet(self, dev, pkt):
        self.presets = []
        if not self.predefined:
            for i in pkt.get(3):
                self.presets.append((i, BUILT_IN.get(i, f"preset_{i}"), None))
        self.presets += self.defaults
        customs = pkt.get(8)
        if self.custom:
            for off in range(0, len(customs) - 1, 36):
                chunk = customs[off:off + 36]
                n = chunk[1]
                self.presets.append((chunk[0], chunk[2 + n:].split(b"\x00", 1)[0].decode("utf8", "ignore"),
                                     chunk[2:2 + n].hex()))
        out = {"eq_rows": None, "eq_saved": self.saved, "eq_options": [p[1] for p in self.presets],
               "eq_max_custom": self.max_custom if self.custom else 0}
        current = pkt.byte(2, signed=True)
        if current is not None:
            out["eq_preset"] = f"unknown_{current}"
            for i, name, data in self.presets:
                if i == current:
                    out["eq_preset"] = name
                    if data is not None:
                        out["eq_rows"] = eq_rows(data)
                    break
        dev.update("sound", out)

    def _current(self, dev):
        name = dev.get("sound", "eq_preset")
        for p in self.presets:
            if p[1] == name:
                return p
        return None, None, None

    def set(self, dev, group, prop, value):
        if prop == "eq_preset":
            return self._select(dev, value)
        mode_id, name, data = self._current(dev)
        if mode_id is None:
            return
        if prop == "eq_rows" and value is None:                       # supprimer le préréglage
            dev.ask(Packet.write(b"\x2b\x49", eq_payload(mode_id, name, data, 2)))
            return self.init(dev)
        if prop == "eq_rows":                                         # bandes modifiées (pas encore gardées)
            new = bytes(v & 0xFF for v in value)
            if self.saved:
                self.rollback = data
            dev.ask(Packet.write(b"\x2b\x49", eq_payload(mode_id, name, new, 1)))
            dev.update("sound", {"eq_rows": list(value), "eq_saved": False})
            self.saved = False
        elif prop == "eq_saved":                                      # garder, ou revenir en arrière
            if not value:
                data = self.rollback
            dev.ask(Packet.write(b"\x2b\x49", eq_payload(mode_id, name, data, 1)))
            dev.update("sound", {"eq_rows": eq_rows(data), "eq_saved": True})
            self.saved = True

    def _select(self, dev, name):
        found = [p for p in self.presets if p[1] == name]
        customs = [i for i, _, d in self.presets if d is not None and i is not None]
        create = False
        if not found:                                                 # nouveau, à partir du préréglage en cours
            data = self._current(dev)[2] or "00" * self.rows
            mode_id, create = 0, True
        elif found[0][0] is None:                                     # modèle à copier en préréglage perso
            mode_id, _, data = found[0]
            create = True
        else:
            mode_id, _, data = found[0]
            data = self.overrides.get(mode_id, data)
        if create:
            if not self.custom:
                raise ValueError("préréglages personnalisés non pris en charge")
            if len(customs) >= self.max_custom:
                raise ValueError("trop de préréglages personnalisés")
            mode_id = 100
            while mode_id in customs:
                mode_id += 1
            self.presets.append((mode_id, name, data))
        if data is not None:
            pkt = Packet.write(b"\x2b\x49", eq_payload(mode_id, name, data, 1))
        else:
            pkt = Packet.write(b"\x2b\x49", [(1, mode_id)])
        self.saved = True
        dev.ask(pkt)
        self.init(dev)


# --- Double connexion --------------------------------------------------------------------------------

DC_ENABLED_READ, DC_ENABLED_WRITE = b"\x2b\x2f", b"\x2b\x2e"
DC_LIST, DC_PREFERRED, DC_EXEC, DC_CHANGED = b"\x2b\x31", b"\x2b\x32", b"\x2b\x33", b"\x2b\x36"
DC_CONNECT, DC_DISCONNECT, DC_UNPAIR, DC_AUTO_ON, DC_AUTO_OFF = 1, 2, 3, 4, 5


class DualConnect(Handler):
    """Double connexion : activée ou non, appareils connus (une trame 2B31 par appareil), appareil préféré.
    Écritures : ("dual_connect", "enabled" | "preferred" | "<mac>:connected" | "<mac>:auto" | "<mac>:unpair")."""
    id = "dual_connect"
    commands = (DC_LIST, DC_CHANGED, DC_ENABLED_READ)
    ignore = (DC_PREFERRED, DC_EXEC, DC_ENABLED_WRITE)
    writes = (("dual_connect", ""),)

    def __init__(self, auto_connect: bool = True):
        self.auto_connect = auto_connect
        self.pending: dict[int, dict] = {}
        self.count = None
        self.listed = threading.Event()

    def init(self, dev):
        self.on_packet(dev, dev.ask(Packet.read(DC_ENABLED_READ, [1])))
        self.pending, self.count = {}, None
        self.listed.clear()
        dev.send(Packet(DC_LIST, [(1, b"")]))
        if not self.listed.wait(2 * dev.timeout):
            if not self.pending:
                raise TimeoutError("liste de la double connexion")
        devices, preferred = {}, ""
        for index in sorted(self.pending):
            d = self.pending[index]
            devices[d["mac"]] = d
            if d["preferred"]:
                preferred = d["mac"]
        dev.update("dual_connect", {"devices": devices, "preferred": preferred})

    def on_packet(self, dev, pkt):
        if pkt.cmd == DC_CHANGED:
            dev.later(self.init)                    # relire, hors du fil de lecture
        elif pkt.cmd == DC_ENABLED_READ:
            if pkt.byte(1) is not None:
                dev.put("dual_connect", "enabled", pkt.byte(1) == 1)
        elif pkt.cmd == DC_LIST:
            mac = pkt.get(4).hex()
            if len(mac) < 12:
                return
            state = pkt.get(5)[:1] or b"\x00"
            self.pending[pkt.byte(3, signed=True) or 0] = {
                "mac": mac,
                "name": pkt.get(9).decode("utf8", "ignore"),
                "preferred": pkt.get(7)[:1] == b"\x01",
                "auto_connect": (pkt.get(8)[:1] == b"\x01") if self.auto_connect else None,
                "connected": state[0] > 0,
                "playing": state[0] == 9,
            }
            self.count = pkt.byte(2, signed=True)
            if self.count is not None and len(self.pending) >= self.count:
                self.listed.set()

    def set(self, dev, group, prop, value):
        mac, _, what = prop.partition(":")
        if prop == "enabled":
            dev.ask(Packet.write(DC_ENABLED_WRITE, [(1, 1 if value else 0)]))
        elif prop == "preferred":
            dev.send(Packet(DC_PREFERRED, [(1, bytes.fromhex(value))]))
        elif what == "connected":
            dev.send(Packet(DC_EXEC, [(DC_CONNECT if value else DC_DISCONNECT, bytes.fromhex(mac))]))
        elif what == "auto":
            dev.send(Packet(DC_EXEC, [(DC_AUTO_ON if value else DC_AUTO_OFF, bytes.fromhex(mac))]))
        elif what == "unpair":
            dev.send(Packet(DC_EXEC, [(DC_UNPAIR, bytes.fromhex(mac))]))
        else:
            raise KeyError(prop)
        dev.later(self.init)


def as_text(value) -> str:
    """Pour le diagnostic (sirene.probe)."""
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
