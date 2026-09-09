"""Estado local de exibição e geometria pura usada pela interface Tkinter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from game.board import Board, EMPTY


@dataclass(frozen=True)
class BoardGeometry:
    """Converte coordenadas lógicas e gráficas sem depender do Tkinter."""

    # Centralizar estas contas evita espalhar pela GUI a correspondência entre
    # (linha, coluna) do Board e (x, y) do Canvas.

    width: int = 720
    height: int = 400
    padding: int = 42
    click_radius: int = 24

    def board_to_canvas(self, row: int, column: int) -> tuple[float, float]:
        if not Board.is_valid_position(row, column):
            raise ValueError("Posição fora do tabuleiro")
        horizontal_step = (self.width - 2 * self.padding) / (Board.COLUMNS - 1)
        vertical_step = (self.height - 2 * self.padding) / (Board.ROWS - 1)
        return (
            self.padding + column * horizontal_step,
            self.padding + row * vertical_step,
        )

    def canvas_to_board(self, x: float, y: float) -> tuple[int, int] | None:
        horizontal_step = (self.width - 2 * self.padding) / (Board.COLUMNS - 1)
        vertical_step = (self.height - 2 * self.padding) / (Board.ROWS - 1)
        column = round((x - self.padding) / horizontal_step)
        row = round((y - self.padding) / vertical_step)
        if not Board.is_valid_position(row, column):
            return None
        point_x, point_y = self.board_to_canvas(row, column)
        if (x - point_x) ** 2 + (y - point_y) ** 2 > self.click_radius**2:
            return None
        return row, column


@dataclass
class ClientGameState:
    """Cópia somente para exibição do estado recebido do servidor."""

    # Não é o estado oficial: o servidor possui essa autoridade. Antes de START
    # a matriz fica vazia; depois, START/STATE substituem a cópia inteira.

    player_id: int | None = None
    board: list[list[int]] = field(default_factory=lambda: Board.empty().serialize())
    current_player: int = 1
    started: bool = False
    game_over: bool = False
    winner: int | None = None
    capture_sequence: bool = False
    active_piece: tuple[int, int] | None = None

    def assign_player(self, message: dict[str, Any]) -> None:
        player = message.get("player")
        if player not in (1, 2):
            raise ValueError("Identificação de jogador inválida")
        self.player_id = player

    def apply_server_state(
        self, message: dict[str, Any], *, marks_start: bool = False
    ) -> None:
        """Atualiza todos os campos autoritativos em um único ponto."""
        # Ponto único de entrada do estado autoritativo na camada visual. A
        # validação evita que uma mensagem malformada corrompa o desenho.
        board = message.get("board")
        if (
            not isinstance(board, list)
            or len(board) != Board.ROWS
            or any(not isinstance(row, list) or len(row) != Board.COLUMNS for row in board)
            or any(piece not in (0, 1, 2) for row in board for piece in row)
        ):
            raise ValueError("Estado de tabuleiro inválido recebido")
        current_player = message.get("current_player")
        if current_player not in (1, 2):
            raise ValueError("Turno inválido recebido")
        winner = message.get("winner")
        if winner not in (None, 1, 2):
            raise ValueError("Vencedor inválido recebido")

        capture_sequence = bool(message.get("capture_sequence", False))
        active_raw = message.get("active_piece")
        active_piece: tuple[int, int] | None = None
        if capture_sequence:
            try:
                active_piece = Board.normalize_position(active_raw)
            except ValueError as exc:
                raise ValueError("Peça ativa inválida recebida") from exc

        self.board = [row[:] for row in board]
        self.current_player = current_player
        self.game_over = bool(message.get("game_over", False))
        self.winner = winner
        self.capture_sequence = capture_sequence
        self.active_piece = active_piece
        if marks_start:
            self.started = True

    def can_select(self, position: tuple[int, int]) -> bool:
        # Esta é apenas uma ajuda visual. As regras definitivas continuam sendo
        # verificadas no servidor por GameSession e Board.
        row, column = position
        if (
            self.player_id is None
            or not self.started
            or self.game_over
            or self.current_player != self.player_id
            or self.board[row][column] != self.player_id
        ):
            return False
        return not self.capture_sequence or position == self.active_piece

    def piece_at(self, position: tuple[int, int]) -> int:
        return self.board[position[0]][position[1]]

    def is_empty(self, position: tuple[int, int]) -> bool:
        return self.piece_at(position) == EMPTY
