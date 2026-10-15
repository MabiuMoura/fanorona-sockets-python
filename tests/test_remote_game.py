import unittest

from server.server import FanoronaRemoteGame


class RemoteGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = FanoronaRemoteGame()
        self.first = self.game.registrar_jogador("Ana")
        self.second = self.game.registrar_jogador("Bia")
        self.first_token = self.first["token"]
        self.second_token = self.second["token"]

    def test_register_starts_and_exposes_shared_state(self) -> None:
        self.assertTrue(self.first["ok"])
        self.assertEqual(self.first["player"], 1)
        self.assertTrue(self.second["started"])
        self.assertTrue(self.game.obter_estado()["game_started"])

    def test_move_turn_and_invalid_move_are_authoritative(self) -> None:
        moved = self.game.mover(self.first_token, [2, 3], [2, 4], "approach")
        self.assertTrue(moved["ok"])
        self.assertEqual(moved["state"]["current_player"], 2)
        rejected = self.game.mover(self.first_token, [2, 4], [2, 3])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["code"], "NOT_YOUR_TURN")

    def test_chat_is_polled_and_give_up_declares_winner(self) -> None:
        self.assertTrue(self.game.enviar_mensagem(self.first_token, "Olá")["ok"])
        messages = self.game.obter_mensagens()
        self.assertEqual(messages[0]["player"], 1)
        self.assertEqual(messages[0]["message"], "Olá")
        result = self.game.desistir(self.first_token)
        self.assertTrue(result["ok"])
        self.assertTrue(result["state"]["game_over"])
        self.assertEqual(result["state"]["winner"], 2)

    def test_game_full_and_invalid_chat_are_explicit_results(self) -> None:
        self.assertEqual(self.game.registrar_jogador("C")["code"], "GAME_FULL")
        self.assertEqual(self.game.enviar_mensagem(self.first_token, " ")["code"], "INVALID_CHAT")


if __name__ == "__main__":
    unittest.main()
