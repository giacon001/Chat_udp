
"""
=============================================================================
SISTEMA DE MENSAGERIA P2P — PROTOCOLO UDP  |  Interface Gráfica (Tkinter)
=============================================================================
COMO INICIAR (um comando por computador):

  Computador A:
    python3 chat_gui.py No_A 192.168.1.10 5001  No_B 192.168.1.11 5002

  Computador B:
    python3 chat_gui.py No_B 192.168.1.11 5002  No_A 192.168.1.10 5001  No_C 192.168.1.12 5003

  Computador C:
    python3 chat_gui.py No_C 192.168.1.12 5003  No_B 192.168.1.11 5002

Em localhost (teste local, 3 terminais):
  python3 chat_gui.py No_A 127.0.0.1 5001  No_B 127.0.0.1 5002
  python3 chat_gui.py No_B 127.0.0.1 5002  No_A 127.0.0.1 5001  No_C 127.0.0.1 5003
  python3 chat_gui.py No_C 127.0.0.1 5003  No_B 127.0.0.1 5002
=============================================================================
"""

# ── Biblioteca padrão Python (sem instalação necessária) ──────────────────────
import socket           # UDP: AF_INET + SOCK_DGRAM
import threading        # Thread de escuta concorrente + Lock thread-safe
import json             # Serialização/desserialização dos pacotes
import sys              # sys.argv (argumentos da linha de comando)
import time             # timestamps e delays
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime
from copy import deepcopy

# ── Tkinter (GUI nativa Python — funciona em Windows, macOS e Linux) ─────────
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont


# =============================================================================
# PALETA E CONSTANTES VISUAIS
# =============================================================================
# Tema: Terminal Cyberpunk — escuro com acentos neon ciano/violeta
# Funciona em qualquer resolução e não exige fontes externas

C = {
    "bg_deep":    "#080c10",   # fundo principal (quase preto azulado)
    "bg_panel":   "#0d1117",   # painel de chat
    "bg_input":   "#161b22",   # campo de digitação
    "bg_bubble_me":    "#0a2a4a",  # balão mensagem própria (azul escuro)
    "bg_bubble_other": "#141f2e",  # balão mensagem recebida
    "bg_bubble_fwd":   "#1a1a0a",  # balão encaminhamento (amarelado escuro)
    "bg_header":  "#0d1117",
    "bg_sidebar": "#0d1117",
    "accent":     "#00d4ff",   # ciano neon (cor principal de destaque)
    "accent2":    "#7c3aed",   # violeta (botão encaminhar)
    "accent3":    "#10b981",   # verde esmeralda (mensagens enviadas)
    "accent4":    "#f59e0b",   # âmbar (encaminhamento)
    "text_pri":   "#e6edf3",   # texto principal (quase branco)
    "text_sec":   "#8b949e",   # texto secundário (cinza)
    "text_faint": "#3d444d",   # texto apagado (separadores)
    "border":     "#21262d",   # bordas sutis
    "online":     "#3fb950",   # verde status online
    "danger":     "#f85149",   # vermelho erro
}

FONT_MONO  = ("Consolas", 11)          # Windows/Linux
FONT_MONO2 = ("Courier New", 11)       # fallback universal
FONT_BOLD  = ("Consolas", 12, "bold")
FONT_SMALL = ("Consolas", 9)
FONT_TITLE = ("Consolas", 14, "bold")
FONT_NANO  = ("Consolas", 8)


# =============================================================================
# SEÇÃO 1 — ESTRUTURA DA MENSAGEM (Requisito C)
# =============================================================================

@dataclass
class Mensagem:
    """
    Pacote de dados trafegado via UDP.

    Todos os campos exigidos pelo enunciado estão presentes:
      timestamp        — data/hora ISO do envio
      remetente_nome   — identificador do nó de origem
      remetente_ip     — IP do nó de origem
      remetente_porta  — porta UDP do nó de origem
      dest_nome        — nome do destinatário FINAL
      dest_ip / porta  — endereço do destinatário final
      conteudo         — texto da mensagem
      encaminhado      — flag: False=original, True=repassada (Requisito C)
      encaminhado_por  — quem repassou (ou None)
    """
    timestamp: str
    remetente_nome: str
    remetente_ip: str
    remetente_porta: int
    dest_nome: str
    dest_ip: str
    dest_porta: int
    conteudo: str
    encaminhado: bool = False
    encaminhado_por: Optional[str] = None

    def serializar(self) -> bytes:
        """
        Mensagem → JSON → bytes para sock.sendto().

        asdict() converte o dataclass em dict Python.
        json.dumps() serializa o dict em string JSON.
        encode('utf-8') transforma em bytes (formato aceito pelo socket).
        """
        return json.dumps(asdict(self), ensure_ascii=False).encode('utf-8')

    @staticmethod
    def desserializar(dados: bytes) -> 'Mensagem':
        """
        bytes recebidos pelo socket → objeto Mensagem.

        decode() converte bytes em string JSON.
        json.loads() transforma em dict Python.
        Mensagem(**d) usa o dict como argumentos nomeados pro __init__.
        """
        d = json.loads(dados.decode('utf-8'))
        return Mensagem(**d)

    def hora(self) -> str:
        """Extrai HH:MM do timestamp ISO."""
        return self.timestamp[11:16]


# =============================================================================
# SEÇÃO 2 — VIZINHO
# =============================================================================

@dataclass
class Vizinho:
    """Endereçamento de um nó vizinho."""
    nome: str
    ip: str
    porta: int

    @property
    def endereco(self) -> tuple:
        """Tupla (ip, porta) usada em sock.sendto()."""
        return (self.ip, self.porta)

    @property
    def label(self) -> str:
        return f"{self.nome}  {self.ip}:{self.porta}"


# =============================================================================
# SEÇÃO 3 — NÓ P2P (camada de rede)
# =============================================================================

