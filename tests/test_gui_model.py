import unittest

from client.gui_model import BoardGeometry, ClientGameState
from game.board import Board


class BoardGeometryTests(unittest.TestCase):
    def test_board_canvas_round_trip_for_every_position(self) -> None:
        geometry = BoardGeometry()
        for row in range(Board.ROWS):
            for column in range(Board.COLUMNS):
                x, y = geometry.board_to_canvas(row, column)
                self.assertEqual(geometry.canvas_to_board(x, y), (row, column))

    def test_canvas_click_far_from_point_is_ignored(self) -> None:
        geometry = BoardGeometry(click_radius=10)
        x, y = geometry.board_to_canvas(2, 4)

        self.assertIsNone(geometry.canvas_to_board(x + 20, y + 20))


class ClientGameStateTests(unittest.TestCase):
    def test_board_stays_empty_until_authoritative_start_arrives(self) -> None:
        model = ClientGameState()

        self.assertTrue(all(piece == 0 for row in model.board for piece in row))

    def test_state_is_copied_and_applied_centrally(self) -> None:
        model = ClientGameState(player_id=1)
        board = Board().serialize()
        message = {
            "board": board,
            "current_player": 1,
            "game_over": False,
            "winner": None,
            "capture_sequence": False,
            "active_piece": None,
        }

        model.apply_server_state(message, marks_start=True)
        board[0][0] = 0

        self.assertTrue(model.started)
        self.assertEqual(model.board[0][0], 2)
        self.assertTrue(model.can_select((2, 3)))

    def test_capture_sequence_allows_only_active_piece(self) -> None:
        model = ClientGameState(player_id=1)
        board = Board().serialize()
        model.apply_server_state(
            {
                "board": board,
                "current_player": 1,
                "game_over": False,
                "winner": None,
                "capture_sequence": True,
                "active_piece": [2, 3],
            },
            marks_start=True,
        )

        self.assertTrue(model.can_select((2, 3)))
        self.assertFalse(model.can_select((2, 1)))

    def test_out_of_turn_piece_cannot_be_selected(self) -> None:
        model = ClientGameState(player_id=1, started=True, current_player=2)

        self.assertFalse(model.can_select((2, 3)))


if __name__ == "__main__":
    unittest.main()
