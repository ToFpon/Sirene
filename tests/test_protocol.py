"""Trames : construction, lecture, CRC, découpage du flux.

    python3.12 -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sirene.backend.protocol import FrameReader, Packet, crc16_xmodem  # noqa: E402

# Trames réelles des FreeBuds 7i (tests de la pull request #135 d'OpenFreebuds, capturées depuis AI Life)
ANC_DYNAMIC = bytes.fromhex("5a0007002b2a010203015043")
ANC_SET_ULTRA = bytes.fromhex("5a0007002b0401020102c15e")
WEAR_BOTH = bytes.fromhex("5a000f002b25010101020101030100040100e11b")


class PacketTest(unittest.TestCase):
    def test_crc_of_real_frames(self):
        for frame in (ANC_DYNAMIC, ANC_SET_ULTRA, WEAR_BOTH):
            self.assertEqual(crc16_xmodem(frame[:-2]), frame[-2:], frame.hex())

    def test_parse_and_rebuild(self):
        pkt = Packet.from_bytes(WEAR_BOTH)
        self.assertEqual(pkt.cmd, b"\x2b\x25")
        self.assertEqual((pkt.byte(1), pkt.byte(2), pkt.byte(3), pkt.byte(4)), (1, 1, 0, 0))
        self.assertEqual(pkt.to_bytes(), WEAR_BOTH)

    def test_text_like_mybuds_log(self):
        """Même écriture que le journal de MyBuds : les captures des 6i de Tof se comparent telles quelles."""
        pkt = Packet(b"\x2b\x25", [(1, 1), (2, 0), (3, 0), (4, 0)])
        self.assertEqual(str(pkt), "cmd=2B25 p1=01 p2=00 p3=00 p4=00")

    def test_read_request(self):
        pkt = Packet.read(b"\x2b\x2a", [1, 2])
        self.assertEqual(pkt.reply, b"\x2b\x2a")
        self.assertEqual(pkt.to_bytes().hex(), "5a0007002b2a01000200" + crc16_xmodem(
            bytes.fromhex("5a0007002b2a01000200")).hex())

    def test_signed_int_param(self):
        self.assertEqual(Packet(b"\x01\x1f", [(1, -1)]).params[1], b"\xff")

    def test_bad_crc_refused(self):
        bad = WEAR_BOTH[:-1] + bytes((WEAR_BOTH[-1] ^ 1,))
        with self.assertRaises(ValueError):
            Packet.from_bytes(bad)


class ReaderTest(unittest.TestCase):
    def test_split_and_glued_frames(self):
        r = FrameReader()
        stream = ANC_DYNAMIC + WEAR_BOTH
        got = []
        for i in range(0, len(stream), 3):              # par morceaux de 3 octets
            got += r.feed(stream[i:i + 3])
        self.assertEqual([p.cmd for p in got], [b"\x2b\x2a", b"\x2b\x25"])

    def test_resync_after_garbage_and_bad_frame(self):
        r = FrameReader()
        bad = WEAR_BOTH[:-1] + b"\x00"
        got = r.feed(b"\x00\x13\x5a" + bad + ANC_DYNAMIC)
        self.assertEqual([p.cmd for p in got], [b"\x2b\x2a"], "trame fausse et octets perdus sautés")
        self.assertGreaterEqual(r.bad, 1)


if __name__ == "__main__":
    unittest.main()
