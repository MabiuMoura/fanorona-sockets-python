"""Cliente de terminal para validar chat e movimentos sem interface gráfica."""

from __future__ import annotations

import argparse
import queue
import threading

from client.connection import ServerConnection
from common.protocol import CHAT, GIVEUP, MOVE


def show_events(connection: ServerConnection, stopped: threading.Event) -> None:
    # O cliente de terminal usa uma thread apenas para imprimir os eventos da
    # fila enquanto a thread principal permanece bloqueada em input().
    while not stopped.is_set():
        try:
            event = connection.events.get(timeout=0.2)
        except queue.Empty:
            continue
        print(f"\nServidor: {event}")
        if event["type"] in {"CONNECTION_CLOSED", "CONNECTION_ERROR"}:
            stopped.set()


def send_command(connection: ServerConnection, command: str) -> bool:
    """Interpreta um comando; retorna False quando o cliente deve encerrar."""
    if command == "/quit":
        return False
    if command == "/giveup":
        connection.send({"type": GIVEUP})
        return True
    if command.startswith("/move "):
        parts = command.split()
        if len(parts) not in (5, 6):
            print("Uso: /move r1 c1 r2 c2 [approach|withdrawal]")
            return True
        try:
            coordinates = [int(value) for value in parts[1:5]]
        except ValueError:
            print("As quatro coordenadas precisam ser números inteiros.")
            return True
        message = {
            "type": MOVE,
            "from": coordinates[:2],
            "to": coordinates[2:],
        }
        if len(parts) == 6:
            if parts[5] not in {"approach", "withdrawal"}:
                print("A captura deve ser approach ou withdrawal.")
                return True
            message["capture"] = parts[5]
        connection.send(message)
        return True
    text = command.removeprefix("/chat ")
    connection.send({"type": CHAT, "message": text})
    return True


def main() -> None:
    # ============================================================
    # MAIN DO CLIENTE DE TERMINAL
    # python -m client.client
    #        -> main()
    #        -> ServerConnection(...)
    #        -> connect()
    #        -> thread show_events() + leitura de comandos
    # ============================================================
    parser = argparse.ArgumentParser(description="Cliente TCP do Fanorona")
    parser.add_argument("--host", default="127.0.0.1", help="IP do servidor")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    connection = ServerConnection(args.host, args.port)
    stopped = threading.Event()
    print(f"Conectando a {args.host}:{args.port}...")
    try:
        connection.connect()
        threading.Thread(
            target=show_events, args=(connection, stopped), daemon=True
        ).start()
        print(
            "Digite texto para conversar, /move r1 c1 r2 c2 [capture], "
            "/giveup ou /quit."
        )
        while not stopped.is_set():
            try:
                command = input("> ").strip()
            except EOFError:
                break
            if not send_command(connection, command):
                break
    except (ConnectionError, OSError) as exc:
        print(f"Falha de conexão: {exc}")
    except KeyboardInterrupt:
        print("Encerrando cliente...")
    finally:
        stopped.set()
        connection.close()


if __name__ == "__main__":
    main()
