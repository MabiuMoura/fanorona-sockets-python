"""Estado autoritativo compartilhado de uma partida."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING

from game.board import Board, InvalidMove, MoveResult, Position

if TYPE_CHECKING:
    from server.client_handler import ClientHandler


class SessionError(ValueError):
    """Erro de regra com um código apropriado para o protocolo."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class CaptureSequence:
    active_piece: Position
    visited_positions: set[Position]


class GameSession:
    """Mantém jogadores, tabuleiro, turno e encerramento da partida."""

    # ============================================================
    # ESTADO OFICIAL DA PARTIDA
    # Esta instância existe no servidor e é a fonte de verdade. Ela sabe quem
    # está conectado, qual é o tabuleiro, de quem é o turno, se há sequência,
    # se a partida terminou e quem venceu. Os clientes mantêm apenas uma cópia
    # para exibição, atualizada pelas mensagens START e STATE.
    # ============================================================

    MAX_PLAYERS = 2

    def __init__(self) -> None:
        self.players: dict[int, ClientHandler] = {}
        self.board = Board()
        self.current_player = 1
        self.game_started = False
        self.game_over = False
        self.winner: int | None = None
        self.end_reason: str | None = None
        self.capture_sequence: CaptureSequence | None = None
        # ClientHandler P1 e P2 executam em threads distintas. O RLock protege
        # este estado compartilhado contra validações/alterações simultâneas.
        self.lock = threading.RLock()

    def add_player(self, handler: ClientHandler) -> int:
        with self.lock:
            if self.game_started or len(self.players) >= self.MAX_PLAYERS:
                raise RuntimeError("A partida já possui dois jogadores")
            player_id = next(
                candidate
                for candidate in range(1, self.MAX_PLAYERS + 1)
                if candidate not in self.players
            )
            self.players[player_id] = handler
            return player_id

    def remove_player(self, player_id: int) -> None:
        with self.lock:
            self.players.pop(player_id, None)

    def try_start(self) -> bool:
        """Inicia atomicamente quando os dois jogadores estão conectados."""
        # Verifica e marca o início dentro do mesmo lock; assim duas threads não
        # conseguem iniciar a mesma partida duas vezes.
        with self.lock:
            if len(self.players) != self.MAX_PLAYERS or self.game_started:
                return False
            self.game_started = True
            self.current_player = 1
            return True

    def has_player(self, player_id: int | None) -> bool:
        with self.lock:
            return player_id is not None and player_id in self.players

    def state(self) -> dict:
        with self.lock:
            return self._state_unlocked()

    def try_move(
        self,
        player_id: int,
        origin: object,
        destination: object,
        capture: object = None,
    ) -> tuple[dict, MoveResult]:
        """Aplica uma jogada e atualiza sequência, turno ou vitória."""
        with self.lock:
            # Fluxo autoritativo da jogada:
            # 1. valida partida e turno;
            # 2. normaliza as coordenadas;
            # 3. aplica restrições da sequência;
            # 4. pede a Board para validar e aplicar o movimento/captura;
            # 5. verifica continuação, troca de turno ou vitória;
            # 6. devolve um novo estado serializável para o servidor transmitir.
            self._validate_active_game(player_id)
            try:
                origin_position = Board.normalize_position(origin)
                destination_position = Board.normalize_position(destination)
            except InvalidMove as exc:
                raise SessionError(exc.code, str(exc)) from exc

            sequence = self.capture_sequence
            if sequence is not None:
                if origin_position != sequence.active_piece:
                    raise SessionError(
                        "SEQUENCE_PIECE_REQUIRED",
                        "A sequência deve continuar com a mesma peça",
                    )
                if destination_position in sequence.visited_positions:
                    raise SessionError(
                        "POSITION_ALREADY_VISITED",
                        "Uma posição da sequência não pode ser revisitada",
                    )

            try:
                result = self.board.apply_move(
                    player_id,
                    origin_position,
                    destination_position,
                    capture,
                    capture_required=sequence is not None,
                )
            except InvalidMove as exc:
                raise SessionError(exc.code, str(exc)) from exc

            if result.is_capture:
                self._after_capture(player_id, result, sequence)
            else:
                self.capture_sequence = None
                self._change_turn(player_id)
            return self._state_unlocked(), result

    def _validate_active_game(self, player_id: int) -> None:
        if not self.game_started:
            raise SessionError("GAME_NOT_STARTED", "A partida ainda não iniciou")
        if self.game_over:
            raise SessionError("GAME_ALREADY_OVER", "A partida já terminou")
        if player_id != self.current_player:
            raise SessionError("NOT_YOUR_TURN", "Não é o seu turno")

    def _after_capture(
        self,
        player_id: int,
        result: MoveResult,
        previous_sequence: CaptureSequence | None,
    ) -> None:
        # A eliminação da última peça encerra a partida antes de procurar
        # outra captura para a sequência.
        if self.board.count_pieces(Board.opponent(player_id)) == 0:
            self.game_over = True
            self.winner = player_id
            self.end_reason = "no_pieces"
            self.capture_sequence = None
            return

        visited = (
            set(previous_sequence.visited_positions)
            if previous_sequence is not None
            else {result.origin}
        )
        visited.add(result.destination)
        # Enquanto houver captura válida a peça e o turno permanecem ativos.
        # Sem continuação, a sequência é limpa e o adversário recebe o turno.
        if self.board.has_capture_from(player_id, result.destination, visited):
            self.capture_sequence = CaptureSequence(result.destination, visited)
        else:
            self.capture_sequence = None
            self._change_turn(player_id)

    def _change_turn(self, player_id: int) -> None:
        self.current_player = 2 if player_id == 1 else 1

    def give_up(self, player_id: int) -> dict:
        with self.lock:
            if not self.game_started:
                raise SessionError("GAME_NOT_STARTED", "A partida ainda não iniciou")
            if self.game_over:
                raise SessionError("GAME_ALREADY_OVER", "A partida já terminou")
            if player_id not in self.players:
                raise SessionError("INVALID_GIVEUP", "Jogador não conectado")
            self.game_over = True
            self.winner = Board.opponent(player_id)
            self.end_reason = "give_up"
            self.capture_sequence = None
            return self._state_unlocked()

    def disconnect(self, player_id: int) -> dict | None:
        """Remove o jogador e encerra somente se a partida estava em andamento."""
        with self.lock:
            self.players.pop(player_id, None)
            if not self.game_started or self.game_over:
                return None
            self.game_over = True
            self.winner = Board.opponent(player_id)
            self.end_reason = "disconnect"
            self.capture_sequence = None
            return self._state_unlocked()

    def _state_unlocked(self) -> dict:
        # Somente tipos compatíveis com JSON saem da sessão. Objetos Board e
        # CaptureSequence nunca são enviados diretamente pelo socket.
        sequence = self.capture_sequence
        return {
            "board": self.board.serialize(),
            "current_player": self.current_player,
            "game_over": self.game_over,
            "winner": int(self.winner) if self.winner is not None else None,
            "capture_sequence": sequence is not None,
            "active_piece": list(sequence.active_piece) if sequence else None,
        }

    def handlers(self) -> list[ClientHandler]:
        with self.lock:
            return list(self.players.values())
