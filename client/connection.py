"""Cliente Pyro5: chamadas RPC em threads, eventos locais para a interface."""
from __future__ import annotations
import queue
import threading
from typing import Any, Callable
import Pyro5.api

class ServerConnection:
    """Proxy Pyro5 por thread; Tkinter consome somente ``events`` na thread principal."""
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.player_id: int | None = None
        self.session_token: str | None = None
        self._closed = threading.Event()
        self._last_message = 0
        self._last_state: dict | None = None
        self._last_revision = -1
        self._started_seen = False
        self._state_lock = threading.Lock()

    def _proxy(self) -> Pyro5.api.Proxy:
        return Pyro5.api.Proxy(f"PYRO:fanorona@{self.host}:{self.port}")

    def connect(self, timeout: float = 5.0) -> None:
        proxy = self._proxy()
        proxy._pyroTimeout = timeout
        reply = proxy.registrar_jogador("")
        proxy._pyroRelease()
        if not reply.get("ok"):
            raise ConnectionError(reply.get("message", "Não foi possível registrar jogador"))
        self.player_id = reply["player"]
        self.session_token = reply["token"]
        self.events.put({"type": "CONNECTED"})
        self.events.put({"type": "ASSIGN_PLAYER", "player": self.player_id})
        self._emit_state(reply["state"])
        threading.Thread(target=self._poll_loop, daemon=True, name="pyro-poll").start()

    def _emit_state(self, state: dict) -> None:
        # A resposta de uma ação e o polling podem chegar simultaneamente.
        # Só uma delas deve publicar cada transição de estado na fila da GUI.
        with self._state_lock:
            revision = state.get("revision")
            if not isinstance(revision, int):
                self.events.put({"type": "CONNECTION_ERROR", "message": "Estado remoto sem revisão válida"})
                return
            if revision <= self._last_revision:
                return
            self._last_state = state
            self._last_revision = revision
            started_now = bool(state.get("game_started")) and not self._started_seen
            self._started_seen = self._started_seen or bool(state.get("game_started"))
        self.events.put({"type": "START" if started_now else "STATE", **state})

    def _poll_loop(self) -> None:
        try:
            while not self._closed.is_set():
                proxy = self._proxy(); proxy._pyroTimeout = 2
                self._emit_state(proxy.obter_estado())
                for message in proxy.obter_mensagens(self._last_message):
                    self._last_message = max(self._last_message, message["id"])
                    self.events.put({"type": "CHAT", **message})
                proxy._pyroRelease()
                self._closed.wait(0.15)
        except Exception as exc:
            if not self._closed.is_set(): self.events.put({"type": "CONNECTION_ERROR", "message": str(exc)})

    def _invoke_async(
        self, operation: str, invoke: Callable[[Pyro5.api.Proxy], dict]
    ) -> None:
        """Executa uma chamada RPC explícita fora da thread do Tkinter."""
        def worker() -> None:
            try:
                proxy = self._proxy(); proxy._pyroTimeout = 5
                reply = invoke(proxy)
                proxy._pyroRelease()
                if not reply.get("ok"): self.events.put({"type": "ERROR", **reply})
                elif reply.get("state") is not None: self._emit_state(reply["state"])
            except Exception as exc:
                self.events.put({"type": "CONNECTION_ERROR", "message": str(exc)})
        threading.Thread(target=worker, daemon=True, name=f"pyro-{operation}").start()

    def move(self, origin: object, destination: object, capture: object = None) -> None:
        if self.session_token is None: raise ConnectionError("Cliente não está conectado")
        token = self.session_token
        self._invoke_async("mover", lambda proxy: proxy.mover(token, origin, destination, capture))
    def send_chat(self, message: str) -> None:
        if self.session_token is None: raise ConnectionError("Cliente não está conectado")
        token = self.session_token
        self._invoke_async("enviar_mensagem", lambda proxy: proxy.enviar_mensagem(token, message))
    def give_up(self) -> None:
        if self.session_token is None: raise ConnectionError("Cliente não está conectado")
        token = self.session_token
        self._invoke_async("desistir", lambda proxy: proxy.desistir(token))
    def close(self) -> None:
        if self._closed.is_set(): return
        self._closed.set()
        if self.session_token is not None:
            try:
                proxy = self._proxy(); proxy._pyroTimeout = 1
                proxy.desconectar(self.session_token); proxy._pyroRelease()
            except Exception: pass
