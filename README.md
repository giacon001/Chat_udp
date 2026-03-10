# ◈ P2P UDP Chat — Sistema de Mensageria Peer-to-Peer

Sistema de chat descentralizado com interface gráfica, construído em Python puro (sem dependências externas). Utiliza o protocolo **UDP** para comunicação direta entre nós em uma rede local ou via localhost.

---

## Visão Geral

Cada instância do programa representa um **nó** na rede P2P. Os nós se comunicam diretamente entre si via sockets UDP, sem servidor central. A topologia é definida pelos vizinhos informados na linha de comando.

```
  Nó_A ◄──────► Nó_B ◄──────► Nó_C
  :5001          :5002          :5003
```

Nó_A conhece Nó_B, Nó_B conhece Nó_A e Nó_C, Nó_C conhece Nó_B. Mensagens podem ser **encaminhadas** entre nós que não são vizinhos diretos.

---

## Funcionalidades

### 1. Envio de Mensagens (UDP)
- Mensagens são enviadas via **UDP** (fire-and-forget, sem conexão).
- Cada mensagem carrega: timestamp, remetente (nome/IP/porta), destinatário (nome/IP/porta) e conteúdo.
- O envio é instantâneo — basta digitar o texto e pressionar **Enter** ou clicar em **ENVIAR**.

### 2. Recebimento em Tempo Real
- Uma **thread de escuta** roda em background, aguardando datagramas UDP na porta configurada.
- Mensagens recebidas aparecem automaticamente na conversa ativa, sem necessidade de atualizar manualmente.
- Mensagens de conversas inativas geram um **badge de notificação** na sidebar.

### 3. Encaminhamento de Mensagens
- Permite **reencaminhar** uma mensagem recebida para outro vizinho.
- O destinatário vê quem é o **autor original** e quem **encaminhou**.
- Para encaminhar:
  - Pressione **F** (com o campo de texto vazio) ou clique em **↩ ENCAMINHAR**.
  - Selecione a mensagem na lista.
  - Escolha o vizinho de destino.
  - Clique em **CONFIRMAR**.

### 4. Múltiplas Conversas
- A **sidebar** lateral lista todos os vizinhos configurados.
- Clique em um vizinho para alternar entre conversas.
- Cada conversa mantém seu próprio **histórico** (até 300 mensagens).

### 5. Interface Gráfica (Tkinter)
- Tema **Cyberpunk** escuro com acentos neon (ciano/violeta/verde).
- Balões de mensagem coloridos por tipo:
  - **Verde** — mensagens enviadas por você.
  - **Azul** — mensagens recebidas diretamente.
  - **Âmbar** — mensagens encaminhadas recebidas.
  - **Violeta** — confirmação de encaminhamento enviado.
- Barra de status inferior com feedback de ações e contador de pacotes recebidos.

---

## Estrutura da Mensagem (JSON via UDP)

```json
{
  "timestamp": "2026-03-05T14:30:00",
  "remetente_nome": "No_A",
  "remetente_ip": "127.0.0.1",
  "remetente_porta": 5001,
  "dest_nome": "No_B",
  "dest_ip": "127.0.0.1",
  "dest_porta": 5002,
  "conteudo": "Olá!",
  "encaminhado": false,
  "encaminhado_por": null
}
```

---

## Como Executar

### Teste local (3 terminais no mesmo computador)

**Terminal 1 — Nó A** (conhece B):
```bash
python chat_gui.py No_A 127.0.0.1 5001  No_B 127.0.0.1 5002
```

**Terminal 2 — Nó B** (conhece A e C):
```bash
python chat_gui.py No_B 127.0.0.1 5002  No_A 127.0.0.1 5001  No_C 127.0.0.1 5003
```

**Terminal 3 — Nó C** (conhece B):
```bash
python chat_gui.py No_C 127.0.0.1 5003  No_B 127.0.0.1 5002
```

### Em rede local (um computador por nó)

```bash
# Computador A (IP 192.168.1.10)
python chat_gui.py No_A 192.168.1.10 5001  No_B 192.168.1.11 5002

# Computador B (IP 192.168.1.11)
python chat_gui.py No_B 192.168.1.11 5002  No_A 192.168.1.10 5001  No_C 192.168.1.12 5003

# Computador C (IP 192.168.1.12)
python chat_gui.py No_C 192.168.1.12 5003  No_B 192.168.1.11 5002
```

---

## Atalhos de Teclado

| Tecla   | Ação                                        |
|---------|---------------------------------------------|
| `Enter` | Enviar mensagem                             |
| `F`     | Abrir diálogo de encaminhamento (campo vazio)|
| `Esc`   | Cancelar modo de encaminhamento             |

---

## Requisitos

- **Python 3.7+**
- **Tkinter** (incluso na instalação padrão do Python no Windows e macOS; no Linux pode ser necessário instalar via `sudo apt install python3-tk`)
- Nenhuma dependência externa — apenas bibliotecas padrão do Python.

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│                    ChatApp (Tkinter)                     │
│  ┌──────────┐  ┌─────────────────────────────────────┐  │
│  │ Sidebar  │  │         Painel de Chat               │  │
│  │ Vizinhos │  │  ┌─────────────────────────────┐    │  │
│  │          │  │  │   Balões de Mensagem        │    │  │
│  │  [No_A]  │  │  │   (Canvas scrollável)       │    │  │
│  │  [No_B]  │  │  ├─────────────────────────────┤    │  │
│  │  [No_C]  │  │  │   Input + Enviar + Fwd      │    │  │
│  └──────────┘  │  └─────────────────────────────┘    │  │
│                └─────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                 Classe No (Rede P2P)                     │
│  Socket UDP ◄──► Thread de Escuta ◄──► Histórico (Lock) │
└──────────────────────────────────────────────────────────┘
```

| Camada         | Responsabilidade                                    |
|----------------|-----------------------------------------------------|
| `Mensagem`     | Estrutura de dados + serialização JSON               |
| `Vizinho`      | Endereçamento de um nó vizinho (nome, IP, porta)     |
| `No`           | Socket UDP, envio, escuta, encaminhamento, histórico |
| `ChatApp`      | Interface gráfica, eventos, renderização             |
