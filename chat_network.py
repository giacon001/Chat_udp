"""
=============================================================================
SISTEMA DE MENSAGERIA P2P — PROTOCOLO UDP  |  Camada de Rede
=============================================================================
Contém a lógica de comunicação UDP, estruturas de dados e gerenciamento
de mensagens sem dependência da interface gráfica.
"""

# ── Biblioteca padrão Python (sem instalação necessária) ──────────────────────
import socket           # UDP: AF_INET + SOCK_DGRAM
import threading        # Thread de escuta concorrente + Lock thread-safe
import json             # Serialização/desserialização dos pacotes
import time             # timestamps e delays
import uuid             # IDs únicos para rastreamento de status
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Callable
from collections import deque
from datetime import datetime
from copy import deepcopy


# =============================================================================
# SEÇÃO 1 — ESTRUTURA DA MENSAGEM
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
      encaminhado      — flag: False=original, True=repassada
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
    tipo_pacote: str = "msg"        # "msg", "ack_recebido", "ack_lido"
    msg_id: Optional[str] = None    # ID único para rastreamento de status

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
        self._sock.bind(('0.0.0.0', self.porta))   # escuta em TODAS as interfaces

        # ── Status de mensagens enviadas (msg_id → "enviado"/"recebido"/"lido")
        self._status_msgs: Dict[str, str] = {}

        # ── Histórico por vizinho ─────────────────────────────────────────────
        # deque(maxlen=300): fila circular — evita crescimento ilimitado
        # CHAVE: IP do vizinho (mais robusto que nome, pois IP é único na rede)
        self._historico: Dict[str, deque] = {
            v.ip: deque(maxlen=300) for v in vizinhos
        }
        self._brutas: Dict[str, deque] = {
            v.ip: deque(maxlen=50) for v in vizinhos
        }

        # ── Callbacks para a GUI ──────────────────────────────────────────────
        # A thread de escuta chama este callback quando chega mensagem nova,
        # permitindo que a GUI atualize sem polling contínuo.
        self._callback_nova_msg: Optional[Callable[[str], None]] = None

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
        mid = str(uuid.uuid4())[:8]
        msg = Mensagem(
            timestamp       = datetime.now().isoformat(timespec='seconds'),
            remetente_nome  = self.nome,
            remetente_ip    = self.ip,
            remetente_porta = self.porta,
            dest_nome       = vizinho.nome,
            dest_ip         = vizinho.ip,
            dest_porta      = vizinho.porta,
            conteudo        = texto,
            msg_id          = mid,
        )
        self._sock.sendto(msg.serializar(), vizinho.endereco)
        with self._lock:
            self._status_msgs[mid] = "enviado"
            self._historico[vizinho.ip].append(
                {"tipo": "eu", "msg": msg}
            )
        if self._callback_nova_msg:
            self._callback_nova_msg(vizinho.ip)

    # ── ENCAMINHAMENTO ────────────────────────────────────────────────────────

    def encaminhar(self, msg_original: Mensagem, destino: Vizinho):
        """
        Encaminha mensagem para outro nó.

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
            if destino.ip not in self._historico:
                self._historico[destino.ip] = deque(maxlen=300)
            self._historico[destino.ip].append({"tipo": "fwd_sent", "msg": nota})
        if self._callback_nova_msg:
            self._callback_nova_msg(destino.ip)

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
                if msg.tipo_pacote in ("ack_recebido", "ack_lido"):
                    self._processar_ack(msg)
                else:
                    self._processar(msg)
            except OSError:
                break
            except Exception:
                continue

    def _processar(self, msg: Mensagem):
        """
        Armazena mensagem recebida no histórico correto.

        Roteamento por IP (mais robusto que nome):
          encaminhada → IP de quem encaminhou (se conhecido)
          remetente direto → IP do remetente
          origem nova → cria entrada dinâmica com IP do remetente
        """
        with self._lock:
            # Busca IP de quem encaminhou (se aplicável)
            if msg.encaminhado and msg.encaminhado_por:
                # Procura o IP do vizinho que tem esse nome
                encaminhador_ip = next(
                    (v.ip for v in self.vizinhos if v.nome == msg.encaminhado_por),
                    None
                )
                if encaminhador_ip and encaminhador_ip in self._historico:
                    chave = encaminhador_ip
                elif msg.remetente_ip in self._historico:
                    chave = msg.remetente_ip
                else:
                    chave = msg.remetente_ip
                    self._historico[chave] = deque(maxlen=300)
                    self._brutas[chave]    = deque(maxlen=50)
            elif msg.remetente_ip in self._historico:
                chave = msg.remetente_ip
            else:
                chave = msg.remetente_ip
                self._historico[chave] = deque(maxlen=300)
                self._brutas[chave]    = deque(maxlen=50)

            tipo = "fwd" if msg.encaminhado else "deles"
            self._historico[chave].append({"tipo": tipo, "msg": msg})
            self._brutas[chave].append(deepcopy(msg))

        # Envia ACK de recebimento de volta ao remetente
        if msg.msg_id and not msg.encaminhado:
            self._enviar_ack(msg, "ack_recebido")

        if self._callback_nova_msg:
            self._callback_nova_msg(chave)

    def _enviar_ack(self, msg_original: Mensagem, tipo_ack: str):
        """Envia confirmação (recebido/lido) de volta ao remetente."""
        ack = Mensagem(
            timestamp       = datetime.now().isoformat(timespec='seconds'),
            remetente_nome  = self.nome,
            remetente_ip    = self.ip,
            remetente_porta = self.porta,
            dest_nome       = msg_original.remetente_nome,
            dest_ip         = msg_original.remetente_ip,
            dest_porta      = msg_original.remetente_porta,
            conteudo        = "",
            tipo_pacote     = tipo_ack,
            msg_id          = msg_original.msg_id,
        )
        try:
            self._sock.sendto(
                ack.serializar(),
                (msg_original.remetente_ip, msg_original.remetente_porta)
            )
        except OSError:
            pass

    def _processar_ack(self, msg: Mensagem):
        """Atualiza status de uma mensagem enviada com base no ACK recebido."""
        mid = msg.msg_id
        if not mid:
            return
        with self._lock:
            status_atual = self._status_msgs.get(mid)
            if msg.tipo_pacote == "ack_lido":
                self._status_msgs[mid] = "lido"
            elif msg.tipo_pacote == "ack_recebido" and status_atual != "lido":
                self._status_msgs[mid] = "recebido"
        if self._callback_nova_msg:
            self._callback_nova_msg(msg.remetente_ip)

    def marcar_como_lido(self, ip_vizinho: str):
        """Envia ACK_LIDO para todas as mensagens não-lidas de um vizinho."""
        with self._lock:
            msgs = list(self._historico.get(ip_vizinho, []))
        for item in msgs:
            if item["tipo"] in ("deles", "fwd"):
                msg = item["msg"]
                if msg.msg_id:
                    self._enviar_ack(msg, "ack_lido")

    def get_status(self, msg_id: str) -> str:
        """Retorna status de uma mensagem: enviado/recebido/lido."""
        with self._lock:
            return self._status_msgs.get(msg_id, "enviado")

    # ── GETTERS THREAD-SAFE ───────────────────────────────────────────────────

    def get_historico(self, ip: str) -> list:
        """Cópia thread-safe do histórico de um vizinho (por IP)."""
        with self._lock:
            return list(self._historico.get(ip, []))

    def get_brutas(self, ip: str) -> List[Mensagem]:
        """Cópia thread-safe das mensagens brutas de um vizinho (por IP)."""
        with self._lock:
            return list(self._brutas.get(ip, []))

    def encerrar(self):
        """Fecha socket → causa OSError no recvfrom → thread encerra."""
        self._rodando = False
        try:
            self._sock.close()
        except OSError:
            pass
