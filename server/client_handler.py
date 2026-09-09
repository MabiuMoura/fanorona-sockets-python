"""Atendimento concorrente de uma conexão cliente."""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any, Callable

from common.protocol import ERROR, MessageBuffer, ProtocolError, send_message


LOGGER = logging.getLogger("fanorona.server")


class ClientHandler(threading.Thread):
    """Lê mensagens de um cliente sem bloquear as demais conexões."""

    # Cada jogador recebe uma instância/thread:
    # ClientHandler Player 1 -> Thread
    # ClientHandler Player 2 -> Thread
    # Como recv() é bloqueante, isso permite aguardar os dois sockets ao mesmo
    # tempo sem uma conexão impedir o atendimento da outra.

    def __init__(
        self,
        connection: socket.socket,
        address: tuple[str, int],
        on_message: Callable[["ClientHandler", dict[str, Any]], None],
        on_disconnect: Callable[["ClientHandler"], None],
    ) -> None:
        super().__init__(daemon=True, name=f"client-{address[0]}:{address[1]}")
        self.connection = connection
        self.address = address
        self.player_id: int | None = None
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._send_lock = threading.Lock()
        self._closed = threading.Event()

    def send(self, message: dict[str, Any]) -> None:
        # Caminho servidor -> cliente. send_message() codifica em JSON/UTF-8 e
        # termina em socket.sendall(); _send_lock serializa envios neste socket.
        send_message(self.connection, message, self._send_lock)

    def run(self) -> None:
        # ============================================================
        # PONTO DE RECEPÇÃO DAS MENSAGENS DO CLIENTE
        # recv() aguarda bytes no socket desta conexão. MessageBuffer recupera
        # mensagens JSON completas e _on_message aponta para
        # FanoronaServer._handle_message().
        # ============================================================
        parser = MessageBuffer()
        try:
            while not self._closed.is_set():
                chunk = self.connection.recv(4096)
                if not chunk:
                    break
                for item in parser.feed(chunk):
                    if isinstance(item, ProtocolError):
                        self.send(
                            {
                                "type": ERROR,
                                "code": "INVALID_MESSAGE",
                                "message": str(item),
                            }
                        )
                    else:
                        self._on_message(self, item)
        except (ConnectionError, OSError):
            pass
        finally:
            self.close()
            self._on_disconnect(self)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()
