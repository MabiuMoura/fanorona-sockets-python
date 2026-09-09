"""Servidor TCP da partida de Fanorona."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from typing import Any

from common.protocol import (
    ASSIGN_PLAYER,
    CHAT,
    CONNECTED,
    DISCONNECT,
    ERROR,
    GAME_OVER,
    GIVEUP,
    HELLO,
    MOVE,
    START,
    STATE,
)
from server.client_handler import ClientHandler
from server.game_session import GameSession, SessionError


LOGGER = logging.getLogger("fanorona.server")


class FanoronaServer:
    """Aceita dois jogadores e coordena a sessão autoritativa."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000) -> None:
        self.host = host
        self.port = port
        self.session = GameSession()
        self._socket: socket.socket | None = None
        self._stopping = threading.Event()
        self._action_lock = threading.Lock()

    def serve_forever(self) -> None:
        # ============================================================
        # CRIAÇÃO DO SOCKET SERVIDOR
        # AF_INET = endereços IPv4. SOCK_STREAM = transporte TCP.
        # bind() associa o processo ao host/porta; listen() habilita a espera;
        # accept() aguarda um jogador e devolve um NOVO socket exclusivo para
        # conversar com ele. O socket original continua aceitando conexões.
        # ============================================================
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(GameSession.MAX_PLAYERS)
        server_socket.settimeout(0.2)
        self._socket = server_socket
        self.port = server_socket.getsockname()[1]
        LOGGER.info("[SERVER] Listening on %s:%s", self.host, self.port)

        try:
            while not self._stopping.is_set():
                try:
                    connection, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stopping.is_set():
                        break
                    raise
                self._register_client(connection, address)
        finally:
            self._close_all()

    def _register_client(
        self, connection: socket.socket, address: tuple[str, int]
    ) -> None:
        # ClientHandler herda de Thread. O start() abaixo chama seu run(), de
        # modo que cada socket possa ficar bloqueado em recv() independentemente.
        handler = ClientHandler(
            connection, address, self._handle_message, self._handle_disconnect
        )
        try:
            player_id = self.session.add_player(handler)
        except RuntimeError:
            LOGGER.info("[SERVER] Connection from %s:%s rejected: game full", *address)
            try:
                handler.send(
                    {
                        "type": ERROR,
                        "code": "GAME_FULL",
                        "message": "A partida já possui dois jogadores",
                    }
                )
            except OSError:
                pass
            handler.close()
            return
        handler.player_id = player_id
        LOGGER.info("[SERVER] Player %s connected from %s:%s", player_id, *address)
        try:
            handler.send({"type": CONNECTED})
            handler.send({"type": ASSIGN_PLAYER, "player": player_id})
        except OSError:
            handler.close()
            self.session.remove_player(player_id)
            return
        handler.start()

        if self.session.try_start():
            LOGGER.info("[GAME] Match started; turn -> Player 1")
            self.broadcast({"type": START, **self.session.state()})

    def _handle_message(
        self, handler: ClientHandler, message: dict[str, Any]
    ) -> None:
        # ============================================================
        # DISTRIBUIÇÃO DAS MENSAGENS RECEBIDAS
        # cliente -> ClientHandler.run() -> _handle_message()
        # MOVE   -> _handle_move()    -> GameSession.try_move()
        # CHAT   -> _handle_chat()    -> broadcast()
        # GIVEUP -> _handle_give_up() -> GameSession.give_up()
        # ============================================================
        if message["type"] == HELLO:
            LOGGER.info("[SERVER] Player %s identified", handler.player_id)
            return
        if message["type"] == CHAT:
            self._handle_chat(handler, message)
            return
        if message["type"] == MOVE:
            self._handle_move(handler, message)
            return
        if message["type"] == GIVEUP:
            self._handle_give_up(handler)
            return
        self._send_error(
            handler,
            "UNSUPPORTED_MESSAGE",
            "Mensagem ainda não disponível nesta etapa",
        )

    def _handle_chat(
        self, handler: ClientHandler, message: dict[str, Any]
    ) -> None:
        if not self.session.has_player(handler.player_id):
            self._send_error(handler, "INVALID_CHAT", "Jogador não conectado")
            return
        text = message.get("message")
        if not isinstance(text, str):
            self._send_error(handler, "INVALID_CHAT", "A mensagem deve ser texto")
            return
        text = text.strip()
        if not text:
            self._send_error(handler, "INVALID_CHAT", "A mensagem não pode ser vazia")
            return
        if len(text) > 500:
            self._send_error(
                handler, "INVALID_CHAT", "A mensagem deve ter no máximo 500 caracteres"
            )
            return
        LOGGER.info("[CHAT] Player %s: %s", handler.player_id, text)
        self.broadcast({"type": CHAT, "player": handler.player_id, "message": text})

    def _handle_move(
        self, handler: ClientHandler, message: dict[str, Any]
    ) -> None:
        if handler.player_id is None or not self.session.has_player(handler.player_id):
            self._send_error(handler, "INVALID_MOVE", "Jogador não conectado")
            return
        try:
            # O lock abrange a alteração e o broadcast correspondente. Isso
            # preserva a ordem dos STATEs mesmo com dois ClientHandlers ativos.
            with self._action_lock:
                state, result = self.session.try_move(
                    handler.player_id,
                    message.get("from"),
                    message.get("to"),
                    message.get("capture"),
                )
                LOGGER.info(
                    "[GAME] Player %s -> MOVE %s -> %s; captured=%s",
                    handler.player_id,
                    message.get("from"),
                    message.get("to"),
                    list(result.captured),
                )
                self.broadcast({"type": STATE, **state})
                if state["game_over"]:
                    self.broadcast(
                        {
                            "type": GAME_OVER,
                            "winner": state["winner"],
                            "reason": "no_pieces",
                        }
                    )
        except SessionError as exc:
            self._send_error(handler, exc.code, str(exc))

    def _handle_give_up(self, handler: ClientHandler) -> None:
        if handler.player_id is None or not self.session.has_player(handler.player_id):
            self._send_error(handler, "INVALID_GIVEUP", "Jogador não conectado")
            return
        try:
            with self._action_lock:
                state = self.session.give_up(handler.player_id)
                LOGGER.info("[GAME] Player %s gave up", handler.player_id)
                self.broadcast({"type": STATE, **state})
                self.broadcast(
                    {
                        "type": GAME_OVER,
                        "winner": state["winner"],
                        "reason": "give_up",
                    }
                )
        except SessionError as exc:
            self._send_error(handler, exc.code, str(exc))

    @staticmethod
    def _send_error(handler: ClientHandler, code: str, message: str) -> None:
        try:
            handler.send(
                {
                    "type": ERROR,
                    "code": code,
                    "message": message,
                }
            )
        except OSError:
            handler.close()

    def _handle_disconnect(self, handler: ClientHandler) -> None:
        player_id = handler.player_id
        if player_id is None:
            return
        with self._action_lock:
            with self.session.lock:
                if self.session.players.get(player_id) is not handler:
                    return
            state = self.session.disconnect(player_id)
            LOGGER.info("[SERVER] Player %s disconnected", player_id)
            recipients = self.session.handlers()
            if state is None:
                for recipient in recipients:
                    try:
                        recipient.send({"type": DISCONNECT, "player": player_id})
                    except OSError:
                        recipient.close()
                return
            self.broadcast({"type": STATE, **state})
            self.broadcast(
                {
                    "type": GAME_OVER,
                    "winner": state["winner"],
                    "reason": "disconnect",
                }
            )

    def broadcast(self, message: dict[str, Any]) -> None:
        # Caminho servidor -> os dois clientes. Cada handler envia a mesma
        # mensagem pelo socket que pertence ao respectivo jogador.
        for handler in self.session.handlers():
            try:
                handler.send(message)
            except OSError:
                handler.close()

    def stop(self) -> None:
        self._stopping.set()
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()

    def _close_all(self) -> None:
        for handler in self.session.handlers():
            handler.close()
        if self._socket is not None:
            self._socket.close()


def main() -> None:
    # ============================================================
    # MAIN DO SERVIDOR
    # python -m server.server
    #        -> main()
    #        -> FanoronaServer(...)
    #        -> serve_forever()
    # ============================================================
    parser = argparse.ArgumentParser(description="Servidor TCP do Fanorona")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = FanoronaServer(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("[SERVER] Encerrando")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
