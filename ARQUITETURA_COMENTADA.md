# Como ler este projeto

Este guia mostra onde cada responsabilidade está no código e como os módulos
se comunicam. A ideia principal é separar quatro assuntos:

1. interface do usuário;
2. comunicação TCP;
3. estado autoritativo da partida;
4. regras puras do Fanorona.

## Ordem recomendada de leitura

1. `server/server.py` — veja o processo principal e a coordenação geral;
2. `client/connection.py` — entenda como o cliente conecta, envia e recebe;
3. `common/protocol.py` — entenda como dicionários viram bytes e voltam;
4. `server/client_handler.py` — veja uma thread atendendo cada jogador;
5. `server/game_session.py` — estude o estado oficial, turno e sequências;
6. `game/board.py` — aprofunde-se na geometria, movimento e capturas;
7. `client/gui_model.py` — veja a cópia visual e as coordenadas do Canvas;
8. `client/gui.py` — por fim, acompanhe os cliques e a atualização da tela.

Essa ordem começa pela visão distribuída e só depois entra nos detalhes das
regras e dos widgets. Para estudar primeiro a experiência do usuário, também é
possível ler `client/gui.py` antes de `game/board.py`.

## Quem faz o quê

| Componente | Papel |
|---|---|
| `client/gui.py` | Mostra a interface e recebe ações do usuário. |
| `client/gui_model.py` | Mantém a cópia visual e converte coordenadas. |
| `client/connection.py` | Realiza a comunicação TCP do cliente. |
| `common/protocol.py` | Transforma mensagens em bytes e bytes em mensagens. |
| `server/client_handler.py` | Recebe mensagens de um cliente numa thread. |
| `server/server.py` | Aceita conexões, distribui mensagens e faz broadcasts. |
| `server/game_session.py` | Mantém o estado oficial da partida. |
| `game/board.py` | Implementa tabuleiro, conexões, movimentos e capturas. |

## Mapa de execução do servidor

Comando:

```bash
python -m server.server
```

Fluxo real:

```text
main()
  ↓
FanoronaServer(host, port)
  ↓
serve_forever()
  ↓
socket.socket(AF_INET, SOCK_STREAM)
  ↓
bind()
  ↓
listen()
  ↓
accept()
  ↓
_register_client()
  ↓
ClientHandler(...)
  ↓
ClientHandler.start()
  ↓
ClientHandler.run()
```

`accept()` devolve um novo socket para conversar exclusivamente com aquele
cliente. O socket criado em `serve_forever()` continua sendo usado para aceitar
outras conexões.

O primeiro jogador recebe `player_id = 1`; o segundo recebe `player_id = 2`.
Quando `GameSession.try_start()` encontra os dois, o servidor transmite `START`
com o tabuleiro e o turno inicial.

## Mapa de execução do cliente gráfico

Comando:

```bash
python -m client.gui
```

Fluxo real:

```text
main()
  ↓
tk.Tk()
  ↓
FanoronaGUI(root)
  ↓
build_connection_screen()
  ↓
root.mainloop()
```

Depois que o usuário clica em **Conectar**:

```text
start_connection()
  ↓
thread _connection_worker()
  ↓
ServerConnection(host, port)
  ↓
ServerConnection.connect()
  ↓
socket.socket(AF_INET, SOCK_STREAM)
  ↓
socket.connect((host, port))
  ↓
thread ServerConnection._receive_loop()
```

O `connect()` ocorre fora da thread Tkinter porque pode demorar. Depois da
conexão, `_receive_loop()` fica responsável pelo `recv()` bloqueante.

## Cliente de terminal

O ponto de entrada alternativo é:

```bash
python -m client.client
```

```text
main()
  ↓
ServerConnection(...)
  ↓
connect()
  ↓
thread show_events()
  +
input() de comandos na thread principal
```

## Caminho dos dados TCP

### Envio

```text
dicionário Python
  ↓
encode_message()
  ↓
json.dumps()
  ↓
texto JSON
  ↓
encode("utf-8")
  ↓
bytes + b"\n"
  ↓
send_message()
  ↓
socket.sendall()
```

### Recebimento

```text
socket.recv(4096)
  ↓
bytes
  ↓
MessageBuffer.feed()
  ↓
linha encerrada por b"\n"
  ↓
_decode_line()
  ↓
decode("utf-8") + json.loads()
  ↓
dicionário Python
```

TCP é um fluxo de bytes. Portanto:

```text
1 sendall() != necessariamente 1 recv()
```

Um `recv()` pode trazer uma parte de uma mensagem ou várias mensagens juntas.
O `MessageBuffer` guarda fragmentos e usa `\n` para reconhecer cada limite.

## Threads do sistema

### Servidor

```text
thread principal: accept()

ClientHandler Player 1: recv() do jogador 1
ClientHandler Player 2: recv() do jogador 2
```

Como cada `ClientHandler` herda de `threading.Thread`, um jogador pode ficar sem
enviar dados sem bloquear a recepção do outro.

`GameSession.lock` é um `threading.RLock` que protege o estado compartilhado.
`FanoronaServer._action_lock` preserva a ordem entre a aplicação de uma ação e
seu broadcast. Cada socket também possui um lock de envio.

### Cliente gráfico

```text
thread principal Tkinter: widgets, Canvas e mainloop()
thread de conexão: executa somente o connect() inicial
thread server-receiver: permanece em recv()
```

Tkinter não é thread-safe. A thread `server-receiver` nunca altera widgets:

