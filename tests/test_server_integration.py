import queue
import threading
import time
import unittest

from client.connection import ServerConnection
from common.protocol import (
    ASSIGN_PLAYER,
    CHAT,
    CONNECTED,
    ERROR,
    GAME_OVER,
    GIVEUP,
    MOVE,
    START,
    STATE,
)
from server.server import FanoronaServer


class ServerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FanoronaServer("127.0.0.1", 0)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        deadline = time.monotonic() + 2
        while self.server.port == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertNotEqual(self.server.port, 0)
        self.clients: list[ServerConnection] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.server.stop()
        self.server_thread.join(timeout=2)

    @staticmethod
    def wait_for_type(
        client: ServerConnection, expected_type: str, timeout: float = 2
    ) -> dict:
        received = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = client.events.get(timeout=0.1)
            except queue.Empty:
                continue
            received.append(message)
            if message["type"] == expected_type:
                return message
        raise AssertionError(f"{expected_type} não recebido; mensagens: {received}")

    def connect_two(self) -> tuple[ServerConnection, ServerConnection, dict, dict]:
        first = ServerConnection("127.0.0.1", self.server.port)
        second = ServerConnection("127.0.0.1", self.server.port)
        self.clients.extend([first, second])
        first.connect()
        second.connect()

        first_connected = self.wait_for_type(first, CONNECTED)
        first_assignment = self.wait_for_type(first, ASSIGN_PLAYER)
        first_start = self.wait_for_type(first, START)
        second_connected = self.wait_for_type(second, CONNECTED)
        second_assignment = self.wait_for_type(second, ASSIGN_PLAYER)
        second_start = self.wait_for_type(second, START)

        self.assertEqual(first_connected["type"], CONNECTED)
        self.assertEqual(second_connected["type"], CONNECTED)
        self.assertEqual(first_assignment["player"], 1)
        self.assertEqual(second_assignment["player"], 2)
        return first, second, first_start, second_start

    def test_assigns_players_and_starts_with_identical_state(self) -> None:
        _, _, first_start, second_start = self.connect_two()

        self.assertEqual(first_start, second_start)
        self.assertEqual(first_start["current_player"], 1)
        self.assertEqual(len(first_start["board"]), 5)

    def test_rejects_third_client_with_game_full_and_closes_connection(self) -> None:
        self.connect_two()
        third = ServerConnection("127.0.0.1", self.server.port)
        self.clients.append(third)

        third.connect()
        error = self.wait_for_type(third, ERROR)
        closed = self.wait_for_type(third, "CONNECTION_CLOSED")

        self.assertEqual(error["code"], "GAME_FULL")
        self.assertEqual(closed["type"], "CONNECTION_CLOSED")

    def test_chat_from_each_player_is_broadcast_with_server_identity(self) -> None:
        first, second, _, _ = self.connect_two()

        first.send({"type": CHAT, "player": 2, "message": "Olá"})
        first_chat = self.wait_for_type(first, CHAT)
        second_chat = self.wait_for_type(second, CHAT)
        self.assertEqual(first_chat, second_chat)
        self.assertEqual(first_chat, {"type": CHAT, "player": 1, "message": "Olá"})

        second.send({"type": CHAT, "player": 1, "message": "Boa jogada"})
        first_chat = self.wait_for_type(first, CHAT)
        second_chat = self.wait_for_type(second, CHAT)
        self.assertEqual(first_chat, second_chat)
        self.assertEqual(
            first_chat, {"type": CHAT, "player": 2, "message": "Boa jogada"}
        )

    def test_invalid_chat_is_rejected_only_for_sender(self) -> None:
        first, _, _, _ = self.connect_two()

        for invalid_message in ("   ", 123, "x" * 501):
            first.send({"type": CHAT, "message": invalid_message})
            error = self.wait_for_type(first, ERROR)
            self.assertEqual(error["code"], "INVALID_CHAT")

    def test_capture_broadcasts_identical_authoritative_state(self) -> None:
        first, second, _, _ = self.connect_two()

        first.send(
            {
                "type": MOVE,
                "from": [2, 3],
                "to": [2, 4],
                "capture": "approach",
            }
        )
        first_state = self.wait_for_type(first, STATE)
        second_state = self.wait_for_type(second, STATE)

        self.assertEqual(first_state, second_state)
        self.assertEqual(first_state["current_player"], 2)
        self.assertEqual(first_state["board"][2][3], 0)
        self.assertEqual(first_state["board"][2][4], 1)
        self.assertEqual(first_state["board"][2][5], 0)

    def test_out_of_turn_move_is_rejected_without_changing_board(self) -> None:
        first, second, _, _ = self.connect_two()
        first.send(
            {
                "type": MOVE,
                "from": [2, 3],
                "to": [2, 4],
                "capture": "approach",
            }
        )
        accepted = self.wait_for_type(first, STATE)
        self.wait_for_type(second, STATE)

        first.send({"type": MOVE, "from": [2, 4], "to": [2, 3]})
        error = self.wait_for_type(first, ERROR)

        self.assertEqual(error["code"], "NOT_YOUR_TURN")
        self.assertEqual(self.server.session.state()["board"], accepted["board"])

    def test_moving_opponents_piece_is_rejected_without_changing_board(self) -> None:
        first, second, _, _ = self.connect_two()
        first.send(
            {
                "type": MOVE,
                "from": [2, 3],
                "to": [2, 4],
                "capture": "approach",
            }
        )
        accepted = self.wait_for_type(first, STATE)
        self.wait_for_type(second, STATE)

        second.send({"type": MOVE, "from": [2, 4], "to": [2, 3]})
        error = self.wait_for_type(second, ERROR)

        self.assertEqual(error["code"], "INVALID_MOVE")
        self.assertEqual(self.server.session.state()["board"], accepted["board"])

    def test_missing_choice_for_double_capture_is_rejected(self) -> None:
        first, _, _, _ = self.connect_two()
        before = self.server.session.state()["board"]

        first.send({"type": MOVE, "from": [2, 3], "to": [2, 4]})
        error = self.wait_for_type(first, ERROR)

        self.assertEqual(error["code"], "CAPTURE_CHOICE_REQUIRED")
        self.assertEqual(self.server.session.state()["board"], before)

    def test_give_up_broadcasts_state_and_game_over(self) -> None:
        first, second, _, _ = self.connect_two()

        first.send({"type": GIVEUP, "player": 1})
        first_state = self.wait_for_type(first, STATE)
        second_state = self.wait_for_type(second, STATE)
        first_game_over = self.wait_for_type(first, GAME_OVER)
        second_game_over = self.wait_for_type(second, GAME_OVER)

        self.assertEqual(first_state, second_state)
        self.assertTrue(first_state["game_over"])
        self.assertEqual(first_game_over, second_game_over)
        self.assertEqual(first_game_over["winner"], 2)
        self.assertEqual(first_game_over["reason"], "give_up")

    def test_disconnect_during_match_declares_remaining_player_winner(self) -> None:
        first, second, _, _ = self.connect_two()

        first.close()
        state = self.wait_for_type(second, STATE)
        game_over = self.wait_for_type(second, GAME_OVER)

        self.assertTrue(state["game_over"])
        self.assertEqual(game_over["winner"], 2)
        self.assertEqual(game_over["reason"], "disconnect")


if __name__ == "__main__":
    unittest.main()
