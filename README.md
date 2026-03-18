# Chat P2P UDP (CLI)

Aplicação de mensageria P2P em **Python + UDP**, sem GUI, feita para ser menor, mais enxuta e fácil de explicar.

## Estrutura

```text
Chat_udp/
├── chat_network.py   # Camada de rede UDP
└── chat_gui.py       # Aplicação CLI (nome mantido por compatibilidade)
```

## Requisitos atendidos do trabalho

- **Protocolo UDP obrigatório**: `socket.SOCK_DGRAM`
- **Concorrência**: thread de escuta + input da CLI em paralelo
- **Estrutura da mensagem**:
  - timestamp
  - remetente (nome/ip/porta)
  - destinatário final (nome/ip/porta)
  - conteúdo
  - status de encaminhamento (`encaminhado`, `encaminhado_por`)
- **Conversa separada por vizinho/remetente**
- **Encaminhamento para terceiro nó**

## Execução

Formato:

```bash
python3 chat_gui.py <nome> <ip> <porta> <viz1_nome> <viz1_ip> <viz1_porta> [<viz2_nome> <viz2_ip> <viz2_porta> ...]
```

Exemplo com 3 nós:

```bash
# Terminal 1
python3 chat_gui.py No_A 192.168.1.10 5001 No_B 192.168.1.11 5002

# Terminal 2
python3 chat_gui.py No_B 192.168.1.11 5002 No_A 192.168.1.10 5001 No_C 192.168.1.12 5003

# Terminal 3
python3 chat_gui.py No_C 192.168.1.12 5003 No_B 192.168.1.11 5002
```

## Comandos da CLI

- `/ajuda`
- `/conversas`
- `/abrir <nome>`
- `/historico`
- `/enviar <texto>`
- `/encaminhar <indice> <destino>`
- `/sair`

Também pode digitar texto direto (sem comando), equivalente a `/enviar <texto>`.

## Como demonstrar o encaminhamento (critério D)

1. Bob envia mensagem para Alice.
2. Alice abre a conversa com Bob e usa `/historico`.
3. Alice escolhe o índice da mensagem e executa:

```bash
/encaminhar <indice> Charlie
```

4. Charlie recebe no formato:
   - `Encaminhado por Alice: [mensagem original de Bob]`

## Observações

- Não existe servidor central.
- Cada instância é um nó independente.
