"""Tabuleiro e regras geométricas do Fanorona, sem rede ou interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Sequence


class Piece(IntEnum):
    EMPTY = 0
    PLAYER_1 = 1
    PLAYER_2 = 2


EMPTY = Piece.EMPTY
PLAYER_1 = Piece.PLAYER_1
PLAYER_2 = Piece.PLAYER_2

APPROACH = "approach"
WITHDRAWAL = "withdrawal"
CAPTURE_MODES = {APPROACH, WITHDRAWAL}

Position = tuple[int, int]


class InvalidMove(ValueError):
    """Movimento recusado com um código apropriado ao protocolo."""

    def __init__(self, message: str, code: str = "INVALID_MOVE") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MoveResult:
    origin: Position
    destination: Position
    capture_mode: str | None
    captured: tuple[Position, ...]

    @property
    def is_capture(self) -> bool:
        return bool(self.captured)


class Board:
    """Matriz 5x9 e conexões reais entre seus 45 pontos."""

    # ============================================================
    # CAMADA DE REGRAS
    # Board não conhece sockets, threads ou Tkinter. Ele recebe valores Python,
    # valida a geometria do Fanorona e altera somente a matriz de peças.
    # GameSession é quem decide quando e qual jogador pode chamar essas regras.
    # ============================================================

    ROWS = 5
    COLUMNS = 9

    def __init__(self, grid: Sequence[Sequence[int]] | None = None) -> None:
        self._grid = self._initial_grid() if grid is None else self._copy_grid(grid)

    @classmethod
    def empty(cls) -> "Board":
        return cls([[EMPTY] * cls.COLUMNS for _ in range(cls.ROWS)])

    @classmethod
    def _initial_grid(cls) -> list[list[Piece]]:
        grid = [[PLAYER_2 for _ in range(cls.COLUMNS)] for _ in range(2)]
        grid.append(
            [
                PLAYER_2,
                PLAYER_1,
                PLAYER_2,
                PLAYER_1,
                EMPTY,
                PLAYER_2,
                PLAYER_1,
                PLAYER_2,
                PLAYER_1,
            ]
        )
        grid.extend([[PLAYER_1 for _ in range(cls.COLUMNS)] for _ in range(2)])
        return grid

    @classmethod
    def _copy_grid(cls, grid: Sequence[Sequence[int]]) -> list[list[Piece]]:
        if len(grid) != cls.ROWS or any(len(row) != cls.COLUMNS for row in grid):
            raise ValueError("O tabuleiro deve possuir 5 linhas e 9 colunas")
        try:
            return [[Piece(value) for value in row] for row in grid]
        except ValueError as exc:
            raise ValueError("O tabuleiro contém uma peça inválida") from exc

    @classmethod
    def is_valid_position(cls, row: int, column: int) -> bool:
        return (
            isinstance(row, int)
            and not isinstance(row, bool)
            and isinstance(column, int)
            and not isinstance(column, bool)
            and 0 <= row < cls.ROWS
            and 0 <= column < cls.COLUMNS
        )

    @classmethod
    def normalize_position(cls, position: object) -> Position:
        if (
            not isinstance(position, (list, tuple))
            or len(position) != 2
            or not cls.is_valid_position(position[0], position[1])
        ):
            raise InvalidMove("Coordenadas inválidas")
        return position[0], position[1]

    def get_piece(self, row: int, column: int) -> Piece:
        if not self.is_valid_position(row, column):
            raise IndexError("Posição fora do tabuleiro")
        return self._grid[row][column]

    def set_piece(self, row: int, column: int, piece: int) -> None:
        """Configura uma posição; útil para montar cenários de regras."""
        if not self.is_valid_position(row, column):
            raise IndexError("Posição fora do tabuleiro")
        self._grid[row][column] = Piece(piece)

    def is_empty(self, row: int, column: int) -> bool:
        return self.get_piece(row, column) == EMPTY

    def neighbors(self, row: int, column: int) -> list[Position]:
        """Retorna pontos adjacentes ligados por uma linha do tabuleiro."""
        if not self.is_valid_position(row, column):
            raise IndexError("Posição fora do tabuleiro")
        # Horizontais e verticais existem em todos os pontos. Diagonais existem
        # apenas nos cruzamentos pares, reproduzindo as linhas reais do tabuleiro.
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if (row + column) % 2 == 0:
            directions.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])
        return [
            (row + row_delta, column + column_delta)
            for row_delta, column_delta in directions
            if self.is_valid_position(row + row_delta, column + column_delta)
        ]

    def are_connected(self, first: Position, second: Position) -> bool:
        return second in self.neighbors(*first)

    @staticmethod
    def opponent(player: int) -> Piece:
        if player == PLAYER_1:
            return PLAYER_2
        if player == PLAYER_2:
            return PLAYER_1
        raise InvalidMove("Jogador inválido")

    def get_approach_captures(
        self, player: int, origin: object, destination: object
    ) -> list[Position]:
        # APROXIMAÇÃO: origem -> destino -> adversários.
        # O vetor do movimento é mantido depois do destino.
        origin_position, destination_position = self._validate_geometry(
            player, origin, destination
        )
        row_delta = destination_position[0] - origin_position[0]
        column_delta = destination_position[1] - origin_position[1]
        return self._opponent_line(
            player, destination_position, row_delta, column_delta
        )

    def get_withdrawal_captures(
        self, player: int, origin: object, destination: object
    ) -> list[Position]:
        # AFASTAMENTO: adversários <- origem -> destino.
        # O vetor é invertido para procurar atrás da origem.
        origin_position, destination_position = self._validate_geometry(
            player, origin, destination
        )
        row_delta = origin_position[0] - destination_position[0]
        column_delta = origin_position[1] - destination_position[1]
        return self._opponent_line(player, origin_position, row_delta, column_delta)

    def capture_options(
        self, player: int, origin: object, destination: object
    ) -> dict[str, list[Position]]:
        approach = self.get_approach_captures(player, origin, destination)
        withdrawal = self.get_withdrawal_captures(player, origin, destination)
        options: dict[str, list[Position]] = {}
        if approach:
            options[APPROACH] = approach
        if withdrawal:
            options[WITHDRAWAL] = withdrawal
        return options

    def _validate_geometry(
        self, player: int, origin: object, destination: object
    ) -> tuple[Position, Position]:
        self.opponent(player)
        origin_position = self.normalize_position(origin)
        destination_position = self.normalize_position(destination)
        if self.get_piece(*origin_position) != player:
            raise InvalidMove("A origem não possui uma peça do jogador")
        if not self.is_empty(*destination_position):
            raise InvalidMove("O destino não está vazio")
        if not self.are_connected(origin_position, destination_position):
            raise InvalidMove("Origem e destino não estão conectados")
        return origin_position, destination_position

    def _opponent_line(
        self, player: int, anchor: Position, row_delta: int, column_delta: int
    ) -> list[Position]:
        opponent = self.opponent(player)
        captures: list[Position] = []
        previous = anchor
        candidate = (anchor[0] + row_delta, anchor[1] + column_delta)
        # Captura somente a sequência contínua: a busca para na borda, numa
        # conexão inexistente, numa casa vazia ou numa peça do próprio jogador.
        while (
            self.is_valid_position(*candidate)
            and self.are_connected(previous, candidate)
            and self.get_piece(*candidate) == opponent
        ):
            captures.append(candidate)
            previous = candidate
            candidate = (candidate[0] + row_delta, candidate[1] + column_delta)
        return captures

    def apply_move(
        self,
        player: int,
        origin: object,
        destination: object,
        capture: object = None,
        capture_required: bool = False,
    ) -> MoveResult:
        """Aplica movimento e a forma de captura escolhida, quando houver."""
        # ============================================================
        # APLICAÇÃO DE UM MOVIMENTO NO TABULEIRO
        # Primeiro tudo é validado e as capturas são calculadas. A matriz só é
        # modificada depois disso, evitando alteração parcial numa jogada inválida.
        # ============================================================
        origin_position, destination_position = self._validate_geometry(
            player, origin, destination
        )
        if capture is not None and (
            not isinstance(capture, str) or capture not in CAPTURE_MODES
        ):
            raise InvalidMove("Forma de captura inválida", "INVALID_CAPTURE")

        options = self.capture_options(player, origin_position, destination_position)
        if len(options) == 2 and capture is None:
            raise InvalidMove(
                "Escolha captura por aproximação ou afastamento",
                "CAPTURE_CHOICE_REQUIRED",
            )
        if capture is not None and capture not in options:
            raise InvalidMove(
                "A captura escolhida não existe para esse movimento",
                "INVALID_CAPTURE",
            )
        if capture_required and not options:
            raise InvalidMove(
                "A sequência exige um movimento de captura", "CAPTURE_REQUIRED"
            )

        capture_mode = capture if capture is not None else next(iter(options), None)
        captured = tuple(options.get(capture_mode, []))
        self._grid[destination_position[0]][destination_position[1]] = Piece(player)
        self._grid[origin_position[0]][origin_position[1]] = EMPTY
        for position in captured:
            self._grid[position[0]][position[1]] = EMPTY
        return MoveResult(origin_position, destination_position, capture_mode, captured)

    def move_piece(
        self, player: int, origin: object, destination: object
    ) -> MoveResult:
        """Compatibilidade: aplica um movimento sem escolha explícita."""
        return self.apply_move(player, origin, destination)

    def has_capture_from(
        self,
        player: int,
        origin: Position,
        forbidden_destinations: Iterable[Position] = (),
    ) -> bool:
        # GameSession usa esta consulta depois de uma captura para decidir se a
        # mesma peça deve continuar jogando. Destinos visitados são descartados.
        forbidden = set(forbidden_destinations)
        for destination in self.neighbors(*origin):
            if destination in forbidden or not self.is_empty(*destination):
                continue
            if self.capture_options(player, origin, destination):
                return True
        return False

    def count_pieces(self, player: int) -> int:
        piece = Piece(player)
        return sum(cell == piece for row in self._grid for cell in row)

    def serialize(self) -> list[list[int]]:
        return [[int(piece) for piece in row] for row in self._grid]
