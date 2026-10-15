"""Servidor RPC do Fanorona baseado exclusivamente em Pyro5."""
from __future__ import annotations
import argparse
import logging
import secrets
import threading
from typing import Any
import Pyro5.api
from server.game_session import GameSession, SessionError

LOGGER = logging.getLogger("fanorona.server")

@Pyro5.api.expose
@Pyro5.api.behavior(instance_mode="single")
class FanoronaRemoteGame:
    """Objeto remoto autoritativo; cada ação é um método RPC explícito."""
    def __init__(self) -> None:
        self.session = GameSession()
        self._action_lock = threading.RLock()
        self._messages: list[dict[str, Any]] = []
        self._message_id = 0
        # O token é a credencial de cada conexão lógica. Ele não integra o
        # estado público da partida, mensagens de chat ou serialização do Board.
        self._player_tokens: dict[str, int] = {}

    @staticmethod
    def _failure(error: SessionError | str, code: str = "INVALID_REQUEST") -> dict:
        if isinstance(error, SessionError):
            return {"ok": False, "code": error.code, "message": str(error)}
        return {"ok": False, "code": code, "message": error}

    def registrar_jogador(self, nome: str = "") -> dict:
        """Registra um jogador e inicia a partida ao receber o segundo."""
        if not isinstance(nome, str): return self._failure("O nome deve ser texto")
        with self._action_lock:
            try: player = self.session.add_player(nome.strip()[:60])
            except RuntimeError as exc: return self._failure(str(exc), "GAME_FULL")
            token = secrets.token_urlsafe(32)
            self._player_tokens[token] = player
            return {"ok": True, "player": player, "token": token,
                    "started": self.session.try_start(), "state": self.session.state()}

    def iniciar_partida(self) -> dict:
        """Tenta iniciar a partida; o segundo registro normalmente já a inicia."""
        with self._action_lock:
            return {"ok": True, "started": self.session.try_start(), "state": self.session.state()}

    def _player_for_token(self, token: object) -> int | None:
        """Obtém a identidade registrada para um token, sem expô-lo no estado."""
        return self._player_tokens.get(token) if isinstance(token, str) else None

    def mover(self, token: str, origem: object, destino: object, tipo_captura: object = None) -> dict:
        """Valida e aplica uma jogada ou etapa de sequência de capturas."""
        with self._action_lock:
            jogador = self._player_for_token(token)
            if jogador is None: return self._failure("Sessão de jogador inválida", "INVALID_SESSION")
            try:
                state, result = self.session.try_move(jogador, origem, destino, tipo_captura)
                return {"ok": True, "state": state, "captured": [list(p) for p in result.captured]}
            except SessionError as exc: return self._failure(exc)

    def obter_estado(self) -> dict:
        """Retorna a cópia serializável mais recente do estado oficial."""
        return self.session.state()

    def enviar_mensagem(self, token: str, mensagem: str) -> dict:
        """Publica uma mensagem de chat associada ao jogador."""
        with self._action_lock:
            jogador = self._player_for_token(token)
            if jogador is None: return self._failure("Sessão de jogador inválida", "INVALID_SESSION")
            if not self.session.has_player(jogador): return self._failure("Jogador não conectado", "INVALID_CHAT")
            if not isinstance(mensagem, str) or not mensagem.strip() or len(mensagem.strip()) > 500:
                return self._failure("A mensagem deve conter de 1 a 500 caracteres", "INVALID_CHAT")
            self._message_id += 1
            self._messages.append({"id": self._message_id, "player": jogador, "message": mensagem.strip()})
            return {"ok": True}

    def obter_mensagens(self, depois_de: int = 0) -> list[dict]:
        """Retorna mensagens posteriores ao identificador, para polling RPC."""
        with self._action_lock: return [dict(item) for item in self._messages if item["id"] > depois_de]

    def desistir(self, token: str) -> dict:
        """Encerra a partida e declara vencedor o adversário."""
        with self._action_lock:
            jogador = self._player_for_token(token)
            if jogador is None: return self._failure("Sessão de jogador inválida", "INVALID_SESSION")
            try: return {"ok": True, "state": self.session.give_up(jogador)}
            except SessionError as exc: return self._failure(exc)

    def desconectar(self, token: str) -> dict:
        """Remove o jogador; durante partida, concede vitória ao outro."""
        with self._action_lock:
            jogador = self._player_for_token(token)
            if jogador is None: return self._failure("Sessão de jogador inválida", "INVALID_SESSION")
            state = self.session.disconnect(jogador)
            self._player_tokens.pop(token, None)
            return {"ok": True, "state": state}

class FanoronaServer:
    """Hospeda o objeto remoto no daemon Pyro5."""
    def __init__(self, host: str = "0.0.0.0", port: int = 5000) -> None:
        self.host, self.port = host, port
        self.remote_game = FanoronaRemoteGame()
        self.session = self.remote_game.session
        self._daemon: Pyro5.api.Daemon | None = None
    def serve_forever(self) -> None:
        daemon = Pyro5.api.Daemon(host=self.host, port=self.port)
        self._daemon = daemon
        uri = daemon.register(self.remote_game, objectId="fanorona")
        self.port = daemon.sock.getsockname()[1]
        LOGGER.info("[SERVER] Fanorona RPC disponível em %s", uri)
        daemon.requestLoop()
    def stop(self) -> None:
        if self._daemon is not None: self._daemon.shutdown()

def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor Pyro5 do Fanorona")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = FanoronaServer(args.host, args.port)
    try: server.serve_forever()
    except KeyboardInterrupt: LOGGER.info("[SERVER] Encerrando")
    finally: server.stop()

if __name__ == "__main__": main()
