import unittest

from common.protocol import MessageBuffer, ProtocolError, encode_message


class MessageBufferTests(unittest.TestCase):
    def test_reassembles_fragmented_message(self) -> None:
        parser = MessageBuffer()
        payload = encode_message({"type": "CHAT", "text": "olá"})

        self.assertEqual(parser.feed(payload[:5]), [])
        self.assertEqual(
            parser.feed(payload[5:]), [{"type": "CHAT", "text": "olá"}]
        )

    def test_separates_coalesced_messages(self) -> None:
        parser = MessageBuffer()
        payload = encode_message({"type": "ONE"}) + encode_message({"type": "TWO"})

        self.assertEqual(parser.feed(payload), [{"type": "ONE"}, {"type": "TWO"}])

    def test_rejects_invalid_json(self) -> None:
        items = MessageBuffer().feed(b"not-json\n")

        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], ProtocolError)

    def test_keeps_valid_messages_around_invalid_line(self) -> None:
        parser = MessageBuffer()
        payload = (
            encode_message({"type": "HELLO"})
            + b"JSON_INVALIDO\n"
            + encode_message({"type": "HELLO"})
        )

        items = parser.feed(payload)

        self.assertEqual(items[0], {"type": "HELLO"})
        self.assertIsInstance(items[1], ProtocolError)
        self.assertEqual(items[2], {"type": "HELLO"})


if __name__ == "__main__":
    unittest.main()
