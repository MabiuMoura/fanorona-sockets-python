import unittest

from game.board import (
    APPROACH,
    WITHDRAWAL,
    Board,
    EMPTY,
    PLAYER_1,
    PLAYER_2,
    InvalidMove,
)


class BoardTests(unittest.TestCase):
    def test_initial_board_dimensions_and_piece_counts(self) -> None:
        board = Board()
        serialized = board.serialize()
        pieces = [piece for row in serialized for piece in row]

        self.assertEqual(len(serialized), 5)
        self.assertTrue(all(len(row) == 9 for row in serialized))
        self.assertEqual(pieces.count(PLAYER_1), 22)
        self.assertEqual(pieces.count(PLAYER_2), 22)
        self.assertEqual(pieces.count(EMPTY), 1)
        self.assertEqual(board.get_piece(2, 4), EMPTY)

    def test_horizontal_vertical_and_diagonal_connections(self) -> None:
        board = Board()
        self.assertIn((2, 4), board.neighbors(2, 3))
        self.assertIn((2, 4), board.neighbors(1, 4))
        self.assertIn((1, 1), board.neighbors(0, 0))
        self.assertNotIn((1, 2), board.neighbors(0, 1))

    def test_move_without_capture(self) -> None:
        board = Board.empty()
        board.set_piece(2, 3, PLAYER_1)

        result = board.apply_move(PLAYER_1, (2, 3), (2, 4))

        self.assertFalse(result.is_capture)
        self.assertEqual(board.get_piece(2, 3), EMPTY)
        self.assertEqual(board.get_piece(2, 4), PLAYER_1)

    def test_approach_capture(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 4, PLAYER_2)

        self.assertEqual(
            board.get_approach_captures(PLAYER_1, (2, 2), (2, 3)), [(2, 4)]
        )
        result = board.apply_move(PLAYER_1, (2, 2), (2, 3))
        self.assertEqual(result.capture_mode, APPROACH)
        self.assertEqual(result.captured, ((2, 4),))
        self.assertEqual(board.get_piece(2, 4), EMPTY)

    def test_withdrawal_capture(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 1, PLAYER_2)

        self.assertEqual(
            board.get_withdrawal_captures(PLAYER_1, (2, 2), (2, 3)), [(2, 1)]
        )
        result = board.apply_move(PLAYER_1, (2, 2), (2, 3))
        self.assertEqual(result.capture_mode, WITHDRAWAL)
        self.assertEqual(board.get_piece(2, 1), EMPTY)

    def test_captures_multiple_contiguous_pieces(self) -> None:
        board = Board.empty()
        board.set_piece(2, 1, PLAYER_1)
        for column in (3, 4, 5):
            board.set_piece(2, column, PLAYER_2)

        result = board.apply_move(PLAYER_1, (2, 1), (2, 2))

        self.assertEqual(result.captured, ((2, 3), (2, 4), (2, 5)))
        self.assertTrue(all(board.is_empty(2, column) for column in (3, 4, 5)))

    def test_requires_choice_when_both_capture_modes_exist(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 1, PLAYER_2)
        board.set_piece(2, 4, PLAYER_2)
        before = board.serialize()

        with self.assertRaises(InvalidMove) as raised:
            board.apply_move(PLAYER_1, (2, 2), (2, 3))

        self.assertEqual(raised.exception.code, "CAPTURE_CHOICE_REQUIRED")
        self.assertEqual(board.serialize(), before)

    def test_applies_explicit_choice_when_both_modes_exist(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 1, PLAYER_2)
        board.set_piece(2, 4, PLAYER_2)

        result = board.apply_move(PLAYER_1, (2, 2), (2, 3), APPROACH)

        self.assertEqual(result.captured, ((2, 4),))
        self.assertEqual(board.get_piece(2, 1), PLAYER_2)

    def test_rejects_capture_mode_that_is_not_available(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 1, PLAYER_2)
        before = board.serialize()

        with self.assertRaises(InvalidMove) as raised:
            board.apply_move(PLAYER_1, (2, 2), (2, 3), APPROACH)

        self.assertEqual(raised.exception.code, "INVALID_CAPTURE")
        self.assertEqual(board.serialize(), before)

    def test_rejects_non_textual_capture_choice(self) -> None:
        board = Board.empty()
        board.set_piece(2, 2, PLAYER_1)
        board.set_piece(2, 4, PLAYER_2)

        with self.assertRaises(InvalidMove) as raised:
            board.apply_move(PLAYER_1, (2, 2), (2, 3), [])

        self.assertEqual(raised.exception.code, "INVALID_CAPTURE")

    def test_invalid_move_does_not_change_board(self) -> None:
        board = Board()
        before = board.serialize()
        with self.assertRaises(InvalidMove):
            board.apply_move(PLAYER_1, (2, 2), (2, 4))
        self.assertEqual(board.serialize(), before)


if __name__ == "__main__":
    unittest.main()
