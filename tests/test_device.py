"""Connexion et fonctions contre de faux écouteurs (socketpair) qui rejouent de vraies trames :
7i (tests de la pull request #135 d'OpenFreebuds, capturées depuis AI Life) et 6i (captures de Tof).

    python3.12 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_buds import FakeBuds, wait_for  # noqa: E402
from sirene.backend import handlers as h  # noqa: E402
from sirene.backend import models  # noqa: E402
from sirene.backend.device import Device  # noqa: E402
from sirene.backend.models import Model  # noqa: E402
from sirene.backend.protocol import Packet  # noqa: E402

GET_ANC = Packet.read(b"\x2b\x2a", [1, 2])
GET_WEAR = Packet.read(b"\x2b\x25", [1, 2])


def start(handlers, fake, channel=1):
    changes = []
    dev = Device(Model("essai", channel, lambda: handlers), "00:11:22:33:44:55",
                 on_change=lambda g, p, v: changes.append((g, p, v)), connect=fake.connect, timeout=0.3)
    dev.start()
    assert wait_for(dev.ready.is_set), "démarrage"
    return dev, changes


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBuds()

    def tearDown(self):
        self.fake.close()

    def test_anc_levels_7i(self):
        self.fake.answer(GET_ANC, bytes.fromhex("5a0007002b2a010203015043"))           # réduction, dynamique
        dev, _ = start([h.Anc(levels=True, dynamic=True, voice_boost=True)], self.fake)
        self.assertEqual(dev.get("anc", "mode"), "cancellation")
        self.assertEqual(dev.get("anc", "level"), "dynamic")
        self.assertEqual(dev.get("anc", "level_options"), ["comfort", "normal", "ultra", "dynamic"])

        set_ultra = bytes.fromhex("5a0007002b0401020102c15e")
        self.fake.answer(set_ultra, bytes.fromhex("5a0006002b040201003171"))
        self.fake.answer(GET_ANC, bytes.fromhex("5a0007002b2a010202016372"))           # ultra
        errors = []
        dev.set("anc", "level", "ultra", done=errors.append)
        self.assertTrue(wait_for(lambda: errors))
        self.assertEqual(errors, [None])
        self.assertIn(set_ultra, self.fake.sent, "même trame qu'AI Life")
        self.assertEqual(dev.get("anc", "level"), "ultra")
        dev.stop()

    def test_voice_boost_7i(self):
        self.fake.answer(GET_ANC, bytes.fromhex("5a0007002b2a010202025311"))           # transparence normale
        dev, _ = start([h.Anc(levels=True, dynamic=True, voice_boost=True)], self.fake)
        self.assertEqual((dev.get("anc", "mode"), dev.get("anc", "level")), ("awareness", "normal"))
        set_boost = bytes.fromhex("5a0007002b0401020201a46e")
        self.fake.answer(set_boost, bytes.fromhex("5a0006002b040201003171"))
        self.fake.answer(GET_ANC, bytes.fromhex("5a0007002b2a010201020642"))
        done = []
        dev.set("anc", "level", "voice_boost", done=done.append)
        self.assertTrue(wait_for(lambda: done))
        self.assertIn(set_boost, self.fake.sent)
        self.assertEqual(dev.get("anc", "level"), "voice_boost")
        dev.stop()

    def test_wear_per_bud_7i(self):
        """7i : état lu au démarrage, puis chaque retrait annoncé (p1 gauche, p2 droit)."""
        self.fake.answer(GET_WEAR, bytes.fromhex("5a000f002b25010101020101030100040100e11b"))
        dev, changes = start([h.InEar(wear=True, wear_read=True)], self.fake)
        self.assertTrue(dev.get("state", "in_ear"))
        self.fake.push(Packet(b"\x2b\x25", [(1, 0), (2, 1), (3, 0), (4, 0)]))          # gauche retiré
        self.assertTrue(wait_for(lambda: dev.get("state", "in_ear") is False))
        self.assertEqual((dev.get("state", "left"), dev.get("state", "right")), (False, True))
        self.assertIn(("state", "in_ear", False), changes)
        dev.stop()

    def test_wear_6i_right_only(self):
        """6i (captures de Tof) : rien n'est lu au démarrage ; le droit change p2, p1 reste à 01."""
        dev, _ = start([h.InEar(wear=True)], self.fake)
        self.assertFalse(any(raw[4:6] == b"\x2b\x25" for raw in self.fake.sent), "pas de lecture sur les 6i")
        for p2, worn in ((1, True), (0, False), (1, True)):
            self.fake.push(Packet(b"\x2b\x25", [(1, 1), (2, p2), (3, 0), (4, 0)]))
            self.assertTrue(wait_for(lambda: dev.get("state", "in_ear") is worn))
        dev.stop()

    def test_battery_6i_capture(self):
        """« cmd=0108 p1=64 p2=646454 p3=000000 … » : gauche et droit 100 %, boîtier 84 %."""
        self.fake.answer(Packet.read(b"\x01\x08", [1, 2, 3]), Packet(b"\x01\x08", [
            (1, b"\x64"), (2, bytes.fromhex("646454")), (3, b"\x00\x00\x00"), (4, bytes.fromhex("140a")),
            (5, b"\x00\x00"), (6, b"\x0a")]))
        dev, _ = start([h.Battery()], self.fake)
        self.assertEqual({k: dev.get("battery", k) for k in ("left", "right", "case", "charging")},
                         {"left": 100, "right": 100, "case": 84, "charging": False})
        self.fake.push(Packet(b"\x01\x27", [(2, bytes((90, 100, 84))), (3, b"\x00\x00\x01")]))   # annonce
        self.assertTrue(wait_for(lambda: dev.get("battery", "left") == 90))
        self.assertTrue(dev.get("battery", "charging_case"))
        dev.stop()

    def test_auto_pause_setting(self):
        self.fake.answer(Packet.read(b"\x2b\x11", [1]), Packet(b"\x2b\x11", [(1, 1)]))
        dev, _ = start([h.AutoPause()], self.fake)
        self.assertIs(dev.get("config", "auto_pause"), True)
        self.fake.answer(Packet.write(b"\x2b\x10", [(1, 0)]), Packet(b"\x2b\x10", [(127, b"\x00\x01\x86\xa0")]))
        done = []
        dev.set("config", "auto_pause", False, done=done.append)
        self.assertTrue(wait_for(lambda: done))
        self.assertIs(dev.get("config", "auto_pause"), False)
        dev.stop()

    def test_equalizer_builtin_and_fake_7i(self):
        get_eq = Packet.read(b"\x2b\x4a", range(1, 9))
        current = lambda i: Packet(b"\x2b\x4a", [(1, b"\x01"), (2, bytes((i,))), (3, bytes.fromhex("01020309")),  # noqa: E731
                                                 (4, b"\x01"), (8, b"")])
        self.fake.answer(get_eq, current(0xC9))                                         # Hi-Fi Live
        eq = h.Equalizer(presets=h.BUILT_IN, fake_built_in=True, custom=True)
        dev, _ = start([eq], self.fake)
        self.assertEqual(dev.get("sound", "eq_preset"), "hifi_live")
        self.assertIn("bass", dev.get("sound", "eq_options"))

        ok = bytes.fromhex("5a0009002b497f04000186a0b3c6")
        set_bass = Packet(b"\x2b\x49", [(1, 2)])
        self.fake.answer(set_bass, ok)
        self.fake.answer(get_eq, current(2))
        done = []
        dev.set("sound", "eq_preset", "bass", done=done.append)
        self.assertTrue(wait_for(lambda: done))
        self.assertEqual(dev.get("sound", "eq_preset"), "bass")

        # Symphonie : préréglage d'AI Life envoyé sous son numéro en décimal (« 200 ») — sinon ignoré
        set_symphony = Packet(b"\x2b\x49", [(1, b"\xc8"), (2, 10), (3, bytes.fromhex("0f0f0afb0f190ffb322d")),
                                            (4, b"200"), (5, 1)])
        self.fake.answer(set_symphony, ok)
        self.fake.answer(get_eq, current(0xC8))
        done.clear()
        dev.set("sound", "eq_preset", "symphony", done=done.append)
        self.assertTrue(wait_for(lambda: done))
        self.assertIn(set_symphony.to_bytes(), self.fake.sent)
        self.assertEqual(dev.get("sound", "eq_preset"), "symphony")
        dev.stop()

    def test_label_truncated_to_24_bytes(self):
        label = h.eq_payload(101, "é" * 20, "00" * 10, 1)[3][1]
        self.assertLessEqual(len(label), h.LABEL_MAX)
        self.assertEqual(label.decode(), "é" * 12)

    def test_taps(self):
        self.fake.answer(Packet.read(b"\x01\x20", [1, 2]), Packet(b"\x01\x20", [
            (1, 1), (2, -1), (3, bytes((0xff, 1, 2, 7, 0))), (4, 0)]))
        dev, _ = start([h.DoubleTap(in_call=True)], self.fake)
        self.assertEqual((dev.get("action", "double_tap_left"), dev.get("action", "double_tap_right")),
                         ("play_pause", "off"))
        self.assertEqual(dev.get("action", "double_tap_options"), ["off", "play_pause", "next", "previous", "assistant"])
        self.assertEqual(dev.get("action", "double_tap_in_call"), "answer")
        write = Packet.write(b"\x01\x1f", [(2, 2)])
        self.fake.answer(write, Packet(b"\x01\x1f", [(127, b"\x00\x01\x86\xa0")]))
        done = []
        dev.set("action", "double_tap_right", "next", done=done.append)
        self.assertTrue(wait_for(lambda: done))
        self.assertIn(write.to_bytes(), self.fake.sent)
        dev.stop()

    def test_dual_connect_list_and_change_event(self):
        """Liste des appareils (une trame 2B31 chacun), puis 2B36 « changé » → relue dans le fil de travail
        (vu chez Tof : la relecture plantait, DualConnect.init appelé sans l'appareil)."""
        self.fake.answer(Packet.read(b"\x2b\x2f", [1]), Packet(b"\x2b\x2f", [(1, 1)]))

        def row(index, mac, name, state, preferred):
            return Packet(b"\x2b\x31", [(2, 2), (3, index), (4, bytes.fromhex(mac)), (5, state),
                                        (7, preferred), (9, name.encode())])
        listing = [row(0, "2b3c1292a0a8", "zorin-tof", 9, 1), row(1, "aabbccddeeff", "Téléphone", 0, 0)]
        self.fake.answer(Packet(b"\x2b\x31", [(1, b"")]), *listing)
        dev, _ = start([h.DualConnect(auto_connect=False)], self.fake)
        self.assertIs(dev.get("dual_connect", "enabled"), True)
        devices = dev.get("dual_connect", "devices")
        self.assertEqual(devices["2b3c1292a0a8"]["name"], "zorin-tof")
        self.assertTrue(devices["2b3c1292a0a8"]["playing"])
        self.assertFalse(devices["aabbccddeeff"]["connected"])
        self.assertEqual(dev.get("dual_connect", "preferred"), "2b3c1292a0a8")

        listing[1] = row(1, "aabbccddeeff", "Téléphone", 1, 0)                         # le téléphone arrive
        self.fake.answer(Packet(b"\x2b\x31", [(1, b"")]), *listing)
        self.fake.push(Packet(b"\x2b\x36", [(1, 1)]))
        self.assertTrue(wait_for(lambda: dev.get("dual_connect", "devices")["aabbccddeeff"]["connected"]))
        dev.stop()

    def test_info_6i_capture(self):
        """Trame 0107 des 6i de Tof (capture MyBuds) : textes lisibles, binaire en hexadécimal."""
        raw = {2: "0153", 3: "484c324f52434d4c",
               7: "4861726d6f6e794f5320362e302e302e32393228463030314830303343393029",
               9: "324e4754513234423036303035373834", 10: "42544654303031392d303030313533",
               15: "4254465430303139",
               24: "4c2d545134383730323442323030393839342c522d54513438373332344232303034333235",
               25: "02", 27: "b5dc03f78a30"}
        self.fake.answer(Packet.read(b"\x01\x07", range(32)),
                         Packet(b"\x01\x07", [(k, bytes.fromhex(v)) for k, v in raw.items()]))
        dev, _ = start([h.Info()], self.fake)
        info = dev.store["info"]
        self.assertEqual(info["software"], "HarmonyOS 6.0.0.292(F001H003C90)")
        self.assertEqual((info["model"], info["hardware"]), ("BTFT0019", "HL2ORCML"))
        self.assertEqual((info["serial_left"], info["serial_right"]), ("TQ487024B2009894", "TQ487324B2004325"))
        self.assertEqual((info["field_25"], info["field_27"]), ("02", "b5dc03f78a30"))
        dev.stop()

    def test_optional_wear_read_6i(self):
        """6i : lecture du port tentée une fois ; sans réponse, rien d'échoué et pas de nouvel essai."""
        dev, _ = start([h.InEar(wear=True, wear_read=True, optional=True)], self.fake)
        self.assertEqual(dev.failed, [])
        self.assertEqual(sum(raw[4:6] == b"\x2b\x25" for raw in self.fake.sent), 1)
        self.fake.answer(GET_WEAR, Packet(b"\x2b\x25", [(1, 1), (2, 1), (3, 0), (4, 0)]))
        dev.stop()
        self.fake = FakeBuds({GET_WEAR.to_bytes(): [Packet(b"\x2b\x25", [(1, 1), (2, 1)]).to_bytes()]})
        dev, _ = start([h.InEar(wear=True, wear_read=True, optional=True)], self.fake)
        self.assertIs(dev.get("state", "in_ear"), True, "s'ils répondent, l'état est juste dès le départ")
        dev.stop()

    def test_silent_handler_does_not_block_others(self):
        """Une fonction sans réponse est notée, les suivantes démarrent quand même."""
        self.fake.answer(GET_ANC, bytes.fromhex("5a0007002b2a010203015043"))
        dev, _ = start([h.LowLatency(), h.Anc(levels=True)], self.fake)
        self.assertEqual(dev.failed, ["low_latency"])
        self.assertEqual(dev.get("anc", "mode"), "cancellation")
        dev.stop()

    def test_disconnect_reported(self):
        dev, changes = start([], self.fake)
        self.fake.close()
        self.assertTrue(wait_for(lambda: ("device", "connected", False) in changes))
        self.assertFalse(dev.alive)

    def test_unknown_frames_kept_for_diagnosis(self):
        dev, _ = start([], self.fake)
        self.fake.push(Packet(b"\x2b\xbb", [(1, 5)]))
        self.assertTrue(wait_for(lambda: b"\x2b\xbb" in dev.unknown))
        dev.stop()


class ModelsTest(unittest.TestCase):
    def test_known_models(self):
        self.assertEqual(models.find("HUAWEI FreeBuds 6i").channel, 1)
        self.assertEqual(models.find(" HUAWEI FreeBuds 7i ").channel, 1)
        self.assertEqual(models.find("HONOR Earbuds 2").name, "HUAWEI FreeBuds 4i")
        self.assertIsNone(models.find("Souris"))

    def test_each_model_builds_and_routes(self):
        for model in models.MODELS.values():
            dev = Device(model, "00:00:00:00:00:00")
            ids = [x.id for x in dev.handlers]
            self.assertEqual(len(ids), len(set(ids)), model.name)
            self.assertTrue(dev.can_set("anc", "mode"), model.name)


if __name__ == "__main__":
    unittest.main()
