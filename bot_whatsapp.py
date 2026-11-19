"""Bot no WhatsApp pelo QR code (mesmo esquema da Belinha / branch belinhafuncional).

Funciona assim:
  servidor-whatsapp (Node, porta 3000)  <-- Socket.IO "novaMensagem" -->  este arquivo (Python)
  este arquivo  -- POST /enviarMensagem -->  servidor-whatsapp  -->  WhatsApp

Rodar:
  1) cd servidor-whatsapp && npm install && npm start   (escaneie o QR code)
  2) python bot_whatsapp.py
"""
import os
import threading
import time

import requests
import socketio
from dotenv import load_dotenv

load_dotenv()

from barbearia.atendente import Atendente  # noqa: E402
from barbearia.humanizar import tempo_digitando  # noqa: E402
from barbearia.ia import Gemini  # noqa: E402

SERVIDOR = os.getenv("SERVIDOR_WHATSAPP", "http://localhost:3000")
ID_SESSAO = os.getenv("ID_SESSAO", "8113")


def _post(rota, dados):
    try:
        r = requests.post(f"{SERVIDOR}{rota}", json={"idSessao": ID_SESSAO, **dados}, timeout=20)
        if r.status_code >= 300 and rota != "/digitando":
            print(f"[whatsapp] erro {r.status_code} em {rota}: {r.text[:200]}")
    except requests.RequestException as e:
        if rota != "/digitando":
            print(f"[whatsapp] falha em {rota}: {e}")


def enviar(numero, texto):
    _post("/enviarMensagem", {"numero": numero, "mensagem": texto})


def digitando(numero):
    _post("/digitando", {"numero": numero})  # se o servidor não tiver essa rota, só ignora


bot = Atendente(Gemini(), enviar=enviar)
_vistos = set()


def processar(numero, texto):
    time.sleep(1.5)  # ninguém responde no mesmo milissegundo
    for balao in bot.responder(numero, texto):
        digitando(numero)
        time.sleep(tempo_digitando(balao))
        enviar(numero, balao)


def montar_socket():
    sio = socketio.Client(reconnection=True, reconnection_delay=5)

    @sio.event
    def connect():
        print(f"✅ Conectado ao servidor do WhatsApp ({SERVIDOR}), sessão {ID_SESSAO}")

    @sio.event
    def disconnect():
        print("⚠️ Desconectado do servidor do WhatsApp. Tentando reconectar...")

    @sio.on("novaMensagem")
    def nova_mensagem(data):
        if str(data.get("idSessao", ID_SESSAO)) != str(ID_SESSAO):
            return
        origem = data.get("from", "")
        if data.get("fromMe") or origem.endswith("@g.us") or origem == "status@broadcast":
            return  # ignora grupos, status e mensagens enviadas por nós
        mid = data.get("id")
        if mid:
            if mid in _vistos:
                return
            _vistos.add(mid)
        numero = origem.replace("@c.us", "")
        tipo = data.get("type", "chat")
        texto = (data.get("body") or "").strip()
        if tipo in ("ptt", "audio"):
            texto = "[o cliente mandou um áudio que você não consegue ouvir; peça com jeito para escrever]"
        elif tipo not in ("chat", "text") and not texto:
            texto = f"[o cliente mandou um(a) {tipo}; responda de forma natural]"
        if not texto:
            return
        print(f"📩 {numero}: {texto}")
        # cada mensagem em uma thread para não travar as outras conversas
        threading.Thread(target=processar, args=(numero, texto), daemon=True).start()

    return sio


def loop_lembretes():
    while True:
        try:
            for numero, texto in bot.mensagens_de_lembrete():
                enviar(numero, texto)
        except Exception as e:  # o loop não pode morrer
            print(f"[lembretes] erro: {e}")
        time.sleep(300)


def main():
    threading.Thread(target=loop_lembretes, daemon=True).start()
    sio = montar_socket()
    while True:
        try:
            print(f"Conectando em {SERVIDOR}...")
            sio.connect(SERVIDOR)
            sio.wait()
        except socketio.exceptions.ConnectionError as e:
            print(f"❌ Não conectou ({e}). O servidor-whatsapp está rodando? Tentando de novo em 10s...")
            time.sleep(10)
        except KeyboardInterrupt:
            print("\nBot encerrado.")
            break


if __name__ == "__main__":
    main()