```text
thread da rede
  ↓
ServerConnection._receive_loop()
  ↓
events.put(mensagem)
  ↓
queue.Queue
  ↓
root.after(50, process_queues)
  ↓
FanoronaGUI.process_queues()
  ↓
atualização na thread Tkinter
```

Os 50 ms são apenas o intervalo escolhido para consultar a fila; não são um
tempo de rede nem uma regra do jogo.

## Fluxo completo de uma jogada

```text
Usuário
  ↓
FanoronaGUI.on_board_click()
  ↓
FanoronaGUI.send_move()
  ↓
FanoronaGUI.send()
  ↓
ServerConnection.send()
  ↓
send_message()
  ↓
encode_message()
  ↓
socket.sendall()

============ REDE TCP ============

ClientHandler.run()
  ↓
socket.recv()
  ↓
MessageBuffer.feed()
  ↓
FanoronaServer._handle_message()
  ↓
FanoronaServer._handle_move()
  ↓
GameSession.try_move()
  ↓
Board.apply_move()
  ↓
GameSession atualiza sequência, turno ou vencedor
  ↓
FanoronaServer.broadcast(STATE)
  ↓
ClientHandler.send()
  ↓
send_message() / socket.sendall()

============ REDE TCP ============

ServerConnection._receive_loop()
  ↓
socket.recv()
  ↓
MessageBuffer.feed()
  ↓
ServerConnection.events.put()
  ↓
FanoronaGUI.process_queues()
  ↓
FanoronaGUI.handle_network_message()
  ↓
FanoronaGUI.handle_state()
  ↓
ClientGameState.apply_server_state()
  ↓
FanoronaGUI.redraw_board()
```

A seleção da peça é local, mas o tabuleiro não é alterado pelo clique. A
mudança visual definitiva acontece somente depois do `STATE` do servidor.

Se `Board.apply_move()` detectar aproximação e afastamento ao mesmo tempo,
produz `CAPTURE_CHOICE_REQUIRED`. A GUI guarda `pending_move`, abre
`show_capture_choice()` e usa `resend_capture()` para incluir `approach` ou
`withdrawal`.

## Fluxo completo do chat

```text
FanoronaGUI.send_chat()
  ↓
ServerConnection.send()
  ↓
send_message() / TCP
  ↓
ClientHandler.run()
  ↓
FanoronaServer._handle_message()
  ↓
FanoronaServer._handle_chat()
  ↓
FanoronaServer.broadcast()
  ↓
TCP para Player 1 e Player 2
  ↓
ServerConnection._receive_loop()
  ↓
queue.Queue
  ↓
FanoronaGUI.process_queues()
  ↓
FanoronaGUI.handle_network_message()
  ↓
FanoronaGUI.append_chat()
```

O servidor define o campo `player` com `handler.player_id`. Assim, um cliente
não pode assumir a identidade do outro no chat.

## Estado autoritativo

`GameSession` é a fonte de verdade. Ela mantém:

- `players`;
- `board`;
- `current_player`;
- `game_started`;
- `game_over`;
- `winner` e `end_reason`;
- `capture_sequence`.

O método `GameSession.try_move()` valida a partida e o turno, aplica restrições
da sequência, chama `Board.apply_move()` e então decide entre continuar,
alternar o turno ou terminar a partida. `state()` e `_state_unlocked()` produzem
somente listas, números, booleanos e `None`, que podem ser serializados em JSON.

`ClientGameState` não substitui `GameSession`: ele é somente a última cópia
recebida para desenhar a interface.

## Regras no Board

`Board` não importa servidor, socket ou Tkinter. Seus pontos principais são:

- `neighbors()`: representa as conexões reais;
- `get_approach_captures()`: procura depois do destino;
- `get_withdrawal_captures()`: procura atrás da origem;
- `apply_move()`: valida e altera a matriz;
- `has_capture_from()`: verifica se a mesma peça pode continuar;
- `serialize()`: cria a matriz que entra em `START` e `STATE`.

```text
Aproximação:
origem -> destino -> adversários

Afastamento:
adversários <- origem -> destino
```

## Onde olhar para entender...

```text
Quero entender conexão TCP
→ server/server.py + client/connection.py

Quero entender bind, listen e accept
→ FanoronaServer.serve_forever() em server/server.py

Quero entender connect e recv do cliente
→ ServerConnection.connect() e _receive_loop() em client/connection.py

Quero entender envio e delimitação de mensagens
→ common/protocol.py

Quero entender threads do servidor
→ server/client_handler.py

Quero entender estado oficial, turno e vencedor
→ server/game_session.py

Quero entender movimentos e capturas
→ game/board.py

Quero entender atualização do Tkinter
→ process_queues(), handle_network_message() e handle_state() em client/gui.py

Quero entender estado visual
→ client/gui_model.py

Quero entender os comportamentos comprovados pelos testes
→ tests/test_protocol.py, test_board.py, test_game_session.py,
  test_server_integration.py e test_gui_model.py
```

## Resumo para apresentação

Uma explicação curta pode ser:

> Cada jogador executa uma GUI Tkinter e abre uma conexão TCP com o mesmo
> servidor. O cliente envia intenções, como MOVE, CHAT e GIVEUP. Uma thread por
> cliente recebe essas mensagens no servidor. O servidor mantém a GameSession
> autoritativa, usa Board para aplicar as regras e transmite o novo STATE aos
> dois jogadores. No cliente, outra thread recebe a rede e coloca mensagens em
> uma Queue; o root.after faz a thread principal do Tkinter consumir essa fila
> com segurança e redesenhar a interface.
