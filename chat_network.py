import json
import socket
import threading
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional


@dataclass
class Mensagem:
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
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def desserializar(dados: bytes) -> "Mensagem":
        return Mensagem(**json.loads(dados.decode("utf-8")))

    def hora(self) -> str:
        return self.timestamp[11:16]


@dataclass
class Vizinho:
    nome: str
    ip: str
    porta: int

    @property
    def endereco(self) -> tuple[str, int]:
        return (self.ip, self.porta)


class No:
    def __init__(self, nome: str, ip: str, porta: int, vizinhos: List[Vizinho]):
        self.nome = nome
        self.ip = ip
        self.porta = porta
        self.vizinhos = vizinhos

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.porta))

        self._historico: Dict[str, deque] = {v.nome: deque(maxlen=300) for v in vizinhos}
        self._brutas: Dict[str, deque] = {v.nome: deque(maxlen=100) for v in vizinhos}
        self._lock = threading.Lock()
        self._rodando = True
        self._callback_nova_msg: Optional[Callable[[str], None]] = None

        threading.Thread(target=self._loop_escuta, daemon=True).start()

    def _agora(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _notificar(self, conversa: str):
        if self._callback_nova_msg:
            self._callback_nova_msg(conversa)

    def _garantir_conversa(self, conversa: str):
        if conversa not in self._historico:
            self._historico[conversa] = deque(maxlen=300)
            self._brutas[conversa] = deque(maxlen=100)

    def enviar(self, destino: Vizinho, conteudo: str):
        msg = Mensagem(
            timestamp=self._agora(),
            remetente_nome=self.nome,
            remetente_ip=self.ip,
            remetente_porta=self.porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=conteudo,
            encaminhado=False,
        )
        self._sock.sendto(msg.serializar(), destino.endereco)

        with self._lock:
            self._garantir_conversa(destino.nome)
            self._historico[destino.nome].append({"tipo": "eu", "msg": msg})

        self._notificar(destino.nome)

    def encaminhar(self, msg_original: Mensagem, destino: Vizinho):
        msg = Mensagem(
            timestamp=self._agora(),
            remetente_nome=msg_original.remetente_nome,
            remetente_ip=msg_original.remetente_ip,
            remetente_porta=msg_original.remetente_porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=msg_original.conteudo,
            encaminhado=True,
            encaminhado_por=self.nome,
        )
        self._sock.sendto(msg.serializar(), destino.endereco)

        nota = Mensagem(
            timestamp=msg.timestamp,
            remetente_nome=self.nome,
            remetente_ip=self.ip,
            remetente_porta=self.porta,
            dest_nome=destino.nome,
            dest_ip=destino.ip,
            dest_porta=destino.porta,
            conteudo=f'Encaminhei "{msg_original.conteudo[:40]}" para {destino.nome}',
            encaminhado=True,
            encaminhado_por=self.nome,
        )

        with self._lock:
            self._garantir_conversa(destino.nome)
            self._historico[destino.nome].append({"tipo": "fwd_sent", "msg": nota})

        self._notificar(destino.nome)

    def _loop_escuta(self):
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
        conversa = msg.remetente_nome
        tipo = "fwd" if msg.encaminhado else "deles"

        with self._lock:
            self._garantir_conversa(conversa)
            self._historico[conversa].append({"tipo": tipo, "msg": msg})
            self._brutas[conversa].append(deepcopy(msg))

        self._notificar(conversa)

    def get_historico(self, conversa: str) -> list:
        with self._lock:
            return list(self._historico.get(conversa, []))

    def get_brutas(self, conversa: str) -> List[Mensagem]:
        with self._lock:
            return list(self._brutas.get(conversa, []))

    def listar_conversas(self) -> List[str]:
        with self._lock:
            return list(self._historico.keys())

    def encerrar(self):
        self._rodando = False
        try:
            self._sock.close()
        except OSError:
            pass
