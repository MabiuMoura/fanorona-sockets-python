# Fanorona distribuído com Pyro5 (RMI/RPC)

Projeto de Programação Paralela e Distribuída para dois jogadores. As regras
continuam centralizadas no servidor: tabuleiro 5x9, turnos, capturas por
aproximação/afastamento, sequências, chat, desistência e vencedor.

## Arquitetura

O Projeto 1 usava TCP e mensagens JSON com um campo `type`. Nesta versão não
há protocolo de aplicação nem interpretação de comandos: o daemon Pyro5 expõe
um único objeto remoto, `FanoronaRemoteGame`, e os clientes invocam seus
métodos diretamente. A GUI mantém o Tkinter na thread principal; chamadas e
consultas periódicas RPC rodam em threads auxiliares e seus resultados chegam
por uma fila local thread-safe.

`game/board.py` e `server/game_session.py` foram reaproveitados integralmente
como regras e estado autoritativo. `server/server.py` hospeda o objeto remoto;
`client/connection.py` contém o proxy Pyro5; `client/gui.py` preserva a
interface visual.

## Interface remota

- `registrar_jogador(nome)`: atribui Player 1/2 e inicia ao entrar o segundo.
- `iniciar_partida()`: tentativa idempotente de início.
- `mover(token, origem, destino, tipo_captura=None)`: valida e aplica jogada.
- `obter_estado()`: estado oficial serializável do tabuleiro e turno.
- `enviar_mensagem(token, mensagem)` e `obter_mensagens(depois_de=0)`: chat.
- `desistir(token)`: encerra por desistência.
- `desconectar(token)`: remove jogador e encerra partida em curso.

Métodos que podem ser rejeitados retornam `{ok: false, code, message}`; ações
aceitas retornam `{ok: true, state}` quando alteram a partida.

`registrar_jogador` devolve um token aleatório somente ao respectivo cliente.
Operações que alteram identidade/estado validam esse token no servidor; ele não
é incluído no tabuleiro, chat ou estado compartilhado. Todo estado contém uma
`revision` monotônica, e o cliente descarta respostas RPC mais antigas.

## Instalação e execução

Requer Python 3.10+ e Tkinter.

```bash
python -m pip install -r requirements.txt
python -m server.server --host 0.0.0.0 --port 5000
```

Em dois terminais, abra os clientes gráficos:

```bash
python -m client.gui
```

Na mesma máquina, informe `127.0.0.1` e porta `5000`. Em máquinas distintas,
informe nos dois clientes o IP local da máquina servidora e libere a porta
5000 no firewall. O host `0.0.0.0` permite conexões pela rede local.

Há também um cliente terminal:

```bash
python -m client.client --host IP_DO_SERVIDOR --port 5000
```

Use `/move r1 c1 r2 c2 [approach|withdrawal]`, texto (ou `/chat texto`),
`/giveup` e `/quit`.

## Testes

```bash
python -m unittest discover -v
```

A suíte cobre as regras puras, registro de dois jogadores, início, jogadas,
controle de turno, chat, desistência, erros e sincronização do estado remoto.
