"""Camada de conexão TCP independente da futura interface Tkinter."""

from __future__ import annotations

import queue
import socket
import threading
from typing import Any

from common.protocol import MessageBuffer, ProtocolError, send_message


class ServerConnection:
    """Recebe eventos em thread própria e os disponibiliza em uma fila."""

    # Esta classe não conhece widgets. Ela converte a rede em uma fila de
    # dicionários que tanto a GUI quanto o cliente de terminal podem consumir.

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        # Ponte thread-safe entre a thread receptora e a thread do Tkinter.
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._socket: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._receiver: threading.Thread | None = None
        self._closed = threading.Event()

    def connect(self, timeout: float = 5.0) -> None:
        # ============================================================
        # CRIAÇÃO DO SOCKET CLIENTE
        # socket(AF_INET, SOCK_STREAM) cria um socket IPv4/TCP.
        # connect() inicia a conexão com host e porta do servidor.
        # Depois, uma thread exclusiva assume o recv() bloqueante.
        # ============================================================
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(timeout)
        connection.connect((self.host, self.port))
        connection.settimeout(None)
        self._socket = connection
        self._receiver = threading.Thread(
            target=self._receive_loop, daemon=True, name="server-receiver"
        )
        self._receiver.start()

    def send(self, message: dict[str, Any]) -> None:
        # Caminho cliente -> servidor. send_message() termina a serialização
        # chamando socket.sendall(), protegido contra envios concorrentes.
        if self._socket is None or self._closed.is_set():
            raise ConnectionError("Cliente não está conectado")
        send_message(self._socket, message, self._send_lock)

    def _receive_loop(self) -> None:
        # ============================================================
        # THREAD DE RECEPÇÃO DO CLIENTE
        # recv() bloqueia até chegarem bytes, mas somente esta thread fica parada.
        # Cada mensagem pronta vai para events.put(); ela NUNCA altera Tkinter.
        #
        # rede -> recv() -> MessageBuffer -> queue.Queue
        #                                 -> root.after/process_queues na GUI
        # ============================================================
        parser = MessageBuffer()
        assert self._socket is not None
        try:
            while not self._closed.is_set():
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                for item in parser.feed(chunk):
                    if isinstance(item, ProtocolError):
                        self.events.put(
                            {
                                "type": "ERROR",
                                "code": "INVALID_MESSAGE",
                                "message": str(item),
                            }
                        )
                    else:
                        self.events.put(item)
        except (ConnectionError, OSError) as exc:
            if not self._closed.is_set():
                self.events.put({"type": "CONNECTION_ERROR", "message": str(exc)})
        finally:
            if not self._closed.is_set():
                self.events.put({"type": "CONNECTION_CLOSED"})
            self.close()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
