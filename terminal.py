"""Converse com o bot no terminal (para testar sem WhatsApp).

Uso:  python terminal.py [telefone]
Comandos: /telefone <num>  troca de cliente | /dono  vira o dono | /lembretes  | /sair
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from barbearia.atendente import Atendente  # noqa: E402
from barbearia.humanizar import tempo_digitando  # noqa: E402
from barbearia.ia import Gemini  # noqa: E402

RAPIDO = os.getenv("SEM_ATRASO") == "1"


def enviar(telefone, texto):
    print(f"\n📤 [mensagem para {telefone}] {texto}\n")


def mostrar(baloes):
    for b in baloes:
        if not RAPIDO:
            print("   digitando...", end="\r", flush=True)
            time.sleep(tempo_digitando(b))
        print(" " * 20, end="\r")
        print(f"💈 {b}")


def main():
    telefone = sys.argv[1] if len(sys.argv) > 1 else "5575999990000"
    bot = Atendente(Gemini(), enviar=enviar)
    print(f"Conversando como {telefone}. Digite /sair para encerrar.\n")
    while True:
        try:
            texto = input("você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto == "/sair":
            break
        if texto.startswith("/telefone "):
            telefone = texto.split()[1]
            print(f"(agora você é {telefone})")
            continue
        if texto == "/dono":
            telefone = os.getenv("TELEFONE_DONO") or "dono"
            os.environ["TELEFONE_DONO"] = telefone
            print("(agora você é o dono; digite #ajuda)")
            continue
        if texto == "/lembretes":
            for tel, msg in bot.mensagens_de_lembrete() or [("-", "nenhum lembrete agora")]:
                enviar(tel, msg)
            continue
        baloes = bot.responder(telefone, texto)
        if not baloes:
            print("(bot pausado: um atendente humano assumiu essa conversa)")
        mostrar(baloes)


if __name__ == "__main__":
    main()