class No:
    """
    Instância da rede P2P.

    Cria socket UDP, faz bind, inicia thread de escuta,
    mantém histórico de mensagens por vizinho (thread-safe com Lock).
    """

    def __init__(self, nome: str, ip: str, porta: int, vizinhos: List[Vizinho]):
        self.nome     = nome
        self.ip       = ip
        self.porta    = porta
        self.vizinhos = vizinhos

        # ── Socket UDP ────────────────────────────────────────────────────────
        # AF_INET = IPv4 | SOCK_DGRAM = UDP (sem conexão, sem garantia de entrega)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.ip, self.porta))   # registra nesta porta

        # ── Histórico por vizinho ─────────────────────────────────────────────
        # deque(maxlen=300): fila circular — evita crescimento ilimitado
        self._historico: Dict[str, deque] = {
            v.nome: deque(maxlen=300) for v in vizinhos
        }
        self._brutas: Dict[str, deque] = {
            v.nome: deque(maxlen=50) for v in vizinhos
        }

        # ── Callbacks para a GUI ──────────────────────────────────────────────
        # A thread de escuta chama este callback quando chega mensagem nova,
        # permitindo que a GUI atualize sem polling contínuo.
        self._callback_nova_msg = None

        # ── Lock de exclusão mútua ────────────────────────────────────────────
        # Protege _historico e _brutas de acesso simultâneo por duas threads
        # (thread de escuta e thread da GUI → race condition sem lock).
        self._lock    = threading.Lock()
        self._rodando = True

        # ── Thread de escuta (daemon) ─────────────────────────────────────────
        # daemon=True: encerra junto com o processo principal automaticamente.
        threading.Thread(target=self._loop_escuta, daemon=True,
                         name=f"UDP-{porta}").start()

    # ── ENVIO ─────────────────────────────────────────────────────────────────

    def enviar(self, vizinho: Vizinho, texto: str):
        """
        Cria e envia uma mensagem original via UDP.

        sock.sendto(bytes, endereço):
          Fire-and-forget: envia e retorna imediatamente.
          Sem handshake, sem confirmação (natureza do UDP).
        """
        msg = Mensagem(
            timestamp       = datetime.now().isoformat(timespec='seconds'),
            remetente_nome  = self.nome,
            remetente_ip    = self.ip,
            remetente_porta = self.porta,
            dest_nome       = vizinho.nome,
            dest_ip         = vizinho.ip,
            dest_porta      = vizinho.porta,
            conteudo        = texto,
        )
        self._sock.sendto(msg.serializar(), vizinho.endereco)
        with self._lock:
            self._historico[vizinho.nome].append(
                {"tipo": "eu", "msg": msg}
            )
        if self._callback_nova_msg:
            self._callback_nova_msg(vizinho.nome)

    # ── ENCAMINHAMENTO ────────────────────────────────────────────────────────

    def encaminhar(self, msg_original: Mensagem, destino: Vizinho):
        """
        Encaminha mensagem para outro nó (Requisito D).

        encaminhado=True e encaminhado_por=self.nome marcam a mensagem.
        O remetente_nome ORIGINAL é preservado — o destinatário final
        sabe quem criou E quem repassou a mensagem.
        """
        msg = Mensagem(
            timestamp       = datetime.now().isoformat(timespec='seconds'),
            remetente_nome  = msg_original.remetente_nome,  # autor original!
            remetente_ip    = msg_original.remetente_ip,
            remetente_porta = msg_original.remetente_porta,
            dest_nome       = destino.nome,
            dest_ip         = destino.ip,
            dest_porta      = destino.porta,
            conteudo        = msg_original.conteudo,
            encaminhado     = True,
            encaminhado_por = self.nome,
        )
        self._sock.sendto(msg.serializar(), destino.endereco)
        nota = Mensagem(
            timestamp       = msg.timestamp,
            remetente_nome  = f"↩ {self.nome}",
            remetente_ip    = self.ip,
            remetente_porta = self.porta,
            dest_nome       = destino.nome,
            dest_ip         = destino.ip,
            dest_porta      = destino.porta,
            conteudo        = f'Encaminhei "{msg_original.conteudo[:40]}" → {destino.nome}',
            encaminhado     = True,
            encaminhado_por = self.nome,
        )
        with self._lock:
            if destino.nome not in self._historico:
                self._historico[destino.nome] = deque(maxlen=300)
            self._historico[destino.nome].append({"tipo": "fwd_sent", "msg": nota})
        if self._callback_nova_msg:
            self._callback_nova_msg(destino.nome)

    # ── ESCUTA UDP ────────────────────────────────────────────────────────────

    def _loop_escuta(self):
        """
        Thread separada: escuta continuamente no socket UDP.

        recvfrom(65535) bloqueia até chegar um datagrama.
        65535 = tamanho máximo de payload UDP.
        OSError indica socket fechado → encerra o loop.
        """
        while self._rodando:
            try:
                dados, _ = self._sock.recvfrom(65535)
                msg = Mensagem.desserializar(dados)
                self._processar(msg)
            except OSError:
                break
            except Exception:
                continue

    def _processar(self, msg: Mensagem):
        """
        Armazena mensagem recebida no histórico correto.

        Roteamento:
          encaminhada por vizinho conhecido → conversa daquele vizinho
          remetente direto → conversa do remetente
          origem nova      → cria entrada dinâmica
        """
        with self._lock:
            if (msg.encaminhado and msg.encaminhado_por
                    and msg.encaminhado_por in self._historico):
                chave = msg.encaminhado_por
            elif msg.remetente_nome in self._historico:
                chave = msg.remetente_nome
            else:
                chave = msg.remetente_nome
                self._historico[chave] = deque(maxlen=300)
                self._brutas[chave]    = deque(maxlen=50)

            tipo = "fwd" if msg.encaminhado else "deles"
            self._historico[chave].append({"tipo": tipo, "msg": msg})
            self._brutas[chave].append(deepcopy(msg))

        if self._callback_nova_msg:
            self._callback_nova_msg(chave)

    # ── GETTERS THREAD-SAFE ───────────────────────────────────────────────────

    def get_historico(self, nome: str) -> list:
        """Cópia thread-safe do histórico de um vizinho."""
        with self._lock:
            return list(self._historico.get(nome, []))

    def get_brutas(self, nome: str) -> List[Mensagem]:
        """Cópia thread-safe das mensagens brutas de um vizinho."""
        with self._lock:
            return list(self._brutas.get(nome, []))

    def encerrar(self):
        """Fecha socket → causa OSError no recvfrom → thread encerra."""
        self._rodando = False
        try:
            self._sock.close()
        except OSError:
            pass


# =============================================================================
# SEÇÃO 4 — INTERFACE GRÁFICA (Tkinter)
# =============================================================================

