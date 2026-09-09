"""Interface gráfica Tkinter do cliente Fanorona."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any

from client.connection import ServerConnection
from client.gui_model import BoardGeometry, ClientGameState
from common.protocol import (
    ASSIGN_PLAYER,
    CHAT,
    CONNECTED,
    DISCONNECT,
    ERROR,
    GAME_OVER,
    GIVEUP,
    MOVE,
    START,
    STATE,
)
from game.board import Board, EMPTY, PLAYER_1, PLAYER_2


# ============================================================
# CONFIGURAÇÃO VISUAL E MENSAGENS AMIGÁVEIS
# Cores e textos ficam fora da classe porque não representam estado da partida.
# ============================================================
BG = "#f3eee4"
PANEL = "#fffaf0"
INK = "#27313a"
MUTED = "#66717b"
ACCENT = "#247ba0"
PLAYER_COLORS = {PLAYER_1: "#2457a6", PLAYER_2: "#c84b31"}


ERROR_MESSAGES = {
    "NOT_YOUR_TURN": "Aguarde o turno do adversário.",
    "INVALID_MOVE": "Esse movimento não é válido.",
    "INVALID_CAPTURE": "A forma de captura escolhida não é válida.",
    "CAPTURE_REQUIRED": "Continue a sequência realizando uma captura.",
    "SEQUENCE_PIECE_REQUIRED": "Continue com a peça destacada.",
    "POSITION_ALREADY_VISITED": "Essa posição já foi visitada na sequência.",
    "GAME_ALREADY_OVER": "A partida já terminou.",
    "GAME_NOT_STARTED": "Aguarde o segundo jogador.",
    "INVALID_CHAT": "A mensagem de chat não é válida.",
}


class FanoronaGUI:
    # FanoronaGUI vive na thread principal do Tkinter. Nenhum método chamado pela
    # thread de rede toca diretamente nos widgets.
    POLL_INTERVAL_MS = 50

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Fanorona")
        self.root.configure(bg=BG)
        self.root.minsize(880, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.geometry = BoardGeometry()
        self.topology = Board()
        self.state = ClientGameState()
        self.connection: ServerConnection | None = None
        # app_events recebe o resultado da thread temporária de conexão.
        # Mensagens TCP normais chegam em ServerConnection.events.
        self.app_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.selected: tuple[int, int] | None = None
        self.pending_move: dict[str, Any] | None = None
        self.request_pending = False
        self.capture_dialog: tk.Toplevel | None = None
        self.closing = False
        self.game_over_announced = False

        self.status_var = tk.StringVar(value="Informe o servidor para começar.")
        self.player_var = tk.StringVar(value="Jogador: aguardando")
        self.turn_var = tk.StringVar(value="Turno: aguardando")
        self.build_connection_screen()
        # Inicia o ciclo que consulta as filas sem bloquear o mainloop().
        self.root.after(self.POLL_INTERVAL_MS, self.process_queues)

    def clear_window(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def build_connection_screen(self) -> None:
        # ============================================================
        # TELA DE CONEXÃO
        # O usuário escolhe IP/porta; o clique não executa connect() diretamente
        # porque essa operação pode demorar e congelaria a janela.
        # ============================================================
        self.clear_window()
        self.root.minsize(500, 360)
        self.root.geometry("520x390")
        container = tk.Frame(self.root, bg=BG, padx=55, pady=42)
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="FANORONA",
            font=("Segoe UI", 25, "bold"),
            fg=INK,
            bg=BG,
        ).pack(pady=(5, 4))
        tk.Label(
            container,
            text="Jogo distribuído por sockets TCP",
            font=("Segoe UI", 10),
            fg=MUTED,
            bg=BG,
        ).pack(pady=(0, 25))

        card = tk.Frame(container, bg=PANEL, padx=28, pady=22, bd=1, relief="solid")
        card.pack(fill="x")
        tk.Label(card, text="Servidor", font=("Segoe UI", 10, "bold"), bg=PANEL).pack(
            anchor="w"
        )
        self.host_entry = tk.Entry(card, font=("Consolas", 11), relief="solid", bd=1)
        self.host_entry.insert(0, "127.0.0.1")
        self.host_entry.pack(fill="x", pady=(5, 13), ipady=5)
        tk.Label(card, text="Porta", font=("Segoe UI", 10, "bold"), bg=PANEL).pack(
            anchor="w"
        )
        self.port_entry = tk.Entry(card, font=("Consolas", 11), relief="solid", bd=1)
        self.port_entry.insert(0, "5000")
        self.port_entry.pack(fill="x", pady=(5, 17), ipady=5)
        self.connect_button = tk.Button(
            card,
            text="Conectar",
            command=self.start_connection,
            bg=ACCENT,
            fg="white",
            activebackground="#1d6684",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            cursor="hand2",
        )
        self.connect_button.pack(fill="x", ipady=7)
        self.connection_status = tk.Label(
            container,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=BG,
            wraplength=400,
        )
        self.connection_status.pack(pady=14)
        self.host_entry.focus_set()
        self.root.bind("<Return>", lambda _event: self.start_connection())

    def start_connection(self) -> None:
        if str(self.connect_button["state"]) == "disabled":
            return
        host = self.host_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            self.status_var.set("A porta precisa ser um número inteiro.")
            return
        if not host or not 1 <= port <= 65535:
            self.status_var.set("Informe um servidor e uma porta entre 1 e 65535.")
            return
        self.connect_button.configure(state="disabled")
        self.status_var.set(f"Conectando a {host}:{port}...")
        # THREAD DE CONEXÃO: existe apenas para o connect() inicial. O resultado
        # volta para a thread Tkinter por app_events, nunca por acesso a widgets.
        threading.Thread(
            target=self._connection_worker,
            args=(host, port),
            daemon=True,
            name="connection-starter",
        ).start()

    def _connection_worker(self, host: str, port: int) -> None:
        connection = ServerConnection(host, port)
        try:
            connection.connect()
        except (ConnectionError, OSError) as exc:
            connection.close()
            self.app_events.put(("CONNECT_ERROR", str(exc)))
            return
        if self.closing:
            connection.close()
            return
        self.app_events.put(("CONNECTED_SOCKET", connection))

    def build_game_screen(self) -> None:
        # ============================================================
        # TELA DO JOGO
        # Constrói Canvas, painel de estado, legenda, chat e desistência.
        # ============================================================
        self.clear_window()
        self.root.unbind("<Return>")
        self.root.geometry("1080x730")
        self.root.minsize(980, 690)

        header = tk.Frame(self.root, bg=INK, height=58)
        header.pack(fill="x")
        tk.Label(
            header,
            text="FANORONA",
            font=("Segoe UI", 20, "bold"),
            fg="white",
            bg=INK,
        ).pack(pady=12)

        content = tk.Frame(self.root, bg=BG, padx=18, pady=16)
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        board_panel = tk.Frame(content, bg=PANEL, bd=1, relief="solid")
        board_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.canvas = tk.Canvas(
            board_panel,
            width=self.geometry.width,
            height=self.geometry.height,
            bg="#e6c98e",
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack(padx=12, pady=12, expand=True)
        self.canvas.bind("<Button-1>", self.on_board_click)

        side = tk.Frame(content, bg=PANEL, width=245, padx=18, pady=18, bd=1, relief="solid")
        side.grid(row=0, column=1, sticky="ns")
        side.grid_propagate(False)
        tk.Label(side, textvariable=self.player_var, bg=PANEL, fg=INK, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(side, textvariable=self.turn_var, bg=PANEL, fg=ACCENT, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
        tk.Label(side, text="Status", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(20, 4))
        tk.Label(
            side,
            textvariable=self.status_var,
            bg=PANEL,
            fg=INK,
            justify="left",
            wraplength=200,
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        legend = tk.Frame(side, bg=PANEL)
        legend.pack(anchor="w", pady=(28, 20))
        for player in (PLAYER_1, PLAYER_2):
            row = tk.Frame(legend, bg=PANEL)
            row.pack(anchor="w", pady=3)
            tk.Label(row, text="●", fg=PLAYER_COLORS[player], bg=PANEL, font=("Segoe UI", 17)).pack(side="left")
            tk.Label(row, text=f" Player {int(player)}", fg=INK, bg=PANEL, font=("Segoe UI", 9)).pack(side="left")

        self.giveup_button = tk.Button(
            side,
            text="Desistir",
            command=self.confirm_give_up,
            state="disabled",
            bg="#a63d40",
            fg="white",
            activebackground="#852f32",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.giveup_button.pack(side="bottom", fill="x", ipady=7)

        chat_panel = tk.Frame(self.root, bg=BG, padx=18)
        chat_panel.pack(fill="x", pady=(0, 16))
        tk.Label(chat_panel, text="Chat", bg=BG, fg=INK, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.chat_history = tk.Text(
            chat_panel,
            height=6,
            state="disabled",
            wrap="word",
            bg=PANEL,
            fg=INK,
            font=("Segoe UI", 9),
            relief="solid",
            bd=1,
            padx=8,
            pady=6,
        )
        self.chat_history.pack(fill="x", pady=(5, 7))
        chat_controls = tk.Frame(chat_panel, bg=BG)
        chat_controls.pack(fill="x")
        self.chat_entry = tk.Entry(chat_controls, font=("Segoe UI", 10), relief="solid", bd=1)
        self.chat_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.chat_entry.bind("<Return>", lambda _event: self.send_chat())
        self.chat_button = tk.Button(
            chat_controls,
            text="Enviar",
            command=self.send_chat,
            bg=ACCENT,
            fg="white",
            activebackground="#1d6684",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        self.chat_button.pack(side="left", padx=(8, 0), ipadx=16, ipady=5)
        self.redraw_board()
        self.update_labels()

    def process_queues(self) -> None:
        # ============================================================
        # INTEGRAÇÃO THREAD DE REDE -> TKINTER
        # thread de rede -> recv() -> queue.Queue -> process_queues() -> widgets
        #
        # Tkinter não é thread-safe. Por isso somente este método, executado na
        # thread principal via root.after(), encaminha eventos para a interface.
        # Os 50 ms são apenas o intervalo escolhido para consultar as filas.
        # ============================================================
        if self.closing:
            return
        while True:
            try:
                event_type, payload = self.app_events.get_nowait()
            except queue.Empty:
                break
            if event_type == "CONNECTED_SOCKET":
                self.connection = payload
                self.status_var.set("Conectado. Aguardando identificação...")
                self.build_game_screen()
            elif event_type == "CONNECT_ERROR":
                self.status_var.set(f"Não foi possível conectar: {payload}")
                if hasattr(self, "connect_button"):
                    self.connect_button.configure(state="normal")
                messagebox.showerror("Falha de conexão", str(payload), parent=self.root)

        active_connection = self.connection
        if active_connection is not None:
            while True:
                try:
                    message = active_connection.events.get_nowait()
                except queue.Empty:
                    break
                self.handle_network_message(message)
                if self.connection is not active_connection:
                    break
        self.root.after(self.POLL_INTERVAL_MS, self.process_queues)

    def handle_network_message(self, message: dict[str, Any]) -> None:
        # Dispatcher visual: transforma cada fato produzido pelo servidor em uma
        # atualização de modelo, status, chat ou modal.
        message_type = message.get("type")
        if message_type == CONNECTED:
            self.status_var.set("Conectado. Aguardando o segundo jogador...")
        elif message_type == ASSIGN_PLAYER:
            try:
                self.state.assign_player(message)
            except ValueError as exc:
                self.status_var.set(str(exc))
                return
            self.update_labels()
        elif message_type == START:
            self.handle_state(message, marks_start=True)
            self.append_chat("Sistema: partida iniciada; Player 1 começa.")
        elif message_type == STATE:
            self.handle_state(message)
        elif message_type == CHAT:
            self.append_chat(
                f"Player {message.get('player', '?')}: {message.get('message', '')}"
            )
        elif message_type == ERROR:
            self.handle_error(message)
        elif message_type == GAME_OVER:
            self.handle_game_over(message)
        elif message_type == DISCONNECT:
            self.status_var.set(f"Player {message.get('player', '?')} desconectou.")
        elif message_type in {"CONNECTION_CLOSED", "CONNECTION_ERROR"}:
            self.request_pending = False
            self.close_capture_dialog()
            self.disable_game_actions()
            if not self.state.game_over:
                detail = message.get("message", "Conexão encerrada pelo servidor.")
                self.status_var.set(str(detail))
                messagebox.showwarning("Conexão encerrada", str(detail), parent=self.root)

    def handle_state(self, message: dict[str, Any], marks_start: bool = False) -> None:
        # START e STATE convergem aqui. A cópia local é substituída e o Canvas
        # redesenhado; este é o ponto que confirma visualmente uma jogada.
        try:
            self.state.apply_server_state(message, marks_start=marks_start)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        self.request_pending = False
        self.pending_move = None
        if (
            self.state.capture_sequence
            and self.state.current_player == self.state.player_id
        ):
            self.selected = self.state.active_piece
        else:
            self.selected = None
        self.redraw_board()
        self.update_labels()

    def update_labels(self) -> None:
        if not hasattr(self, "giveup_button"):
            return
        if self.state.player_id is None:
            self.player_var.set("Jogador: aguardando")
        else:
            self.player_var.set(f"Você é o Player {self.state.player_id}")
        self.turn_var.set(f"Turno: Player {self.state.current_player}")

        if self.state.game_over:
            self.status_var.set("Partida encerrada.")
        elif not self.state.started:
            self.status_var.set("Aguardando o segundo jogador...")
        elif self.state.capture_sequence:
            if self.state.current_player == self.state.player_id:
                self.status_var.set(
                    "Sequência de captura — continue com a peça destacada."
                )
            else:
                self.status_var.set("O adversário está em uma sequência de captura.")
        elif self.state.current_player == self.state.player_id:
            self.status_var.set("Seu turno. Selecione uma peça.")
        else:
            self.status_var.set("Turno do adversário.")
        self.giveup_button.configure(
            state="normal" if self.state.started and not self.state.game_over else "disabled"
        )

    def redraw_board(self) -> None:
        # ============================================================
        # DESENHO DO TABULEIRO
        # A topologia visual reutiliza Board.neighbors(), portanto as diagonais
        # desenhadas são as mesmas conexões aceitas pelas regras do servidor.
        # ============================================================
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        for row in range(Board.ROWS):
            for column in range(Board.COLUMNS):
                origin = (row, column)
                origin_x, origin_y = self.geometry.board_to_canvas(*origin)
                for neighbor in self.topology.neighbors(*origin):
                    if neighbor <= origin:
                        continue
                    target_x, target_y = self.geometry.board_to_canvas(*neighbor)
                    self.canvas.create_line(
                        origin_x, origin_y, target_x, target_y, fill="#765f3c", width=2
                    )

        for row in range(Board.ROWS):
            for column in range(Board.COLUMNS):
                position = (row, column)
                x, y = self.geometry.board_to_canvas(*position)
                piece = self.state.piece_at(position)
                if position == self.state.active_piece:
                    self.canvas.create_oval(
                        x - 25,
                        y - 25,
                        x + 25,
                        y + 25,
                        outline="#f5b700",
                        width=5,
                    )
                if position == self.selected:
                    self.canvas.create_oval(
                        x - 22,
                        y - 22,
                        x + 22,
                        y + 22,
                        outline="#00a8cc",
                        width=4,
                    )
                if piece == EMPTY:
                    self.canvas.create_oval(
                        x - 4, y - 4, x + 4, y + 4, fill="#5b4930", outline=""
                    )
                else:
                    self.canvas.create_oval(
                        x - 17,
                        y - 17,
                        x + 17,
                        y + 17,
                        fill=PLAYER_COLORS[piece],
                        outline="#f9f4e8",
                        width=2,
                    )

    def on_board_click(self, event: tk.Event) -> None:
        # ============================================================
        # CLIQUES E MOVIMENTOS
        # O primeiro clique guarda apenas uma seleção visual. O segundo chama
        # send_move(). Nenhuma peça muda aqui: a confirmação vem por STATE.
        # ============================================================
        position = self.geometry.canvas_to_board(event.x, event.y)
        if position is None or self.request_pending or self.state.game_over:
            return
        if not self.state.started or self.state.current_player != self.state.player_id:
            self.status_var.set("Aguarde o seu turno.")
            return

        if self.selected is None:
            if self.state.can_select(position):
                self.selected = position
                self.status_var.set("Peça selecionada. Escolha o destino.")
                self.redraw_board()
            else:
                self.status_var.set("Selecione uma peça sua.")
            return

        if position == self.selected:
            if not self.state.capture_sequence:
                self.selected = None
                self.status_var.set("Seleção cancelada.")
                self.redraw_board()
            return
        if self.state.can_select(position) and not self.state.capture_sequence:
            self.selected = position
            self.status_var.set("Nova peça selecionada. Escolha o destino.")
            self.redraw_board()
            return
        if (
            self.state.capture_sequence
            and self.state.piece_at(position) == self.state.player_id
        ):
            self.status_var.set("Continue com a peça destacada em amarelo.")
            return
        self.send_move(self.selected, position)

    def send_move(
        self,
        origin: tuple[int, int],
        destination: tuple[int, int],
        capture: str | None = None,
    ) -> None:
        message: dict[str, Any] = {
            "type": MOVE,
            "from": list(origin),
            "to": list(destination),
        }
        if capture is not None:
            message["capture"] = capture
        self.pending_move = {"type": MOVE, "from": list(origin), "to": list(destination)}
        if self.send(message):
            self.request_pending = True
            self.status_var.set("Jogada enviada; aguardando o servidor...")

    def handle_error(self, message: dict[str, Any]) -> None:
        self.request_pending = False
        code = str(message.get("code", "ERROR"))
        detail = ERROR_MESSAGES.get(code, str(message.get("message", "Erro do servidor")))
        self.status_var.set(detail)
        if code == "CAPTURE_CHOICE_REQUIRED" and self.pending_move is not None:
            self.show_capture_choice()
        elif code == "GAME_FULL":
            messagebox.showerror("Partida lotada", detail, parent=self.root)
            self.return_to_connection_screen()

    def show_capture_choice(self) -> None:
        # O servidor detectou duas capturas possíveis. A GUI não decide a regra:
        # apenas pergunta ao usuário e reenvia o mesmo MOVE com a escolha.
        if self.capture_dialog is not None and self.capture_dialog.winfo_exists():
            return
        dialog = tk.Toplevel(self.root)
        self.capture_dialog = dialog
        dialog.title("Escolha a captura")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=PANEL, padx=24, pady=20)
        tk.Label(
            dialog,
            text="Este movimento permite duas capturas.\nQual deseja realizar?",
            bg=PANEL,
            fg=INK,
            font=("Segoe UI", 10),
            justify="center",
        ).pack(pady=(0, 15))
        buttons = tk.Frame(dialog, bg=PANEL)
        buttons.pack()
        tk.Button(
            buttons,
            text="Aproximação",
            command=lambda: self.resend_capture("approach"),
            bg=ACCENT,
            fg="white",
            relief="flat",
            padx=13,
            pady=7,
        ).pack(side="left", padx=5)
        tk.Button(
            buttons,
            text="Afastamento",
            command=lambda: self.resend_capture("withdrawal"),
            bg="#6c5b7b",
            fg="white",
            relief="flat",
            padx=13,
            pady=7,
        ).pack(side="left", padx=5)
        dialog.protocol("WM_DELETE_WINDOW", self.close_capture_dialog)
        dialog.grab_set()
        dialog.wait_visibility()
        dialog.focus_set()

    def resend_capture(self, capture: str) -> None:
        if self.pending_move is None:
            self.close_capture_dialog()
            return
        message = dict(self.pending_move)
        message["capture"] = capture
        if self.send(message):
            self.request_pending = True
            self.status_var.set("Escolha enviada; aguardando o servidor...")
        self.close_capture_dialog()

    def close_capture_dialog(self) -> None:
        if self.capture_dialog is not None:
            try:
                self.capture_dialog.grab_release()
                self.capture_dialog.destroy()
            except tk.TclError:
                pass
        self.capture_dialog = None

    def send_chat(self) -> None:
        # ============================================================
        # CHAT
        # A GUI envia somente o texto. O servidor acrescenta o player_id oficial
        # e faz broadcast; append_chat() mostra apenas o retorno recebido.
        # ============================================================
        text = self.chat_entry.get().strip()
        if not text:
            return
        if self.send({"type": CHAT, "message": text}):
            self.chat_entry.delete(0, "end")

    def append_chat(self, text: str) -> None:
        if not hasattr(self, "chat_history"):
            return
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", text + "\n")
        self.chat_history.see("end")
        self.chat_history.configure(state="disabled")

    def confirm_give_up(self) -> None:
        # ============================================================
        # DESISTÊNCIA
        # A confirmação envia GIVEUP, mas a GUI não declara o vencedor. Ela
        # aguarda STATE/GAME_OVER produzidos pelo servidor autoritativo.
        # ============================================================
        if not self.state.started or self.state.game_over:
            return
        if messagebox.askyesno(
            "Desistir", "Deseja realmente desistir da partida?", parent=self.root
        ):
            if self.send({"type": GIVEUP}):
                self.status_var.set("Desistência enviada; aguardando o servidor...")
                self.giveup_button.configure(state="disabled")

    def handle_game_over(self, message: dict[str, Any]) -> None:
        # ============================================================
        # GAME OVER
        # Converte vencedor/motivo enviados pelo servidor em texto amigável e
        # desabilita as ações da partida.
        # ============================================================
        self.state.game_over = True
        self.state.winner = message.get("winner")
        self.request_pending = False
        self.close_capture_dialog()
        self.selected = None
        self.redraw_board()
        self.update_labels()
        self.disable_game_actions()
        if self.game_over_announced:
            return
        self.game_over_announced = True

        won = self.state.winner == self.state.player_id
        title = "Você venceu!" if won else "Você perdeu."
        reason = message.get("reason")
        if reason == "give_up":
            detail = "O adversário desistiu." if won else "Você desistiu."
        elif reason == "disconnect":
            detail = "O adversário desconectou." if won else "Conexão encerrada."
        elif reason == "no_pieces":
            detail = "Todas as peças do perdedor foram capturadas."
        else:
            detail = "A partida foi encerrada."
        self.status_var.set(f"{title} {detail}")
        messagebox.showinfo("Fim de jogo", f"{title}\n\n{detail}", parent=self.root)

    def disable_game_actions(self) -> None:
        if hasattr(self, "giveup_button"):
            self.giveup_button.configure(state="disabled")
        if hasattr(self, "chat_entry"):
            self.chat_entry.configure(state="disabled")
            self.chat_button.configure(state="disabled")

    def send(self, message: dict[str, Any]) -> bool:
        if self.connection is None:
            self.status_var.set("Sem conexão com o servidor.")
            return False
        try:
            self.connection.send(message)
            return True
        except (ConnectionError, OSError) as exc:
            self.status_var.set(f"Falha ao enviar: {exc}")
            return False

    def return_to_connection_screen(self) -> None:
        if self.connection is not None:
            self.connection.close()
        self.connection = None
        self.state = ClientGameState()
        self.selected = None
        self.pending_move = None
        self.request_pending = False
        self.game_over_announced = False
        self.status_var.set("Informe o servidor para tentar novamente.")
        self.build_connection_screen()

    def close(self) -> None:
        # ============================================================
        # ENCERRAMENTO
        # Chamado pelo WM_DELETE_WINDOW: fecha o socket antes de destruir Tkinter.
        # As threads são daemon e o fechamento desbloqueia recv().
        # ============================================================
        if self.closing:
            return
        self.closing = True
        self.close_capture_dialog()
        if self.connection is not None:
            self.connection.close()
        self.root.destroy()


def main() -> None:
    # ============================================================
    # MAIN DO CLIENTE GRÁFICO
    # python -m client.gui
    #        -> main()
    #        -> tk.Tk()
    #        -> FanoronaGUI(root)
    #        -> root.mainloop()
    # ============================================================
    root = tk.Tk()
    FanoronaGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
