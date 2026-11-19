"""Bot no WhatsApp pelo QR code (mesmo esquema da Belinha / branch belinhafuncional).

Funciona assim:
  servidor-whatsapp (Node, porta 3000)  <-- Socket.IO "novaMensagem" -->  este arquivo (Python)
  este arquivo  -- POST /enviarMensagem -->  servidor-whatsapp  -->  WhatsApp

Rodar:
  1) cd servidor-whatsapp && npm install && npm start   (escaneie o QR code)
  2) python bot_whatsapp.py
"""
import logging
import os
import threading
import time

import requests
import socketio
from dotenv import load_dotenv

load_dotenv()

from barbearia import configurar_log  # noqa: E402
from barbearia.atendente import Atendente  # noqa: E402
from barbearia.humanizar import tempo_digitando  # noqa: E402
from barbearia.ia import Gemini  # noqa: E402

configurar_log()
log = logging.getLogger("whatsapp")
SERVIDOR = os.getenv("SERVIDOR_WHATSAPP", "http://localhost:3000")
ID_SESSAO = os.getenv("ID_SESSAO", "8113")


def _post(rota, dados):
    try:
        r = requests.post(f"{SERVIDOR}{rota}", json={"idSessao": ID_SESSAO, **dados}, timeout=20)
        if r.status_code >= 300 and rota != "/digitando":
            log.error("Erro %s em %s: %s", r.status_code, rota, r.text[:200])
    except requests.RequestException as e:
        if rota != "/digitando":
            log.error("Falha em %s: %s", rota, e)


def enviar(numero, texto):
    _post("/enviarMensagem", {"numero": numero, "mensagem": texto})


def digitando(numero):
    _post("/digitando", {"numero": numero})  # se o servidor não tiver essa rota, só ignora


bot = Atendente(Gemini(), enviar=enviar)
_vistos: set[str] = set()


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
        log.info("Conectado ao servidor do WhatsApp (%s), sessão %s", SERVIDOR, ID_SESSAO)

    @sio.event
    def disconnect():
        log.warning("Desconectado do servidor do WhatsApp. Tentando reconectar...")

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
        log.info("Mensagem de %s: %s", numero, texto[:80])
        # cada mensagem em uma thread para não travar as outras conversas
        threading.Thread(target=processar, args=(numero, texto), daemon=True).start()

    return sio


def loop_programadas():
    """Lembretes e pedidos de avaliação, a cada 5 minutos."""
    while True:
        try:
            bot.enviar_programadas()
        except Exception:  # o loop não pode morrer
            log.exception("Erro ao enviar mensagens programadas")
        time.sleep(300)


def main():
    threading.Thread(target=loop_programadas, daemon=True).start()
    sio = montar_socket()
    while True:
        try:
            log.info("Conectando em %s...", SERVIDOR)
            sio.connect(SERVIDOR)
            sio.wait()
        except socketio.exceptions.ConnectionError as e:
            log.error("Não conectou (%s). O servidor-whatsapp está rodando? Nova tentativa em 10s", e)
            time.sleep(10)
        except KeyboardInterrupt:
            log.info("Bot encerrado.")
            break


if __name__ == "__main__":
    main()
