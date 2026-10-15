"""Cliente de terminal que invoca diretamente os métodos remotos Pyro5."""
from __future__ import annotations
import argparse
from client.connection import ServerConnection

def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente Pyro5 do Fanorona")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    connection = ServerConnection(args.host, args.port)
    try:
        connection.connect()
        print(f"Conectado como Player {connection.player_id}. /move r1 c1 r2 c2 [approach|withdrawal], /giveup, /quit")
        while True:
            command = input("> ").strip()
            if command == "/quit": break
            if command == "/giveup": connection.give_up(); continue
            if command.startswith("/move "):
                parts = command.split()
                if len(parts) not in (5, 6): print("Uso: /move r1 c1 r2 c2 [approach|withdrawal]"); continue
                try: values = [int(value) for value in parts[1:5]]
                except ValueError: print("Coordenadas devem ser inteiras."); continue
                connection.move(values[:2], values[2:], parts[5] if len(parts) == 6 else None); continue
            connection.send_chat(command.removeprefix("/chat "))
    finally: connection.close()

if __name__ == "__main__": main()
