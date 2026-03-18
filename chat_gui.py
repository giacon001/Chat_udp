
import sys
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from chat_network import Mensagem, No, Vizinho


@dataclass
class EstadoCLI:
    conversa_ativa: str
    nao_lidas: Dict[str, int]


class ChatCLI:
    def __init__(self, no: No):
        self.no = no
        self.vizinhos = {v.nome: v for v in no.vizinhos}
        conversa_inicial = no.vizinhos[0].nome if no.vizinhos else ""
        self.estado = EstadoCLI(conversa_ativa=conversa_inicial, nao_lidas={})
        self._print_lock = threading.Lock()

        for nome in self.no.listar_conversas():
            self.estado.nao_lidas[nome] = 0

        self.no._callback_nova_msg = self._on_nova_msg

    def _safe_print(self, texto: str = ""):
        with self._print_lock:
            print(texto)

    def _on_nova_msg(self, conversa: str):
        if conversa not in self.estado.nao_lidas:
            self.estado.nao_lidas[conversa] = 0

        if conversa == self.estado.conversa_ativa:
            self._safe_print(f"\n📨 Nova mensagem em [{conversa}]")
            self._mostrar_historico(conversa, limite=1)
        else:
            self.estado.nao_lidas[conversa] += 1
            n = self.estado.nao_lidas[conversa]
            self._safe_print(f"\n🔔 {n} nova(s) em [{conversa}]")

    def _formatar_item(self, item: dict) -> str:
        tipo = item["tipo"]
        msg: Mensagem = item["msg"]

        if tipo == "eu":
            return f"[{msg.hora()}] Você: {msg.conteudo}"
        if tipo == "fwd_sent":
            return f"[{msg.hora()}] Você (encaminhou): {msg.conteudo}"
        if tipo == "fwd":
            return (
                f"[{msg.hora()}] Encaminhado por {msg.encaminhado_por}: "
                f"[{msg.remetente_nome}] {msg.conteudo}"
            )
        return f"[{msg.hora()}] {msg.remetente_nome}: {msg.conteudo}"

    def _mostrar_historico(self, conversa: str, limite: Optional[int] = None):
        hist = self.no.get_historico(conversa)
        if not hist:
            self._safe_print("(sem mensagens)")
            return

        itens = hist[-limite:] if limite else hist
        for i, item in enumerate(itens):
            self._safe_print(f"{i:03d} {self._formatar_item(item)}")

    def _listar_conversas(self):
        self._safe_print("\n=== Conversas ===")
        for nome in self.no.listar_conversas():
            marcador = "*" if nome == self.estado.conversa_ativa else " "
            badge = self.estado.nao_lidas.get(nome, 0)
            extra = f" ({badge} nova(s))" if badge else ""
            self._safe_print(f"{marcador} {nome}{extra}")

    def _ajuda(self):
        self._safe_print(
            """
Comandos:
  /ajuda                         Mostra esta ajuda
  /conversas                     Lista conversas
  /abrir <nome>                  Abre conversa
  /historico                     Mostra histórico da conversa ativa
  /enviar <texto>                Envia para o vizinho da conversa ativa
  /encaminhar <idx> <destino>    Encaminha mensagem recebida para outro nó
  /sair                          Encerra

Dica: se digitar texto sem comando, equivale a /enviar <texto>.
""".strip()
        )

    def _abrir_conversa(self, nome: str):
        conversas = self.no.listar_conversas()
        if nome not in conversas:
            self._safe_print(f"Conversa '{nome}' não existe.")
            return
        self.estado.conversa_ativa = nome
        self.estado.nao_lidas[nome] = 0
        self._safe_print(f"\n✅ Conversa ativa: [{nome}]")
        self._mostrar_historico(nome, limite=10)

    def _enviar(self, texto: str):
        if not texto.strip():
            return
        destino = self.vizinhos.get(self.estado.conversa_ativa)
        if not destino:
            self._safe_print("Só é possível enviar para vizinhos diretos.")
            return
        self.no.enviar(destino, texto)

    def _encaminhar(self, idx_str: str, destino_nome: str):
        conversa = self.estado.conversa_ativa
        hist = self.no.get_historico(conversa)
        if not hist:
            self._safe_print("Sem mensagens nessa conversa.")
            return

        try:
            idx = int(idx_str)
        except ValueError:
            self._safe_print("Índice inválido.")
            return

        if idx < 0 or idx >= len(hist):
            self._safe_print("Índice fora do intervalo.")
            return

        item = hist[idx]
        if item["tipo"] not in ("deles", "fwd"):
            self._safe_print("Você só pode encaminhar mensagens recebidas.")
            return

        destino = self.vizinhos.get(destino_nome)
        if not destino:
            self._safe_print(f"Destino '{destino_nome}' não é vizinho direto.")
            return

        self.no.encaminhar(item["msg"], destino)
        self._safe_print(f"✅ Encaminhado para {destino.nome}")

    def executar(self):
        self._safe_print("\n◈ CHAT P2P UDP (CLI)")
        self._safe_print(f"Nó: {self.no.nome}  ({self.no.ip}:{self.no.porta})")
        self._safe_print("Digite /ajuda para ver comandos.\n")
        self._listar_conversas()

        while True:
            try:
                linha = input(f"\n[{self.estado.conversa_ativa}]> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._safe_print("\nSaindo...")
                break

            if not linha:
                continue

            if not linha.startswith("/"):
                self._enviar(linha)
                continue

            partes = linha.split(maxsplit=2)
            cmd = partes[0].lower()

            if cmd == "/sair":
                break
            if cmd == "/ajuda":
                self._ajuda()
            elif cmd == "/conversas":
                self._listar_conversas()
            elif cmd == "/historico":
                self._mostrar_historico(self.estado.conversa_ativa)
            elif cmd == "/abrir" and len(partes) >= 2:
                self._abrir_conversa(partes[1])
            elif cmd == "/enviar" and len(partes) >= 2:
                texto = linha.split(maxsplit=1)[1]
                self._enviar(texto)
            elif cmd == "/encaminhar" and len(partes) >= 3:
                sub = partes[2].split(maxsplit=1)
                if len(sub) < 2:
                    self._safe_print("Uso: /encaminhar <idx> <destino>")
                else:
                    self._encaminhar(sub[0], sub[1])
            else:
                self._safe_print("Comando inválido. Use /ajuda.")

        self.no.encerrar()


def parsear_argumentos():
    args = sys.argv[1:]
    if len(args) < 6 or len(args) % 3 != 0:
        print(
            "Uso:\n"
            "  python3 chat_gui.py <nome> <ip> <porta> "
            "<viz1_nome> <viz1_ip> <viz1_porta> "
            "[<viz2_nome> <viz2_ip> <viz2_porta> ...]"
        )
        sys.exit(1)

    nome, ip, porta_str = args[0], args[1], args[2]
    try:
        porta = int(porta_str)
    except ValueError:
        print(f"Porta inválida: {porta_str}")
        sys.exit(1)

    vizinhos: List[Vizinho] = []
    for i in range(3, len(args), 3):
        v_nome, v_ip, v_porta_str = args[i], args[i + 1], args[i + 2]
        try:
            v_porta = int(v_porta_str)
        except ValueError:
            print(f"Porta inválida para {v_nome}: {v_porta_str}")
            sys.exit(1)
        vizinhos.append(Vizinho(v_nome, v_ip, v_porta))

    return nome, ip, porta, vizinhos


if __name__ == "__main__":
    nome, ip, porta, vizinhos = parsear_argumentos()
    no = No(nome, ip, porta, vizinhos)
    ChatCLI(no).executar()
