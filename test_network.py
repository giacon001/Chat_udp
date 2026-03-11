#!/usr/bin/env python3
"""
Teste da camada de rede sem GUI.
Permite testar o envio/recebimento de mensagens UDP sem interface gráfica.
"""

from chat_network import Mensagem, Vizinho, No
import time
import sys


def callback_msg(ip: str):
    """Callback chamado quando chega mensagem nova."""
    print(f"\n📨 Nova mensagem de {ip}!")


def main():
    if len(sys.argv) < 7:
        print("Uso: python3 test_network.py <nome> <ip> <porta> <viz_nome> <viz_ip> <viz_porta>")
        print("\nExemplo:")
        print("  Terminal 1: python3 test_network.py NoA 127.0.0.1 5001 NoB 127.0.0.1 5002")
        print("  Terminal 2: python3 test_network.py NoB 127.0.0.1 5002 NoA 127.0.0.1 5001")
        sys.exit(1)

    nome = sys.argv[1]
    ip = sys.argv[2]
    porta = int(sys.argv[3])
    
    viz = Vizinho(
        nome=sys.argv[4],
        ip=sys.argv[5],
        porta=int(sys.argv[6])
    )
    
    # Cria o nó
    no = No(nome, ip, porta, [viz])
    no._callback_nova_msg = callback_msg
    
    print(f"✅ Nó '{nome}' iniciado em {ip}:{porta}")
    print(f"📡 Vizinho: {viz.nome} ({viz.ip}:{viz.porta})")
    print("\nComandos:")
    print("  Digite texto e pressione ENTER para enviar")
    print("  'hist' - mostrar histórico")
    print("  'quit' - sair\n")
    
    try:
        while True:
            texto = input(f"{nome}> ").strip()
            
            if texto.lower() == 'quit':
                break
            elif texto.lower() == 'hist':
                hist = no.get_historico(viz.ip)
                print(f"\n📋 Histórico com {viz.nome} ({len(hist)} mensagens):")
                for i, item in enumerate(hist):
                    msg = item['msg']
                    tipo = item['tipo']
                    print(f"  [{i}] [{tipo}] {msg.hora()} - {msg.remetente_nome}: {msg.conteudo}")
                print()
            elif texto:
                no.enviar(viz, texto)
                print(f"✓ Enviado para {viz.nome}")
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\n👋 Encerrando...")
    
    finally:
        no.encerrar()
        print("✅ Socket fechado")


if __name__ == "__main__":
    main()
