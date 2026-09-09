"""Protocolo de aplicação do Fanorona sobre TCP.

Cada mensagem é um objeto JSON codificado em UTF-8 e terminado por uma quebra
de linha. A classe :class:`MessageBuffer` preserva bytes de uma chamada para a
outra porque TCP pode fragmentar ou agrupar mensagens livremente.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any


ENCODING = "utf-8"
DELIMITER = b"\n"
MAX_BUFFER_SIZE = 1_048_576

# Os nomes das mensagens ficam centralizados aqui para cliente e servidor
# falarem exatamente o mesmo protocolo, sem strings diferentes espalhadas.
HELLO = "HELLO"
CONNECTED = "CONNECTED"
ASSIGN_PLAYER = "ASSIGN_PLAYER"
START = "START"
MOVE = "MOVE"
STATE = "STATE"
TURN = "TURN"
CHAT = "CHAT"
GIVEUP = "GIVEUP"
GAME_OVER = "GAME_OVER"
ERROR = "ERROR"
DISCONNECT = "DISCONNECT"


class ProtocolError(ValueError):
    """Indica uma mensagem que não obedece ao protocolo."""


# ============================================================
# CAMINHO DE ENVIO
# dicionário Python -> JSON -> UTF-8 -> bytes + "\n" -> socket
#
# A quebra de linha delimita o fim de uma mensagem. Isso é necessário porque
# TCP transporta um fluxo de bytes: um sendall() não corresponde
# necessariamente a um recv() do outro lado.
# ============================================================
def encode_message(message: dict[str, Any]) -> bytes:
    """Serializa uma mensagem como uma linha JSON UTF-8."""
    if not isinstance(message, dict):
        raise ProtocolError("A mensagem deve ser um objeto JSON")
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("A mensagem deve possuir um campo 'type' textual")
    try:
        payload = json.dumps(
            message, ensure_ascii=False, separators=(",", ":")
        ).encode(ENCODING)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("A mensagem contém dados não serializáveis") from exc
    return payload + DELIMITER


def send_message(
    connection: socket.socket,
    message: dict[str, Any],
    lock: threading.Lock | None = None,
) -> None:
    """Envia uma mensagem completa, opcionalmente protegendo o socket."""
    payload = encode_message(message)
    # sendall() insiste no envio de todo o payload. O lock opcional impede que
    # duas threads misturem bytes ao escrever simultaneamente no mesmo socket.
    if lock is None:
        connection.sendall(payload)
        return
    with lock:
        connection.sendall(payload)


ParsedItem = dict[str, Any] | ProtocolError


class MessageBuffer:
    """Reconstrói mensagens completas recebidas de um fluxo TCP."""

    def __init__(self, max_size: int = MAX_BUFFER_SIZE) -> None:
        self._buffer = bytearray()
        self._max_size = max_size

    def feed(self, data: bytes) -> list[ParsedItem]:
        """Adiciona bytes e devolve mensagens ou erros para cada linha completa.

        Um erro pertence somente à linha inválida. As linhas seguintes do mesmo
        bloco continuam sendo analisadas, evitando que dados válidos fiquem presos
        no buffer.
        """
        if not isinstance(data, bytes):
            raise TypeError("data deve ser bytes")
        # ============================================================
        # CAMINHO DE RECEPÇÃO
        # socket -> bytes -> buffer -> linha JSON -> json.loads() -> dict
        #
        # Um recv() pode trazer meia mensagem ou várias de uma vez. Por isso,
        # bytes sem "\n" permanecem guardados para a próxima chamada.
        # ============================================================
        self._buffer.extend(data)
        if len(self._buffer) > self._max_size:
            self._buffer.clear()
            raise ProtocolError("Buffer de recepção excedeu o limite")

        items: list[ParsedItem] = []
        while True:
            delimiter_index = self._buffer.find(DELIMITER)
            if delimiter_index < 0:
                break
            raw_line = bytes(self._buffer[:delimiter_index])
            del self._buffer[: delimiter_index + len(DELIMITER)]
            if not raw_line.strip():
                continue
            try:
                items.append(self._decode_line(raw_line))
            except ProtocolError as exc:
                items.append(exc)
        return items

    @staticmethod
    def _decode_line(raw_line: bytes) -> dict[str, Any]:
        try:
            decoded = raw_line.decode(ENCODING)
            message = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("JSON inválido recebido") from exc
        if not isinstance(message, dict):
            raise ProtocolError("A mensagem recebida deve ser um objeto JSON")
        message_type = message.get("type")
        if not isinstance(message_type, str) or not message_type:
            raise ProtocolError("A mensagem recebida não possui 'type' válido")
        return message