class ChatApp(tk.Tk):
    """
    Janela principal do chat P2P.

    Herda de tk.Tk (janela raiz do Tkinter).
    Cria todos os widgets, configura o tema escuro e
    inicia o polling de mensagens novas via after().

    Layout:
    ┌─────────────────────────────────────────────────────┐
    │  HEADER: logo + info do nó + status online         │
    ├───────────────────┬─────────────────────────────────┤
    │  SIDEBAR          │  PAINEL DE CHAT                 │
    │  lista de vizinhos│  ┌──────────────────────────┐  │
    │  + estatísticas   │  │  cabeçalho conversa      │  │
    │                   │  │  área de mensagens       │  │
    │                   │  │  (scrollável)            │  │
    │                   │  ├──────────────────────────┤  │
    │                   │  │  campo de input + botões │  │
    │                   │  └──────────────────────────┘  │
    ├───────────────────┴─────────────────────────────────┤
    │  STATUS BAR                                         │
    └─────────────────────────────────────────────────────┘
    """

    def __init__(self, no: No):
        super().__init__()
        self.no  = no
        self._vizinho_ativo = 0           # índice do vizinho selecionado
        self._contadores: Dict[str, int] = {  # mensagens não lidas por vizinho
            v.nome: 0 for v in no.vizinhos
        }
        self._last_rendered_count = -1        # evita redesenho desnecessário

        # ── Registra callback de mensagem nova ────────────────────────────────
        # A thread de escuta chamará _on_nova_msg() quando chegar mensagem.
        # Como operações de GUI devem rodar na thread principal,
        # usamos self.after(0, ...) para enfileirar na fila de eventos do Tk.
        self.no._callback_nova_msg = self._on_nova_msg_thread_safe

        self._configurar_janela()
        self._construir_ui()
        self._selecionar_vizinho(0)

        # ── Polling de atualização ────────────────────────────────────────────
        # after(100, func) agenda func para rodar após 100ms na thread da GUI.
        # Isso garante que atualizações de histórico apareçam na tela.
        self.after(100, self._tick)

        # Encerramento limpo
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # ── CONFIGURAÇÃO DA JANELA ────────────────────────────────────────────────

    def _configurar_janela(self):
        """
        Configura título, tamanho mínimo, cor de fundo e ícone da janela.
        """
        self.title(f"P2P UDP Chat  ·  {self.no.nome}")
        self.geometry("1100x680")
        self.minsize(800, 520)
        self.configure(bg=C["bg_deep"])
        # Tenta carregar ícone (ignora silenciosamente se não encontrar)
        try:
            self.iconbitmap("icon.ico")
        except Exception:
            pass

    # ── CONSTRUÇÃO DA INTERFACE ───────────────────────────────────────────────

    def _construir_ui(self):
        """
        Cria todos os widgets e faz o layout com grid/pack.

        Estrutura de frames:
          header_frame    → faixa superior com logo e info
          main_frame      → conteúdo principal (sidebar + chat)
            sidebar_frame → lista de conversas
            chat_frame    → painel de mensagens
              conv_header → nome/ip do vizinho ativo
              msg_canvas  → área scrollável de mensagens
              input_frame → campo de texto + botões
          statusbar       → linha inferior de status
        """
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_main()
        self._build_statusbar()

    # ── HEADER ────────────────────────────────────────────────────────────────

    def _build_header(self):
        """
        Faixa superior: logo animado + nome do nó + IP:porta + status ONLINE.
        """
        hf = tk.Frame(self, bg=C["bg_header"], height=56)
        hf.grid(row=0, column=0, sticky="ew")
        hf.grid_propagate(False)

        # Linha de separação inferior do header
        sep = tk.Frame(hf, bg=C["accent"], height=1)
        sep.pack(side="bottom", fill="x")

        # Logo / título
        tk.Label(
            hf, text="◈ P2P UDP CHAT",
            font=("Consolas", 15, "bold"),
            fg=C["accent"], bg=C["bg_header"]
        ).pack(side="left", padx=18, pady=14)

        # Separador vertical
        tk.Frame(hf, bg=C["border"], width=1).pack(side="left", fill="y", pady=10)

        # Info do nó (nome + IP:porta)
        info_frame = tk.Frame(hf, bg=C["bg_header"])
        info_frame.pack(side="left", padx=18)
        tk.Label(
            info_frame, text=f"  {self.no.nome}",
            font=FONT_BOLD, fg=C["text_pri"], bg=C["bg_header"]
        ).pack(anchor="w")
        tk.Label(
            info_frame, text=f"  {self.no.ip} : {self.no.porta}",
            font=FONT_SMALL, fg=C["text_sec"], bg=C["bg_header"]
        ).pack(anchor="w")

        # Status ONLINE (lado direito)
        status_f = tk.Frame(hf, bg=C["bg_header"])
        status_f.pack(side="right", padx=18)
        tk.Label(
            status_f, text="●  ONLINE",
            font=FONT_SMALL, fg=C["online"], bg=C["bg_header"]
        ).pack()
        tk.Label(
            status_f, text=f"UDP / IPv4",
            font=FONT_NANO, fg=C["text_faint"], bg=C["bg_header"]
        ).pack()

    # ── MAIN (sidebar + chat) ─────────────────────────────────────────────────

    def _build_main(self):
        main = tk.Frame(self, bg=C["bg_deep"])
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self._build_sidebar(main)
        self._build_chat(main)

    # ── SIDEBAR ───────────────────────────────────────────────────────────────

    def _build_sidebar(self, parent):
        """
        Painel lateral esquerdo: lista de vizinhos clicáveis.
        Cada botão mostra nome, IP:porta e badge de não-lidas.
        """
        sb = tk.Frame(parent, bg=C["bg_sidebar"], width=200)
        sb.grid(row=0, column=0, sticky="ns")
        sb.grid_propagate(False)

        # Separador vertical direito
        tk.Frame(sb, bg=C["border"], width=1).pack(side="right", fill="y")

        tk.Label(
            sb, text="CONVERSAS",
            font=("Consolas", 8, "bold"),
            fg=C["text_faint"], bg=C["bg_sidebar"]
        ).pack(anchor="w", padx=12, pady=(14, 4))

        self._sidebar_btns: List[tk.Frame] = []
        self._badge_labels: Dict[str, tk.Label] = {}

        for i, viz in enumerate(self.no.vizinhos):
            btn_frame = tk.Frame(sb, bg=C["bg_sidebar"], cursor="hand2")
            btn_frame.pack(fill="x", padx=6, pady=2)

            # Indicador colorido lateral (acende quando selecionado)
            indicator = tk.Frame(btn_frame, bg=C["bg_sidebar"], width=3)
            indicator.pack(side="left", fill="y")

            inner = tk.Frame(btn_frame, bg=C["bg_sidebar"])
            inner.pack(side="left", fill="both", expand=True, padx=8, pady=8)

            tk.Label(
                inner, text=viz.nome,
                font=("Consolas", 11, "bold"),
                fg=C["text_pri"], bg=C["bg_sidebar"], anchor="w"
            ).pack(fill="x")
            tk.Label(
                inner, text=f"{viz.ip}:{viz.porta}",
                font=FONT_NANO,
                fg=C["text_sec"], bg=C["bg_sidebar"], anchor="w"
            ).pack(fill="x")

            # Badge de mensagens não lidas
            badge = tk.Label(
                btn_frame, text="",
                font=("Consolas", 8, "bold"),
                fg=C["bg_deep"], bg=C["accent"],
                padx=4, pady=1
            )
            self._badge_labels[viz.nome] = badge

            # Bind de clique em todos os sub-widgets
            idx = i
            for w in [btn_frame, inner, indicator] + list(inner.winfo_children()):
                w.bind("<Button-1>", lambda e, x=idx: self._selecionar_vizinho(x))
                w.bind("<Enter>",    lambda e, f=btn_frame: f.configure(bg=C["bg_input"]))
                w.bind("<Leave>",    lambda e, f=btn_frame: self._reset_sidebar_hover(f))

            btn_frame._indicator = indicator
            btn_frame._inner     = inner
            self._sidebar_btns.append(btn_frame)

        # Separador + info de teclas
        tk.Frame(sb, bg=C["border"], height=1).pack(fill="x", padx=6, pady=8)
        help_txt = "ENTER  enviar\nF      encaminhar\nESC    cancelar"
        tk.Label(
            sb, text=help_txt,
            font=("Consolas", 8),
            fg=C["text_faint"], bg=C["bg_sidebar"],
            justify="left"
        ).pack(anchor="w", padx=14, pady=4)

    def _reset_sidebar_hover(self, frame):
        """Remove highlight de hover se o item não estiver selecionado."""
        idx = self._sidebar_btns.index(frame)
        if idx != self._vizinho_ativo:
            frame.configure(bg=C["bg_sidebar"])

    # ── PAINEL DE CHAT ────────────────────────────────────────────────────────

    def _build_chat(self, parent):
        """
        Área principal de chat:
          conv_header → nome e info da conversa ativa
          msg_frame   → canvas scrollável com os balões de mensagem
          input_frame → campo de texto + botões Enviar/Encaminhar
        """
        cf = tk.Frame(parent, bg=C["bg_panel"])
        cf.grid(row=0, column=1, sticky="nsew")
        cf.grid_rowconfigure(1, weight=1)
        cf.grid_columnconfigure(0, weight=1)

        # ── Cabeçalho da conversa ─────────────────────────────────────────────
        self._conv_header = tk.Frame(cf, bg=C["bg_header"], height=46)
        self._conv_header.grid(row=0, column=0, sticky="ew")
        self._conv_header.grid_propagate(False)
        tk.Frame(self._conv_header, bg=C["border"], height=1).pack(side="bottom", fill="x")

        self._conv_title = tk.Label(
            self._conv_header, text="",
            font=FONT_BOLD, fg=C["accent"], bg=C["bg_header"]
        )
        self._conv_title.pack(side="left", padx=16, pady=12)

        self._conv_sub = tk.Label(
            self._conv_header, text="",
            font=FONT_NANO, fg=C["text_sec"], bg=C["bg_header"]
        )
        self._conv_sub.pack(side="left", padx=0, pady=12)

        # ── Área de mensagens (Canvas + Scrollbar) ────────────────────────────
        # Usamos Canvas em vez de Frame para poder fazer scroll suave.
        msg_outer = tk.Frame(cf, bg=C["bg_panel"])
        msg_outer.grid(row=1, column=0, sticky="nsew")
        msg_outer.grid_rowconfigure(0, weight=1)
        msg_outer.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            msg_outer, bg=C["bg_panel"],
            highlightthickness=0, bd=0
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        vscroll = tk.Scrollbar(
            msg_outer, orient="vertical",
            command=self._canvas.yview,
            bg=C["bg_panel"], troughcolor=C["bg_panel"],
            activebackground=C["accent"]
        )
        vscroll.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=vscroll.set)

        # Frame interno do canvas (onde os balões são inseridos)
        self._msg_frame = tk.Frame(self._canvas, bg=C["bg_panel"])
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._msg_frame, anchor="nw"
        )

        # Ajusta a largura do frame interno quando o canvas é redimensionado
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._msg_frame.bind("<Configure>", self._on_msgframe_resize)

        # Scroll com roda do mouse (Windows, Linux, macOS)
        self._canvas.bind_all("<MouseWheel>",       self._on_mousewheel)
        self._canvas.bind_all("<Button-4>",         self._on_mousewheel)
        self._canvas.bind_all("<Button-5>",         self._on_mousewheel)

        # ── Input + botões ────────────────────────────────────────────────────
        self._build_input(cf)

    def _build_input(self, parent):
        """
        Rodapé com campo de texto e botões Enviar / Encaminhar.

        Entry com bind de teclas:
          <Return>   → enviar mensagem
          <Escape>   → cancelar modo encaminhamento
          <Key-f>    → ativar modo encaminhamento (se campo vazio)
        """
        if_frame = tk.Frame(parent, bg=C["bg_input"], height=72)
        if_frame.grid(row=2, column=0, sticky="ew")
        if_frame.grid_propagate(False)
        tk.Frame(if_frame, bg=C["accent"], height=1).pack(side="top", fill="x")

        inner = tk.Frame(if_frame, bg=C["bg_input"])
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        inner.grid_columnconfigure(0, weight=1)

        # Campo de texto
        self._entry = tk.Entry(
            inner,
            font=FONT_MONO,
            fg=C["text_pri"],
            bg=C["bg_deep"],
            insertbackground=C["accent"],
            relief="flat",
            bd=6,
        )
        self._entry.grid(row=0, column=0, sticky="ew", ipady=6)
        self._entry.bind("<Return>",  self._ao_enviar)
        self._entry.bind("<Escape>",  self._cancelar_encaminhar)
        self._entry.bind("<Key-f>",   self._tecla_f)
        self._entry.bind("<Key-F>",   self._tecla_f)
        self._entry.focus_set()

        # Frame de botões
        btn_frame = tk.Frame(inner, bg=C["bg_input"])
        btn_frame.grid(row=0, column=1, padx=(8, 0))

        self._btn_enviar = self._make_button(
            btn_frame, "ENVIAR ▶", C["accent"], C["bg_deep"],
            self._ao_enviar
        )
        self._btn_enviar.pack(side="left", padx=(0, 4))

        self._btn_fwd = self._make_button(
            btn_frame, "↩ ENCAMINHAR", C["accent2"], C["text_pri"],
            self._iniciar_encaminhar
        )
        self._btn_fwd.pack(side="left")

    def _make_button(self, parent, text, bg, fg, cmd):
        """
        Cria um botão estilizado com hover effect.

        Hover: inverte as cores de fundo/texto para dar feedback visual.
        activebackground/fg controlam o estado de clique no Tk.
        """
        btn = tk.Button(
            parent, text=text,
            font=("Consolas", 9, "bold"),
            fg=fg, bg=bg,
            activebackground=fg,
            activeforeground=bg,
            relief="flat", bd=0,
            padx=10, pady=6,
            cursor="hand2",
            command=cmd
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=self._lighten(bg)))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    @staticmethod
    def _lighten(hex_color: str, amount: int = 30) -> str:
        """
        Clareia uma cor hex somando 'amount' a cada canal RGB.
        Usado no hover dos botões.
        """
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r, g, b = (min(255, c + amount) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    # ── STATUSBAR ─────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        """
        Linha inferior: mensagens de feedback (envio, erro, encaminhamento).
        """
        sb = tk.Frame(self, bg=C["bg_deep"], height=24)
        sb.grid(row=2, column=0, sticky="ew")
        tk.Frame(sb, bg=C["border"], height=1).pack(side="top", fill="x")

        self._status_var = tk.StringVar(value="Pronto.")
        tk.Label(
            sb,
            textvariable=self._status_var,
            font=FONT_NANO,
            fg=C["text_sec"], bg=C["bg_deep"],
            anchor="w"
        ).pack(side="left", padx=12)

        # Número de pacotes UDP recebidos (contador)
        self._pkt_var = tk.StringVar(value="PKT RX: 0")
        tk.Label(
            sb,
            textvariable=self._pkt_var,
            font=FONT_NANO,
            fg=C["text_faint"], bg=C["bg_deep"]
        ).pack(side="right", padx=12)

        self._pkt_count = 0

    # ── SELEÇÃO DE VIZINHO ────────────────────────────────────────────────────

    def _selecionar_vizinho(self, idx: int):
        """
        Muda a conversa ativa: atualiza a sidebar e redesenha as mensagens.

        Reseta o contador de não-lidas para o vizinho selecionado.
        Desmarca o indicator bar de todos os botões e marca o selecionado.
        """
        if idx >= len(self.no.vizinhos):
            return

        self._vizinho_ativo = idx
        viz = self.no.vizinhos[idx]

        # Reseta badge de não-lidas e força redesenho ao trocar conversa
        self._contadores[viz.nome] = 0
        self._badge_labels[viz.nome].place_forget()
        self._last_rendered_count = -1

        # Atualiza visual da sidebar
        for i, btn in enumerate(self._sidebar_btns):
            cor_bg   = C["bg_input"] if i == idx else C["bg_sidebar"]
            cor_ind  = C["accent"]   if i == idx else C["bg_sidebar"]
            btn.configure(bg=cor_bg)
            btn._indicator.configure(bg=cor_ind)
            btn._inner.configure(bg=cor_bg)
            for w in btn._inner.winfo_children():
                w.configure(bg=cor_bg)

        # Atualiza cabeçalho da conversa
        self._conv_title.configure(text=f"  ◈ {viz.nome}")
        self._conv_sub.configure(text=f"  {viz.ip} : {viz.porta}")

        # Redesenha mensagens
        self._redesenhar_mensagens()
        self._status_var.set(f"Conversa ativa: {viz.nome}")

    # ── RENDERIZAÇÃO DE MENSAGENS ─────────────────────────────────────────────

    def _redesenhar_mensagens(self):
        """
        Limpa o frame de mensagens e renderiza todo o histórico do vizinho ativo.

        destroy() em todos os filhos limpa os widgets antigos.
        _criar_balao() cria um balão estilizado para cada mensagem.
        after(50, scroll_bottom) aguarda os widgets renderizarem antes de rolar.
        """
        for w in self._msg_frame.winfo_children():
            w.destroy()

        viz   = self.no.vizinhos[self._vizinho_ativo]
        hist  = self.no.get_historico(viz.nome)

        self._last_rendered_count = len(hist)

        if not hist:
            tk.Label(
                self._msg_frame,
                text=f"\n\n\n  Nenhuma mensagem ainda.\n  Diga olá para {viz.nome}! 👋",
                font=("Consolas", 11),
                fg=C["text_faint"], bg=C["bg_panel"],
                justify="center"
            ).pack(expand=True, fill="both", pady=40)
        else:
            for item in hist:
                self._criar_balao(item["tipo"], item["msg"])

        self.after(60, self._scroll_bottom)

    def _criar_balao(self, tipo: str, msg: Mensagem):
        """
        Cria um balão de mensagem estilizado dentro do msg_frame.

        tipo:
          "eu"       → balão à direita, cor verde
          "deles"    → balão à esquerda, cor azul-acinzentado
          "fwd"      → balão à esquerda, cor âmbar (encaminhamento recebido)
          "fwd_sent" → balão à direita, cor violeta (encaminhamento enviado)

        Estrutura do balão:
          row_frame (alinhamento esquerda/direita)
            └ bubble_frame (fundo + borda)
                ├ label_de (remetente / "via")
                ├ label_conteudo (texto da mensagem)
                └ label_hora (timestamp à direita)
        """
        eh_meu = tipo in ("eu", "fwd_sent")

        # Cores por tipo
        cores = {
            "eu":       (C["bg_bubble_me"],    C["accent3"],  C["text_pri"]),
            "deles":    (C["bg_bubble_other"], C["accent"],   C["text_pri"]),
            "fwd":      (C["bg_bubble_fwd"],   C["accent4"],  C["text_pri"]),
            "fwd_sent": (C["bg_bubble_me"],    C["accent2"],  C["text_pri"]),
        }
        bg_bubble, cor_nome, cor_txt = cores.get(tipo, cores["deles"])

        # Frame da linha (alinha balão à esquerda ou direita)
        row = tk.Frame(self._msg_frame, bg=C["bg_panel"])
        row.pack(fill="x", padx=8, pady=3)

        # Espaçador oposto ao lado do balão
        if eh_meu:
            tk.Frame(row, bg=C["bg_panel"]).pack(side="left", expand=True, fill="x")

        # Balão
        bubble = tk.Frame(row, bg=bg_bubble)
        bubble.pack(side="right" if eh_meu else "left",
                    anchor="e" if eh_meu else "w",
                    padx=4)

        # Borda colorida lateral
        borda = tk.Frame(bubble, bg=cor_nome, width=3)
        borda.pack(side="left", fill="y")

        inner = tk.Frame(bubble, bg=bg_bubble)
        inner.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        # Linha do remetente
        if tipo == "fwd":
            nome_txt = f"↩ {msg.remetente_nome}  via {msg.encaminhado_por}"
        elif tipo == "fwd_sent":
            nome_txt = f"↩ {msg.remetente_nome}"
        elif tipo == "eu":
            nome_txt = "Você"
        else:
            nome_txt = msg.remetente_nome

        tk.Label(
            inner, text=nome_txt,
            font=("Consolas", 9, "bold"),
            fg=cor_nome, bg=bg_bubble, anchor="w"
        ).pack(fill="x")

        # Conteúdo da mensagem (wraplength=380 px)
        tk.Label(
            inner, text=msg.conteudo,
            font=FONT_MONO2,
            fg=cor_txt, bg=bg_bubble,
            wraplength=380, justify="left", anchor="w"
        ).pack(fill="x", pady=(2, 0))

        # Hora (canto inferior direito do balão)
        tk.Label(
            inner, text=msg.hora(),
            font=FONT_NANO,
            fg=C["text_faint"], bg=bg_bubble, anchor="e"
        ).pack(fill="x")

        if not eh_meu:
            tk.Frame(row, bg=C["bg_panel"]).pack(side="right", expand=True, fill="x")

    # ── CANVAS SCROLL ─────────────────────────────────────────────────────────

    def _on_canvas_resize(self, event):
        """Ajusta a largura do frame interno ao canvas quando a janela é redimensionada."""
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_msgframe_resize(self, event):
        """Atualiza a região de scroll quando o conteúdo muda de tamanho."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_mousewheel(self, event):
        """
        Scroll com a roda do mouse.

        Windows → event.delta (múltiplos de 120)
        Linux   → Button-4 (cima) e Button-5 (baixo)
        macOS   → event.delta (diferente de Windows, mas mesmo código funciona)
        """
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _scroll_bottom(self):
        """Rola o canvas até o final (mensagem mais recente)."""
        self._canvas.update_idletasks()
        self._canvas.yview_moveto(1.0)

    # ── ENVIO ─────────────────────────────────────────────────────────────────

    def _ao_enviar(self, event=None):
        """
        Lê o texto do campo, envia via UDP e limpa o campo.

        strip() remove espaços desnecessários.
        Ignora clique em Enviar se o campo estiver vazio.
        """
        texto = self._entry.get().strip()
        if not texto:
            return

        viz = self.no.vizinhos[self._vizinho_ativo]
        self.no.enviar(viz, texto)
        self._entry.delete(0, "end")
        self._status_var.set(f"✓  Enviado para {viz.nome}")

    # ── ENCAMINHAMENTO ────────────────────────────────────────────────────────

    _modo_encaminhar = False   # usado apenas por _cancelar_encaminhar / Escape

    def _tecla_f(self, event=None):
        """Ativa o modo encaminhamento se o campo estiver vazio."""
        if not self._entry.get():
            self._iniciar_encaminhar()

    def _iniciar_encaminhar(self):
        """
        Abre o diálogo de encaminhamento.

        Busca mensagens recebidas do vizinho ativo e exibe
        uma janela Toplevel para o usuário escolher qual encaminhar
        e para qual vizinho enviar.
        """
        viz  = self.no.vizinhos[self._vizinho_ativo]
        msgs = self.no.get_brutas(viz.nome)

        if not msgs:
            self._status_var.set(f"⚠  Nenhuma mensagem recebida de {viz.nome}.")
            return
        if len(self.no.vizinhos) < 2:
            self._status_var.set("⚠  Encaminhamento requer ao menos 2 vizinhos.")
            return

        self._abrir_dialogo_encaminhar(msgs)

    def _abrir_dialogo_encaminhar(self, msgs: List[Mensagem]):
        """
        Janela Toplevel para selecionar mensagem e destino.

        Toplevel: janela filha independente, mas associada à janela principal.
        grab_set(): captura todos os eventos do mouse/teclado → modal.
        """
        dlg = tk.Toplevel(self)
        dlg.title("Encaminhar Mensagem")
        dlg.configure(bg=C["bg_deep"])
        dlg.geometry("520x460")
        dlg.resizable(False, False)
        dlg.grab_set()   # torna modal

        # Cabeçalho do diálogo
        tk.Label(
            dlg,
            text="↩  ENCAMINHAR MENSAGEM",
            font=("Consolas", 12, "bold"),
            fg=C["accent2"], bg=C["bg_deep"]
        ).pack(anchor="w", padx=18, pady=(18, 4))

        tk.Label(
            dlg,
            text="Selecione a mensagem que deseja encaminhar:",
            font=FONT_SMALL,
            fg=C["text_sec"], bg=C["bg_deep"]
        ).pack(anchor="w", padx=18, pady=(0, 8))

        tk.Frame(dlg, bg=C["border"], height=1).pack(fill="x", padx=18)

        # Lista de mensagens (Listbox estilizado)
        list_frame = tk.Frame(dlg, bg=C["bg_panel"])
        list_frame.pack(fill="both", expand=True, padx=18, pady=10)

        listbox = tk.Listbox(
            list_frame,
            font=("Consolas", 10),
            fg=C["text_pri"],
            bg=C["bg_panel"],
            selectbackground=C["accent2"],
            selectforeground=C["text_pri"],
            activestyle="none",
            relief="flat", bd=0,
            highlightthickness=0
        )
        listbox.pack(side="left", fill="both", expand=True)

        scroll = tk.Scrollbar(list_frame, command=listbox.yview,
                               bg=C["bg_panel"])
        scroll.pack(side="right", fill="y")
        listbox.configure(yscrollcommand=scroll.set)

        for i, m in enumerate(msgs):
            label = f"  [{i}]  {m.remetente_nome}  ·  {m.hora()}  →  {m.conteudo[:42]}"
            listbox.insert("end", label)

        # Seleção de destino
        tk.Label(
            dlg,
            text="Encaminhar para:",
            font=FONT_SMALL,
            fg=C["text_sec"], bg=C["bg_deep"]
        ).pack(anchor="w", padx=18, pady=(4, 2))

        destinos = [
            v for i, v in enumerate(self.no.vizinhos)
            if i != self._vizinho_ativo
        ]

        dest_var = tk.StringVar(value=destinos[0].nome if destinos else "")
        dest_frame = tk.Frame(dlg, bg=C["bg_deep"])
        dest_frame.pack(anchor="w", padx=18, pady=(0, 10))

        for v in destinos:
            tk.Radiobutton(
                dest_frame,
                text=f"  {v.nome}  ({v.ip}:{v.porta})",
                variable=dest_var,
                value=v.nome,
                font=FONT_MONO,
                fg=C["text_pri"],
                bg=C["bg_deep"],
                selectcolor=C["bg_deep"],
                activebackground=C["bg_deep"],
                activeforeground=C["accent2"],
            ).pack(side="left", padx=8)

        # Botões Confirmar / Cancelar
        btn_row = tk.Frame(dlg, bg=C["bg_deep"])
        btn_row.pack(fill="x", padx=18, pady=(0, 14))

        def confirmar():
            sel = listbox.curselection()
            if not sel:
                self._status_var.set("⚠  Selecione uma mensagem na lista.")
                return   # mantém o diálogo aberto para o usuário selecionar
            msg_idx = sel[0]
            destino_nome = dest_var.get()
            destino = next((v for v in self.no.vizinhos if v.nome == destino_nome), None)
            if not destino:
                dlg.destroy()
                return
            self.no.encaminhar(msgs[msg_idx], destino)
            self._status_var.set(
                f"✓  Encaminhado para {destino.nome}: \"{msgs[msg_idx].conteudo[:30]}\""
            )
            dlg.destroy()
            self._redesenhar_mensagens()

        self._make_button(
            btn_row, "CONFIRMAR  ▶", C["accent2"], C["text_pri"], confirmar
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            btn_row, "CANCELAR", C["border"], C["text_sec"],
            dlg.destroy
        ).pack(side="left")

    def _cancelar_encaminhar(self, event=None):
        self._modo_encaminhar = False
        self._status_var.set("Encaminhamento cancelado.")

    # ── CALLBACKS DE ATUALIZAÇÃO ──────────────────────────────────────────────

    def _on_nova_msg_thread_safe(self, chave: str):
        """
        Chamado pela thread de escuta quando chega mensagem nova.

        NÃO modifica widgets diretamente aqui — a thread de escuta
        não pode tocar em widgets Tk (não é thread-safe).
        after(0, ...) enfileira a atualização na thread principal da GUI.
        """
        self.after(0, lambda: self._processar_nova_msg(chave))

    def _processar_nova_msg(self, chave: str):
        """
        Roda na thread principal da GUI (seguro para atualizar widgets).

        Se a mensagem é da conversa ativa → redesenha imediatamente.
        Se não → incrementa o badge de não-lidas do vizinho.
        """
        self._pkt_count += 1
        self._pkt_var.set(f"PKT RX: {self._pkt_count}")

        viz_ativo = self.no.vizinhos[self._vizinho_ativo].nome

        if chave == viz_ativo:
            self._redesenhar_mensagens()
        else:
            if chave in self._contadores:
                self._contadores[chave] += 1
                n = self._contadores[chave]
                idx = next(
                    (i for i, v in enumerate(self.no.vizinhos) if v.nome == chave),
                    None
                )
                if idx is not None:
                    badge = self._badge_labels[chave]
                    badge.configure(text=f" {n} ")
                    badge.place(
                        in_=self._sidebar_btns[idx],
                        relx=1.0, rely=0.0,
                        anchor="ne", x=-4, y=4
                    )

    def _tick(self):
        """
        Polling periódico (a cada 200ms) para redesenhar a conversa ativa.
        Só redesenha se o número de mensagens mudou desde o último render,
        evitando o flickering causado por destruição/recriação constante de widgets.
        """
        viz = self.no.vizinhos[self._vizinho_ativo]
        hist = self.no.get_historico(viz.nome)
        if len(hist) != self._last_rendered_count:
            self._redesenhar_mensagens()
        self.after(200, self._tick)

    # ── ENCERRAMENTO ──────────────────────────────────────────────────────────

    def _ao_fechar(self):
        """
        Encerra o socket UDP antes de fechar a janela Tk.
        Sem isso, a thread de escuta ficaria suspensa em recvfrom().
        """
        self.no.encerrar()
        self.destroy()


# =============================================================================
# SEÇÃO 5 — TELA DE CONFIGURAÇÃO (GUI)
# =============================================================================

class TelaSetup(tk.Tk):
    """
    Tela inicial de configuração exibida quando o programa é executado
    sem argumentos de linha de comando.

    Permite configurar nome/IP/porta do nó local e adicionar vizinhos
    antes de abrir o chat.
    """

    def __init__(self):
        super().__init__()
        self.resultado = None  # (nome, ip, porta, [Vizinho, ...])
        self._vizinhos_frames = []

        self._configurar_janela()
        self._construir_ui()

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def _configurar_janela(self):
        self.title("◈ P2P UDP Chat  ·  Configuração")
        self.geometry("620x560")
        self.minsize(520, 480)
        self.resizable(False, False)
        self.configure(bg=C["bg_deep"])

    def _construir_ui(self):
        # ── Header ────────────────────────────────────────────────────────
        hf = tk.Frame(self, bg=C["bg_header"], height=56)
        hf.pack(fill="x")
        hf.pack_propagate(False)
        tk.Frame(hf, bg=C["accent"], height=1).pack(side="bottom", fill="x")
        tk.Label(
            hf, text="◈ P2P UDP CHAT  ·  SETUP",
            font=("Consolas", 15, "bold"),
            fg=C["accent"], bg=C["bg_header"]
        ).pack(side="left", padx=18, pady=14)

        # ── Container scrollável ──────────────────────────────────────────
        container = tk.Frame(self, bg=C["bg_deep"])
        container.pack(fill="both", expand=True, padx=24, pady=12)

        # ── Seção: Meu Computador ─────────────────────────────────────────
        tk.Label(
            container, text="▸ MEU COMPUTADOR",
            font=FONT_BOLD, fg=C["accent3"], bg=C["bg_deep"]
        ).pack(anchor="w", pady=(8, 2))
        tk.Label(
            container,
            text="Configure os dados deste computador. O outro PC também "
                 "precisa rodar o programa com as configurações dele.",
            font=FONT_NANO, fg=C["text_sec"], bg=C["bg_deep"],
            wraplength=560, justify="left"
        ).pack(anchor="w", pady=(0, 6))

        me_frame = tk.Frame(container, bg=C["bg_panel"],
                            highlightbackground=C["border"], highlightthickness=1)
        me_frame.pack(fill="x", pady=(0, 10))

        row_me = tk.Frame(me_frame, bg=C["bg_panel"])
        row_me.pack(fill="x", padx=12, pady=10)

        # Nome
        tk.Label(row_me, text="Nome:", font=FONT_MONO,
                 fg=C["text_sec"], bg=C["bg_panel"]).grid(row=0, column=0, sticky="w", pady=3)
        self._e_nome = tk.Entry(row_me, font=FONT_MONO, width=18,
                                bg=C["bg_input"], fg=C["text_pri"],
                                insertbackground=C["accent"],
                                relief="flat", highlightthickness=1,
                                highlightbackground=C["border"],
                                highlightcolor=C["accent"])
        self._e_nome.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        self._e_nome.insert(0, "Meu_PC")

        # IP
        tk.Label(row_me, text="IP:", font=FONT_MONO,
                 fg=C["text_sec"], bg=C["bg_panel"]).grid(row=1, column=0, sticky="w", pady=3)
        self._e_ip = tk.Entry(row_me, font=FONT_MONO, width=18,
                              bg=C["bg_input"], fg=C["text_pri"],
                              insertbackground=C["accent"],
                              relief="flat", highlightthickness=1,
                              highlightbackground=C["border"],
                              highlightcolor=C["accent"])
        self._e_ip.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)
        self._e_ip.insert(0, "127.0.0.1")
        tk.Label(
            row_me,
            text="Dica: descubra seu IP com  ipconfig  (Windows) ou  ifconfig / ip a  (Linux/Mac)",
            font=FONT_NANO, fg=C["accent4"], bg=C["bg_panel"]
        ).grid(row=1, column=2, sticky="w", padx=(10, 0), pady=3)

        # Porta
        tk.Label(row_me, text="Porta:", font=FONT_MONO,
                 fg=C["text_sec"], bg=C["bg_panel"]).grid(row=2, column=0, sticky="w", pady=3)
        self._e_porta = tk.Entry(row_me, font=FONT_MONO, width=8,
                                 bg=C["bg_input"], fg=C["text_pri"],
                                 insertbackground=C["accent"],
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=C["border"],
                                 highlightcolor=C["accent"])
        self._e_porta.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=3)
        self._e_porta.insert(0, "5001")
        tk.Label(
            row_me,
            text="Recomendado: use portas entre 5001-5009 (uma diferente por PC)",
            font=FONT_NANO, fg=C["accent4"], bg=C["bg_panel"]
        ).grid(row=2, column=2, sticky="w", padx=(10, 0), pady=3)

        # ── Seção: Vizinhos ───────────────────────────────────────────────
        viz_header = tk.Frame(container, bg=C["bg_deep"])
        viz_header.pack(fill="x", pady=(8, 6))
        tk.Label(
            viz_header, text="▸ VIZINHOS",
            font=FONT_BOLD, fg=C["accent"], bg=C["bg_deep"]
        ).pack(side="left")

        tk.Label(
            container,
            text="Informe o nome, IP e porta de cada PC com quem deseja conversar.",
            font=FONT_NANO, fg=C["text_sec"], bg=C["bg_deep"],
            wraplength=560, justify="left"
        ).pack(anchor="w", pady=(0, 4))

        btn_add = tk.Label(
            viz_header, text="  [+ ADICIONAR]  ",
            font=FONT_SMALL, fg=C["accent3"], bg=C["bg_deep"],
            cursor="hand2"
        )
        btn_add.pack(side="right")
        btn_add.bind("<Button-1>", lambda e: self._adicionar_vizinho())

        self._viz_container = tk.Frame(container, bg=C["bg_deep"])
        self._viz_container.pack(fill="both", expand=True)

        # Adiciona 1 vizinho por padrão
        self._adicionar_vizinho()

        # ── Botão Confirmar ───────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=C["bg_deep"])
        btn_frame.pack(fill="x", padx=24, pady=(4, 16))

        self._btn_confirmar = tk.Label(
            btn_frame,
            text="  ▶  INICIAR CHAT  ",
            font=FONT_BOLD, fg=C["bg_deep"], bg=C["accent"],
            cursor="hand2", padx=20, pady=10
        )
        self._btn_confirmar.pack()
        self._btn_confirmar.bind("<Button-1>", lambda e: self._confirmar())
        self._btn_confirmar.bind("<Enter>",
            lambda e: self._btn_confirmar.configure(bg=C["accent3"]))
        self._btn_confirmar.bind("<Leave>",
            lambda e: self._btn_confirmar.configure(bg=C["accent"]))

        # ── Status ────────────────────────────────────────────────────────
        self._lbl_status = tk.Label(
            self, text="", font=FONT_SMALL,
            fg=C["danger"], bg=C["bg_deep"]
        )
        self._lbl_status.pack(pady=(0, 8))

    def _adicionar_vizinho(self):
        """Adiciona uma linha de campos para um novo vizinho."""
        idx = len(self._vizinhos_frames)

        frame = tk.Frame(self._viz_container, bg=C["bg_panel"],
                         highlightbackground=C["border"], highlightthickness=1)
        frame.pack(fill="x", pady=3)

        row = tk.Frame(frame, bg=C["bg_panel"])
        row.pack(fill="x", padx=10, pady=6)

        # Nome
        tk.Label(row, text="Nome:", font=FONT_SMALL,
                 fg=C["text_sec"], bg=C["bg_panel"]).pack(side="left")
        e_nome = tk.Entry(row, font=FONT_MONO, width=14,
                          bg=C["bg_input"], fg=C["text_pri"],
                          insertbackground=C["accent"],
                          relief="flat", highlightthickness=1,
                          highlightbackground=C["border"],
                          highlightcolor=C["accent"])
        e_nome.pack(side="left", padx=(4, 10))
        e_nome.insert(0, f"Vizinho_{idx + 1}")

        # IP
        tk.Label(row, text="IP:", font=FONT_SMALL,
                 fg=C["text_sec"], bg=C["bg_panel"]).pack(side="left")
        e_ip = tk.Entry(row, font=FONT_MONO, width=14,
                        bg=C["bg_input"], fg=C["text_pri"],
                        insertbackground=C["accent"],
                        relief="flat", highlightthickness=1,
                        highlightbackground=C["border"],
                        highlightcolor=C["accent"])
        e_ip.pack(side="left", padx=(4, 10))
        e_ip.insert(0, "127.0.0.1")

        # Porta
        tk.Label(row, text="Porta:", font=FONT_SMALL,
                 fg=C["text_sec"], bg=C["bg_panel"]).pack(side="left")
        e_porta = tk.Entry(row, font=FONT_MONO, width=6,
                           bg=C["bg_input"], fg=C["text_pri"],
                           insertbackground=C["accent"],
                           relief="flat", highlightthickness=1,
                           highlightbackground=C["border"],
                           highlightcolor=C["accent"])
        e_porta.pack(side="left", padx=(4, 8))
        e_porta.insert(0, str(5002 + idx))

        # Botão remover
        btn_rm = tk.Label(row, text=" ✕ ", font=FONT_SMALL,
                          fg=C["danger"], bg=C["bg_panel"], cursor="hand2")
        btn_rm.pack(side="right")
        btn_rm.bind("<Button-1>",
                    lambda e, f=frame, d=(frame, e_nome, e_ip, e_porta):
                    self._remover_vizinho(d))

        self._vizinhos_frames.append((frame, e_nome, e_ip, e_porta))

    def _remover_vizinho(self, entry_tuple):
        """Remove uma linha de vizinho."""
        if len(self._vizinhos_frames) <= 1:
            self._lbl_status.config(text="É necessário ao menos 1 vizinho.")
            return
        frame, _, _, _ = entry_tuple
        frame.destroy()
        self._vizinhos_frames.remove(entry_tuple)

    def _confirmar(self):
        """Valida os campos e armazena o resultado."""
        self._lbl_status.config(text="")

        nome = self._e_nome.get().strip()
        ip = self._e_ip.get().strip()
        porta_str = self._e_porta.get().strip()

        if not nome:
            self._lbl_status.config(text="Preencha o nome do seu computador.")
            return
        if not ip:
            self._lbl_status.config(text="Preencha o IP do seu computador.")
            return
        try:
            porta = int(porta_str)
        except ValueError:
            self._lbl_status.config(text=f"Porta inválida: '{porta_str}'")
            return

        vizinhos = []
        for _, e_nome, e_ip, e_porta in self._vizinhos_frames:
            vn = e_nome.get().strip()
            vi = e_ip.get().strip()
            vp = e_porta.get().strip()
            if not vn or not vi or not vp:
                self._lbl_status.config(text="Preencha todos os campos dos vizinhos.")
                return
            try:
                vizinhos.append(Vizinho(nome=vn, ip=vi, porta=int(vp)))
            except ValueError:
                self._lbl_status.config(text=f"Porta inválida para '{vn}': '{vp}'")
                return

        self.resultado = (nome, ip, porta, vizinhos)
        self.destroy()

    def _ao_fechar(self):
        self.resultado = None
        self.destroy()


