"""Servidor do bot no WhatsApp (API oficial da Meta - WhatsApp Cloud API).

Rodar:  uvicorn whatsapp:app --host 0.0.0.0 --port 8000
Depois cadastre a URL https://SEU_DOMINIO/webhook no painel da Meta
(com o mesmo WHATSAPP_VERIFY_TOKEN do .env) e assine o campo "messages".
"""
import os
import threading
import time
from collections import OrderedDict

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response

load_dotenv()

from barbearia.atendente import Atendente  # noqa: E402
from barbearia.humanizar import tempo_digitando  # noqa: E402
from barbearia.ia import Gemini  # noqa: E402

TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
VERIFY = os.getenv("WHATSAPP_VERIFY_TOKEN", "barbearia123")
GRAPH = f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION', 'v21.0')}/{PHONE_ID}/messages"


def _post(corpo):
    try:
        r = requests.post(GRAPH, json=corpo, timeout=20,
                          headers={"Authorization": f"Bearer {TOKEN}"})
        if r.status_code >= 300:
            print(f"[whatsapp] erro {r.status_code}: {r.text[:300]}")
    except requests.RequestException as e:
        print(f"[whatsapp] falha: {e}")


def enviar(telefone, texto):
    _post({"messaging_product": "whatsapp", "to": telefone, "type": "text",
           "text": {"body": texto}})


def lido_e_digitando(message_id):
    """Marca como lida (✓✓ azul) e mostra 'digitando...' para o cliente."""
    _post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id,
           "typing_indicator": {"type": "text"}})


bot = Atendente(Gemini(), enviar=enviar)
app = FastAPI()
_vistos = OrderedDict()  # evita responder duas vezes à mesma mensagem (a Meta reenvia)


def processar(telefone, texto, message_id):
    time.sleep(1.2)  # ninguém responde no mesmo milissegundo
    lido_e_digitando(message_id)
    for i, balao in enumerate(bot.responder(telefone, texto)):
        if i:
            lido_e_digitando(message_id)
        time.sleep(tempo_digitando(balao))
        enviar(telefone, balao)


@app.get("/webhook")
def verificar(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY:
        return Response(p.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receber(request: Request, tarefas: BackgroundTasks):
    dados = await request.json()
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for msg in mudanca.get("value", {}).get("messages", []):
                mid = msg.get("id")
                if mid in _vistos:
                    continue
                _vistos[mid] = True
                if len(_vistos) > 2000:
                    _vistos.popitem(last=False)
                tel = msg.get("from")
                tipo = msg.get("type")
                if tipo == "text":
                    texto = msg["text"]["body"]
                elif tipo == "interactive":
                    i = msg["interactive"]
                    texto = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                elif tipo == "audio":
                    texto = "[o cliente mandou um áudio que você não consegue ouvir; peça com jeito para escrever]"
                else:
                    texto = f"[o cliente mandou um(a) {tipo}; responda de forma natural]"
                tarefas.add_task(processar, tel, texto, mid)
    return {"ok": True}


def _loop_lembretes():
    while True:
        try:
            for tel, txt in bot.mensagens_de_lembrete():
                enviar(tel, txt)
        except Exception as e:  # o loop não pode morrer
            print(f"[lembretes] erro: {e}")
        time.sleep(300)


threading.Thread(target=_loop_lembretes, daemon=True).start()
