# Fanorona distribuído com Python e sockets TCP

Projeto acadêmico para dois jogadores. Cada cliente usa uma conexão TCP com
um servidor central, que mantém o tabuleiro, valida as jogadas e distribui o
mesmo estado oficial aos participantes.

## Funcionalidades

- TCP IPv4 com JSON Lines em UTF-8;
- duas threads de atendimento no servidor e estado protegido por locks;
- exatamente dois jogadores e rejeição de excedentes com `GAME_FULL`;
- chat bidirecional com identidade atribuída pelo servidor;
- tabuleiro tradicional 5x9 e suas conexões reais;
- movimentos simples, capturas por aproximação e afastamento;
- escolha explícita quando as duas capturas são possíveis;
- sequência obrigatória com a mesma peça, sem revisitar uma posição;
- vitória por eliminação, desistência ou desconexão;
- sincronização por `START` e `STATE` autoritativos;
- interface Tkinter com conexão configurável, Canvas, chat e status;
- cliente alternativo de terminal e testes com sockets reais.

## Decisões de regras

A especificação exige aproximação, afastamento, sequência com a mesma peça
e proíbe revisitar posições. Duas regras encontradas em variantes tradicionais
não estão explicitadas no enunciado e, por isso, **não foram adicionadas**:

1. captura globalmente obrigatória: fora de uma sequência, um movimento simples
   continua permitido mesmo que outra peça possa capturar;
2. proibição de repetir a direção numa sequência: somente a proibição de
   revisitar uma posição é aplicada.

Depois que uma captura inicia uma sequência, sua continuação é obrigatória
enquanto a mesma peça possuir uma captura válida. Não existe comando para
encerrar voluntariamente a sequência. A vitória de tabuleiro ocorre quando uma
captura remove a última peça adversária; não foi criada uma regra adicional de
vitória por imobilização, pois ela não aparece no documento.

## Requisitos

- Python 3.10 ou mais recente;
- Tkinter 8.6 ou compatível (normalmente incluído no Python);
- nenhuma dependência externa instalada por `pip`.

Execute todos os comandos na raiz do projeto.

## Executar servidor e clientes gráficos

Servidor:

```bash
python -m server.server
```

Em dois terminais diferentes, abra uma interface para cada jogador:

```bash
python -m client.gui
```

Em cada tela, mantenha `127.0.0.1` e `5000` e clique em **Conectar**. O primeiro
cliente será o Player 1 e o segundo será o Player 2.

Para usar máquinas distintas, execute no PC servidor:

```bash
python -m server.server --host 0.0.0.0 --port 5000
```

Libere a porta TCP 5000 no firewall quando necessário. Nos dois PCs jogadores,
execute `python -m client.gui`, informe o IP do servidor no campo **Servidor** e
mantenha a porta 5000. O protocolo não depende de `localhost`.

## Como jogar na interface

- Player 1 usa peças azuis; Player 2 usa peças vermelhas.
- Um anel azul-claro marca a seleção local.
- Um anel amarelo marca a peça obrigatória numa sequência.
- Clique numa peça sua e depois no destino. O Canvas só muda quando o servidor
  responder com `STATE`.
- Se aproximação e afastamento forem possíveis, escolha uma das opções na
  janela apresentada depois da resposta do servidor.
- Digite no campo de chat e use **Enviar** ou Enter.
- Use **Desistir** e confirme para enviar `GIVEUP`; a GUI aguarda `GAME_OVER`.

O painel lateral informa identificação, turno, erros e sequências. Depois de
`GAME_OVER`, movimentos, chat e desistência são desabilitados.

## Cliente de terminal opcional

O cliente anterior foi preservado para depuração:

```bash
python -m client.client --host 127.0.0.1 --port 5000
```

## Comandos do cliente

```text
Uma mensagem comum no terminal          envia CHAT
/chat Olá                               envia CHAT
/move 2 3 2 4                           move sem escolha de captura
/move 2 3 2 4 approach                  escolhe aproximação
/move 2 3 2 4 withdrawal                escolhe afastamento
/giveup                                 desiste da partida
/quit                                   fecha a conexão
```

Na abertura padrão, a jogada `(2,3) -> (2,4)` oferece os dois tipos de captura.
Portanto, o Player 1 deve usar `approach` ou `withdrawal` nesse movimento.

## Capturas

Para o vetor do movimento `origem -> destino`:

