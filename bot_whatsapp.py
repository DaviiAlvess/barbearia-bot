"""Bot no WhatsApp via Evolution API (Baileys).

Fluxo:
  Evolution API  --webhook MESSAGES_UPSERT-->  este arquivo (FastAPI /webhook)
  este arquivo  -- POST /message/sendText -->  Evolution API  -->  WhatsApp

Rodar:
  uvicorn bot_whatsapp:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response

load_dotenv()

from barbearia import configurar_log  # noqa: E402
from barbearia import evolution as evo  # noqa: E402
from barbearia.atendente import Atendente  # noqa: E402
from barbearia.humanizar import tempo_digitando  # noqa: E402
from barbearia.ia import Gemini  # noqa: E402

configurar_log()
log = logging.getLogger("whatsapp")

_vistos: OrderedDict[str, None] = OrderedDict()
_VISTOS_MAX = 2000
# Pool próprio: não depende de daemon thread solto (morre/trava sem log)
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="wa")


def _lembrar(mid: str) -> bool:
    """True se já vimos essa mensagem."""
    if not mid:
        return False
    if mid in _vistos:
        return True
    _vistos[mid] = None
    while len(_vistos) > _VISTOS_MAX:
        _vistos.popitem(last=False)
    return False


def enviar(numero: str, texto: str) -> None:
    evo.enviar_texto(numero, texto)


def digitando(numero: str) -> None:
    # delay curto: a Evolution bloqueia a request pelo tempo do delay
    evo.digitando(numero, delay_ms=800)


bot = Atendente(Gemini(), enviar=enviar)


def processar(numero: str, texto: str) -> None:
    try:
        log.info("Processando %s…", numero)
        time.sleep(0.8)
        baloes = bot.responder(numero, texto)
        if not baloes:
            log.warning("Sem resposta para %s (pausado, limite ou vazio)", numero)
            return
        for i, balao in enumerate(baloes):
            digitando(numero)
            time.sleep(min(3.0, tempo_digitando(balao) * 0.6))
            enviar(numero, balao)
            log.info("Enviado para %s (%s/%s): %s", numero, i + 1, len(baloes), balao[:60])
    except Exception:  # noqa: BLE001
        log.exception("Falha ao processar mensagem de %s", numero)


def loop_programadas() -> None:
    while True:
        try:
            bot.enviar_programadas()
        except Exception:  # noqa: BLE001 — o loop não pode morrer
            log.exception("Erro ao enviar mensagens programadas")
        time.sleep(300)


def _evento_nome(payload: dict) -> str:
    ev = payload.get("event") or payload.get("Event") or ""
    return str(ev).replace(".", "_").upper()


def _payload_mensagem(payload: dict) -> dict | None:
    data = payload.get("data") or payload
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    # às vezes vem {messages: [...]}
    if "key" not in data and isinstance(data.get("messages"), list) and data["messages"]:
        data = data["messages"][0]
    return data if isinstance(data, dict) else None


def tratar_mensagem(payload: dict) -> None:
    try:
        ev = _evento_nome(payload)
        # Aceita MESSAGES_UPSERT ou payload sem event (só a mensagem)
        if ev and ev not in ("MESSAGES_UPSERT", "MESSAGESUPSERT"):
            return

        data = _payload_mensagem(payload)
        if not data:
            return

        key = data.get("key") or {}
        if key.get("fromMe"):
            return

        remote = key.get("remoteJid") or data.get("remoteJid") or ""
        numero = evo.extrair_telefone(str(remote))
        if not numero:
            # LID / grupo: tenta remoteJidAlt
            alt = key.get("remoteJidAlt") or data.get("remoteJidAlt") or ""
            numero = evo.extrair_telefone(str(alt))
        if not numero:
            log.debug("Ignorada (sem telefone): %s", remote)
            return

        mid = key.get("id") or data.get("id") or ""
        if _lembrar(str(mid)):
            return

        message = data.get("message") or {}
        # remove messageContextInfo noise
        if isinstance(message, dict) and "message" in message and len(message) <= 3:
            message = message.get("message") or message

        tipo = data.get("messageType") or data.get("type")
        texto = evo.extrair_texto_mensagem(message if isinstance(message, dict) else None, tipo)
        if not texto:
            return

        log.info("Mensagem de %s: %s", numero, texto[:80])
        _pool.submit(processar, numero, texto)
    except Exception:  # noqa: BLE001
        log.exception("Falha no webhook")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Boot Evolution: URL=%s instance=%s", evo.URL, evo.INSTANCE)
    try:
        evo.garantir_instancia()
        st = evo.estado_conexao()
        log.info("Estado da conexão: %s", st)
        if st != "open":
            evo.conectar()
    except Exception:  # noqa: BLE001
        log.exception("Falha ao preparar instância Evolution (vou seguir; webhook pode criar depois)")
    threading.Thread(target=loop_programadas, daemon=True).start()
    yield
    _pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Agendbarber — Evolution webhook", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "instance": evo.INSTANCE, "estado": evo.estado_conexao()}


@app.post("/webhook")
async def webhook(request: Request, tarefas: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return Response(status_code=400)
    # processa em background para responder 200 rápido à Evolution
    tarefas.add_task(tratar_mensagem, payload)
    return {"received": True}


def main():
    import uvicorn

    uvicorn.run("bot_whatsapp:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
