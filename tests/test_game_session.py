import unittest

from game.board import Board, PLAYER_1, PLAYER_2
from server.game_session import GameSession, SessionError


def started_session(board: Board | None = None) -> GameSession:
    session = GameSession()
    session.add_player(object())
    session.add_player(object())
    if board is not None:
        session.board = board
    assert session.try_start()
    return session


def sequence_board() -> Board:
    board = Board.empty()
    board.set_piece(2, 0, PLAYER_1)
    board.set_piece(4, 0, PLAYER_1)
    board.set_piece(2, 2, PLAYER_2)
    board.set_piece(0, 1, PLAYER_2)
    board.set_piece(4, 8, PLAYER_2)
    return board


class GameSessionTests(unittest.TestCase):
    def test_try_start_checks_and_changes_state_atomically(self) -> None:
        session = GameSession()
        session.add_player(object())
        self.assertFalse(session.try_start())
        self.assertFalse(session.game_started)

        session.add_player(object())
        self.assertTrue(session.try_start())
        self.assertTrue(session.game_started)
        self.assertEqual(session.current_player, 1)
        self.assertFalse(session.try_start())

    def test_capture_sequence_keeps_turn_and_then_changes_it(self) -> None:
        session = started_session(sequence_board())

        first_state, first_result = session.try_move(1, (2, 0), (2, 1))
        self.assertTrue(first_result.is_capture)
        self.assertTrue(first_state["capture_sequence"])
        self.assertEqual(first_state["active_piece"], [2, 1])
        self.assertEqual(first_state["current_player"], 1)

        second_state, second_result = session.try_move(1, (2, 1), (1, 1))
        self.assertTrue(second_result.is_capture)
        self.assertFalse(second_state["capture_sequence"])
        self.assertIsNone(second_state["active_piece"])
        self.assertEqual(second_state["current_player"], 2)

    def test_cannot_use_another_piece_during_sequence(self) -> None:
        session = started_session(sequence_board())
        session.try_move(1, (2, 0), (2, 1))
        before = session.state()["board"]

        with self.assertRaises(SessionError) as raised:
            session.try_move(1, (4, 0), (3, 0))

        self.assertEqual(raised.exception.code, "SEQUENCE_PIECE_REQUIRED")
        self.assertEqual(session.state()["board"], before)

    def test_cannot_revisit_position_during_sequence(self) -> None:
        session = started_session(sequence_board())
        session.try_move(1, (2, 0), (2, 1))
        before = session.state()["board"]

        with self.assertRaises(SessionError) as raised:
            session.try_move(1, (2, 1), (2, 0))

        self.assertEqual(raised.exception.code, "POSITION_ALREADY_VISITED")
        self.assertEqual(session.state()["board"], before)

    def test_sequence_requires_another_capture(self) -> None:
        session = started_session(sequence_board())
        session.try_move(1, (2, 0), (2, 1))

        with self.assertRaises(SessionError) as raised:
            session.try_move(1, (2, 1), (3, 1))

        self.assertEqual(raised.exception.code, "CAPTURE_REQUIRED")

    def test_capture_of_last_piece_declares_winner(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 4, PLAYER_2)
        session = started_session(board)

        state, _ = session.try_move(1, (2, 2), (2, 3))

        self.assertTrue(state["game_over"])
        self.assertEqual(state["winner"], 1)
        self.assertEqual(session.end_reason, "no_pieces")
        with self.assertRaises(SessionError) as raised:
            session.try_move(1, (2, 3), (2, 4))
        self.assertEqual(raised.exception.code, "GAME_ALREADY_OVER")

    def test_player_can_give_up_outside_their_turn(self) -> None:
        session = started_session()

        state = session.give_up(2)

        self.assertTrue(state["game_over"])
        self.assertEqual(state["winner"], 1)
        self.assertEqual(session.end_reason, "give_up")

    def test_disconnect_before_start_does_not_finish_session(self) -> None:
        session = GameSession()
        session.add_player(object())

        self.assertIsNone(session.disconnect(1))
        self.assertFalse(session.game_over)

    def test_disconnect_during_match_declares_other_player_winner(self) -> None:
        session = started_session()

        state = session.disconnect(1)

        self.assertIsNotNone(state)
        self.assertTrue(state["game_over"])
        self.assertEqual(state["winner"], 2)
        self.assertEqual(session.end_reason, "disconnect")


if __name__ == "__main__":
    unittest.main()
