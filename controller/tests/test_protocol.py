import unittest

from codex_micro.protocol import FrameDecoder, encode_frame


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        decoder = FrameDecoder()
        frames = decoder.feed(encode_frame(0x20, bytes((2, 4))))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, 0x20)
        self.assertEqual(frames[0].payload, bytes((2, 4)))

    def test_fragmented_frame(self):
        decoder = FrameDecoder()
        data = encode_frame(0x10, bytes((1, 3)))
        self.assertEqual(decoder.feed(data[:3]), [])
        self.assertEqual(decoder.feed(data[3:])[0].payload, bytes((1, 3)))

    def test_bad_crc_is_dropped(self):
        decoder = FrameDecoder()
        data = bytearray(encode_frame(0x20, bytes((0, 1))))
        data[-1] ^= 0xFF
        self.assertEqual(decoder.feed(bytes(data)), [])


if __name__ == "__main__":
    unittest.main()
