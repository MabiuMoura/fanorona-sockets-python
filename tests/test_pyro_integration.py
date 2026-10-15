import queue
import threading
import time
import unittest
from unittest.mock import patch

import Pyro5.api
from client.connection import ServerConnection
from server.server import FanoronaServer


class PyroIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FanoronaServer("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 2
        while self.server.port == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertNotEqual(self.server.port, 0)
        self.clients: list[ServerConnection] = []

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.server.stop()
        self.thread.join(2)

    def test_two_proxies_share_state_and_chat(self) -> None:
        first = ServerConnection("127.0.0.1", self.server.port)
        second = ServerConnection("127.0.0.1", self.server.port)
        self.clients = [first, second]
        first.connect(); second.connect()
        first.move([2, 3], [2, 4], "approach")
        deadline = time.monotonic() + 2
        state = None
        while time.monotonic() < deadline:
            try: event = second.events.get(timeout=.1)
            except queue.Empty: continue
            if event["type"] in {"START", "STATE"} and event["board"][2][4] == 1:
                state = event; break
        self.assertIsNotNone(state)
        first.send_chat("Olá")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try: event = second.events.get(timeout=.1)
            except queue.Empty: continue
            if event["type"] == "CHAT": break
        self.assertEqual(event["message"], "Olá")

    def test_give_up_synchronizes_terminal_state_to_both_clients(self) -> None:
        first = ServerConnection("127.0.0.1", self.server.port)
        second = ServerConnection("127.0.0.1", self.server.port)
        self.clients = [first, second]
        first.connect(); second.connect()
        first.give_up()
        terminal_states = []
        for client in (first, second):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try: event = client.events.get(timeout=.1)
                except queue.Empty: continue
                if event["type"] in {"START", "STATE"} and event.get("game_over"):
                    terminal_states.append(event)
                    break
        self.assertEqual(len(terminal_states), 2)
        self.assertTrue(all(state["game_over"] for state in terminal_states))
        self.assertTrue(all(state["winner"] == 2 for state in terminal_states))
        self.assertTrue(all(state["end_reason"] == "give_up" for state in terminal_states))

    def test_proxy_cannot_impersonate_other_player_with_numeric_id(self) -> None:
        first = ServerConnection("127.0.0.1", self.server.port)
        second = ServerConnection("127.0.0.1", self.server.port)
        self.clients = [first, second]
        first.connect(); second.connect()
        proxy = Pyro5.api.Proxy(f"PYRO:fanorona@127.0.0.1:{self.server.port}")
        try:
            # "2" era suficiente para agir como P2 na interface anterior.
            # Agora não é um token de sessão e todas as operações são recusadas.
            self.assertEqual(proxy.mover("2", [2, 3], [2, 4], "approach")["code"], "INVALID_SESSION")
            self.assertEqual(proxy.enviar_mensagem("2", "falsa")["code"], "INVALID_SESSION")
            self.assertEqual(proxy.desistir("2")["code"], "INVALID_SESSION")
            self.assertEqual(proxy.desconectar("2")["code"], "INVALID_SESSION")
            self.assertFalse(self.server.session.game_over)
            self.assertEqual(self.server.session.players, {1: "", 2: ""})
        finally:
            proxy._pyroRelease()


class StateRevisionTests(unittest.TestCase):
    def test_stale_state_does_not_replace_newer_state(self) -> None:
        connection = ServerConnection("127.0.0.1", 1)
        newer = {"revision": 7, "game_started": True, "board": [[1]]}
        older = {"revision": 6, "game_started": True, "board": [[0]]}
        connection._emit_state(newer)
        connection._emit_state(older)
        event = connection.events.get_nowait()
        self.assertEqual(event["revision"], 7)
        self.assertTrue(connection.events.empty())


class GiveUpFailureTests(unittest.TestCase):
    def test_rpc_failure_is_reported_to_the_gui_queue(self) -> None:
        connection = ServerConnection("127.0.0.1", 1)
        connection.player_id = 1
        connection.session_token = "token-de-teste"
        with patch.object(connection, "_proxy", side_effect=OSError("offline")):
            connection.give_up()
            event = connection.events.get(timeout=1)
        self.assertEqual(event["type"], "CONNECTION_ERROR")
        self.assertIn("offline", event["message"])


if __name__ == "__main__":
    unittest.main()