- aproximação examina os pontos depois do destino, no mesmo sentido;
- afastamento examina os pontos atrás da origem, no sentido oposto;
- somente uma linha contínua de adversários conectada no tabuleiro é removida;
- quando apenas uma forma existe, o servidor a escolhe automaticamente;
- quando ambas existem, omitir `capture` produz `CAPTURE_CHOICE_REQUIRED`;
- escolher uma forma inexistente produz `INVALID_CAPTURE`.

Durante uma sequência, `current_player` não muda. `active_piece` indica a peça
que deve continuar. Um movimento com outra peça, sem captura ou para uma
posição visitada é recusado. Quando não há nova captura, a sequência termina e
o turno passa ao adversário.

## Protocolo JSON Lines

Cada mensagem é um objeto JSON terminado por `\n`. Um buffer persistente trata
mensagens fragmentadas ou agrupadas pelo TCP. Uma linha inválida gera
`INVALID_MESSAGE` sem bloquear linhas válidas seguintes.

### Solicitações do cliente

```json
{"type":"CHAT","message":"Olá"}
```

```json
{"type":"MOVE","from":[2,3],"to":[2,4],"capture":"approach"}
```

```json
{"type":"GIVEUP"}
```

O servidor ignora campos `player` enviados nessas mensagens e utiliza o
`player_id` associado ao socket.

### Eventos do servidor

```json
{"type":"CHAT","player":1,"message":"Olá"}
```

```json
{
  "type":"STATE",
  "board":[[2,2,2,2,2,2,2,2,2]],
  "current_player":1,
  "game_over":false,
  "winner":null,
  "capture_sequence":true,
  "active_piece":[2,4]
}
```

O `board` acima foi abreviado para tornar o exemplo legível; mensagens reais
sempre contêm as cinco linhas de nove posições.

```json
{"type":"GAME_OVER","winner":2,"reason":"give_up"}
```

Motivos de encerramento: `no_pieces`, `give_up` e `disconnect`.

Exemplos de erros:

```json
{"type":"ERROR","code":"CAPTURE_CHOICE_REQUIRED","message":"Escolha captura por aproximação ou afastamento"}
```

```json
{"type":"ERROR","code":"POSITION_ALREADY_VISITED","message":"Uma posição da sequência não pode ser revisitada"}
```

Tipos implementados: `HELLO`, `CONNECTED`, `ASSIGN_PLAYER`, `START`, `CHAT`,
`MOVE`, `STATE`, `GIVEUP`, `GAME_OVER`, `ERROR` e `DISCONNECT`. O turno é
transportado em `START`/`STATE`; não há um evento `TURN` redundante.

## Arquitetura

```text
Tkinter (thread principal)
        |
   root.after(50)
        |
   queue.Queue <--- thread receptora <--- socket TCP
                                              |
Tkinter do outro jogador ------------------ Servidor
                                              |
                                      GameSession -- Board
```

- `common/protocol.py`: serialização e reconstrução JSON Lines;
- `game/board.py`: topologia, movimentos e cálculo das capturas;
- `server/game_session.py`: turno, sequência, vencedor e estado oficial;
- `server/server.py`: conexões, validação das mensagens e broadcasts;
- `server/client_handler.py`: thread receptora de cada cliente;
- `client/connection.py`: socket, thread de rede e fila de eventos;
- `client/gui_model.py`: estado visual e conversões de coordenadas puras;
- `client/gui.py`: telas Tkinter e consumo da fila com `root.after()`;
- `client/client.py`: cliente alternativo de terminal;
- `tests/`: testes unitários e integração com sockets reais.

A thread receptora nunca acessa widgets. Ela coloca dicionários na
`queue.Queue` de `ServerConnection`; a thread principal consulta essa fila a
cada 50 ms e chama o tratador correspondente. `START` e `STATE` alimentam uma
única função de atualização e redesenho.

## Testes

```bash
python -m unittest discover -v
```

A suíte cobre protocolo, topologia, movimentos, aproximação, afastamento,
captura múltipla, escolha simultânea, sequências, restrições da peça ativa,
posições visitadas, turno, vitória, desistência, desconexão, chat e
sincronização entre dois sockets reais.
Funções puras da GUI também são testadas: conversão Canvas/tabuleiro, rejeição
de cliques distantes, cópia centralizada de `STATE`, turno e peça ativa.