# =============================================================================
# SEÇÃO 6 — PARSE DE ARGUMENTOS
# =============================================================================

def parsear_argumentos():
    """
    Lê e valida argumentos da linha de comando.

    Formato:
      python3 chat_gui.py <nome> <ip> <porta>
                          <viz1_nome> <viz1_ip> <viz1_porta>
                         [<viz2_nome> <viz2_ip> <viz2_porta>]

    range(3, len(args), 3) itera em passos de 3 a partir do índice 3,
    lendo cada trio (nome, ip, porta) de vizinho.
    """
    args = sys.argv[1:]
    if len(args) < 6:
        print(__doc__)
        print("ERRO: Argumentos insuficientes.")
        sys.exit(1)

    nome = args[0]
    ip   = args[1]
    try:
        porta = int(args[2])
    except ValueError:
        print(f"ERRO: '{args[2]}' não é uma porta válida.")
        sys.exit(1)

    vizinhos = []
    for i in range(3, len(args), 3):
        if i + 2 < len(args):
            try:
                vizinhos.append(Vizinho(
                    nome  = args[i],
                    ip    = args[i + 1],
                    porta = int(args[i + 2])
                ))
            except ValueError:
                print(f"ERRO: porta inválida para '{args[i]}'.")
                sys.exit(1)

    if not vizinhos:
        print("ERRO: Informe ao menos 1 vizinho.")
        sys.exit(1)

    return nome, ip, porta, vizinhos


# =============================================================================
# SEÇÃO 7 — PONTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    # Se há argumentos de linha de comando, usa o modo CLI (comportamento original)
    if len(sys.argv) > 1:
        nome, ip, porta, vizinhos = parsear_argumentos()
    else:
        # Sem argumentos → abre a tela de configuração gráfica
        setup = TelaSetup()
        setup.mainloop()
        if setup.resultado is None:
            sys.exit(0)
        nome, ip, porta, vizinhos = setup.resultado

    # Inicia o nó UDP (socket + thread de escuta)
    no = No(nome, ip, porta, vizinhos)

    # Inicia a interface gráfica (bloqueia até fechar a janela)
    app = ChatApp(no)
    app.mainloop()

    # Garante encerramento do socket ao sair
    no.encerrar()
