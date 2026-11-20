"""Cliente da Evolution API (Baileys) — instância, QR, envio e presença.

Documentação: https://docs.evolutionfoundation.com.br/evolution-api
Autenticação: header `apikey`.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger("evolution")

URL = os.getenv("EVOLUTION_URL", "http://localhost:8080").rstrip("/")
API_KEY = os.getenv("EVOLUTION_API_KEY", "")
INSTANCE = os.getenv("EVOLUTION_INSTANCE", "barbearia")
WEBHOOK_URL = os.getenv("EVOLUTION_WEBHOOK_URL", "").rstrip("/")

WEBHOOK_EVENTS = [
    "MESSAGES_UPSERT",
    "CONNECTION_UPDATE",
    "QRCODE_UPDATED",
]


def _headers() -> dict[str, str]:
    return {"apikey": API_KEY, "Content-Type": "application/json"}


def _req(method: str, path: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 30)
    url = f"{URL}{path}"
    r = requests.request(method, url, headers=_headers(), timeout=timeout, **kwargs)
    return r


def pronto(tentativas: int = 30, intervalo: float = 2.0) -> bool:
    """Espera a API responder (útil no boot do compose)."""
    for i in range(tentativas):
        try:
            r = _req("GET", "/", timeout=5)
            if r.status_code < 500:
                return True
        except requests.RequestException:
            pass
        log.info("Evolution ainda não respondeu (%s/%s)…", i + 1, tentativas)
        time.sleep(intervalo)
    return False


def listar_instancias() -> list[dict]:
    r = _req("GET", "/instance/fetchInstances", timeout=15)
    if r.status_code >= 300:
        log.warning("fetchInstances %s: %s", r.status_code, r.text[:200])
        return []
    data = r.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("instance") and [data] or data.get("data") or []
    return []


def instancia_existe() -> bool:
    nome = INSTANCE.lower()
    for item in listar_instancias():
        # formatos variam: {instance: {instanceName}}, ou flat
        inst = item.get("instance") if isinstance(item.get("instance"), dict) else item
        n = (inst or {}).get("instanceName") or item.get("name") or item.get("instanceName")
        if n and str(n).lower() == nome:
            return True
    return False


def criar_instancia() -> dict:
    corpo: dict[str, Any] = {
        "instanceName": INSTANCE,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
    }
    if WEBHOOK_URL:
        corpo["webhook"] = {
            "enabled": True,
            "url": WEBHOOK_URL if WEBHOOK_URL.endswith("/webhook") else f"{WEBHOOK_URL}/webhook",
            "byEvents": False,
            "base64": False,
            "events": WEBHOOK_EVENTS,
        }
    r = _req("POST", "/instance/create", json=corpo, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"create instance {r.status_code}: {r.text[:300]}")
    return r.json()


def configurar_webhook() -> None:
    if not WEBHOOK_URL:
        return
    url = WEBHOOK_URL if WEBHOOK_URL.endswith("/webhook") else f"{WEBHOOK_URL}/webhook"
    corpo = {
        "enabled": True,
        "url": url,
        "webhookByEvents": False,
        "webhookBase64": False,
        "events": WEBHOOK_EVENTS,
    }
    r = _req("POST", f"/webhook/set/{INSTANCE}", json=corpo, timeout=20)
    if r.status_code >= 300:
        log.warning("webhook/set %s: %s", r.status_code, r.text[:200])
    else:
        log.info("Webhook apontando para %s", url)


def garantir_instancia() -> None:
    if not API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY não definida")
    if not pronto():
        raise RuntimeError(f"Evolution API inacessível em {URL}")
    if instancia_existe():
        log.info("Instância '%s' já existe", INSTANCE)
        configurar_webhook()
        return
    log.info("Criando instância '%s'…", INSTANCE)
    criar_instancia()
    configurar_webhook()


def estado_conexao() -> str:
    """Retorna open | close | connecting | unknown."""
    try:
        r = _req("GET", f"/instance/connectionState/{INSTANCE}", timeout=8)
    except requests.RequestException as exc:
        log.warning("connectionState: %s", exc)
        return "unknown"
    if r.status_code == 404:
        return "missing"
    if r.status_code >= 300:
        return "unknown"
    data = r.json() or {}
    inst = data.get("instance") or data
    return str(inst.get("state") or data.get("state") or "unknown").lower()


def conectar() -> dict:
    """Inicia conexão / renova QR. Resposta típica: pairingCode, code, base64, count."""
    r = _req("GET", f"/instance/connect/{INSTANCE}", timeout=30)
    if r.status_code >= 300:
        log.warning("connect %s: %s", r.status_code, r.text[:200])
        return {}
    return r.json() if r.content else {}


def logout() -> None:
    with_context = True
    try:
        r = _req("DELETE", f"/instance/logout/{INSTANCE}", timeout=30)
        if r.status_code >= 300:
            log.warning("logout %s: %s", r.status_code, r.text[:200])
    except requests.RequestException as exc:
        log.warning("logout: %s", exc)
        with_context = False
    if with_context:
        time.sleep(1)


def reiniciar_qr() -> dict:
    """Desconecta e pede QR novo."""
    if estado_conexao() == "missing":
        garantir_instancia()
        return conectar()
    logout()
    return conectar()


def status_para_painel() -> dict:
    """Formato esperado pelo painel: conectado, temQr, erro, idadeQrSegundos."""
    try:
        st = estado_conexao()
    except Exception as exc:  # noqa: BLE001
        return {"conectado": False, "temQr": False, "erro": str(exc)}

    if st == "missing":
        try:
            garantir_instancia()
            st = estado_conexao()
        except Exception as exc:  # noqa: BLE001
            return {"conectado": False, "temQr": False, "erro": str(exc)}

    if st == "open":
        return {"conectado": True, "temQr": False, "estado": st}

    if st == "unknown":
        return {"conectado": False, "temQr": False, "erro": f"Evolution sem resposta em {URL}"}

    # connecting / close → tenta obter QR
    data = conectar()
    b64 = (data or {}).get("base64") or ""
    return {
        "conectado": False,
        "temQr": bool(b64),
        "estado": st,
        "idadeQrSegundos": 0 if b64 else None,
    }


def qr_png_bytes() -> bytes | None:
    data = conectar()
    b64 = (data or {}).get("base64") or ""
    if not b64:
        return None
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        log.exception("QR base64 inválido")
        return None


def enviar_texto(numero: str, texto: str) -> None:
    numero = "".join(c for c in str(numero) if c.isdigit())
    corpo = {"number": numero, "text": texto}
    r = _req("POST", f"/message/sendText/{INSTANCE}", json=corpo, timeout=30)
    if r.status_code >= 300:
        log.error("sendText %s: %s", r.status_code, r.text[:300])


def digitando(numero: str, delay_ms: int = 2000) -> None:
    numero = "".join(c for c in str(numero) if c.isdigit())
    # API aceita flat (number, presence, delay) nas versões recentes
    corpo = {"number": numero, "presence": "composing", "delay": max(500, int(delay_ms))}
    try:
        r = _req("POST", f"/chat/sendPresence/{INSTANCE}", json=corpo, timeout=15)
        if r.status_code >= 300:
            # fallback com options (docs antigas)
            corpo2 = {"number": numero, "options": {"delay": corpo["delay"], "presence": "composing"}}
            r2 = _req("POST", f"/chat/sendPresence/{INSTANCE}", json=corpo2, timeout=15)
            if r2.status_code >= 300:
                log.debug("sendPresence %s/%s", r.status_code, r2.status_code)
    except requests.RequestException as exc:
        log.debug("sendPresence: %s", exc)


def extrair_telefone(remote_jid: str) -> str | None:
    """Converte JID WhatsApp em número. Ignora grupos e status."""
    if not remote_jid:
        return None
    jid = remote_jid.split(":")[0]  # remove device suffix
    if jid.endswith("@g.us") or jid == "status@broadcast" or "@lid" in jid:
        return None
    if "@s.whatsapp.net" in jid:
        return jid.split("@", 1)[0]
    if "@" not in jid and jid.isdigit():
        return jid
    return None


def extrair_texto_mensagem(message: dict | None, message_type: str | None = None) -> str | None:
    """Extrai texto útil do payload Baileys / Evolution."""
    if not message:
        return None
    if message.get("conversation"):
        return str(message["conversation"]).strip()
    ext = message.get("extendedTextMessage") or {}
    if ext.get("text"):
        return str(ext["text"]).strip()
    if message.get("imageMessage") or message_type == "imageMessage":
        cap = (message.get("imageMessage") or {}).get("caption")
        return (cap or "").strip() or "[o cliente mandou uma foto; peça com jeito para escrever]"
    if message.get("audioMessage") or message.get("pttMessage") or message_type in (
        "audioMessage",
        "pttMessage",
    ):
        return "[o cliente mandou um áudio que você não consegue ouvir; peça com jeito para escrever]"
    if message.get("videoMessage"):
        cap = (message.get("videoMessage") or {}).get("caption")
        return (cap or "").strip() or "[o cliente mandou um vídeo; peça com jeito para escrever]"
    if message.get("documentMessage"):
        return "[o cliente mandou um arquivo; peça com jeito para escrever]"
    if message.get("stickerMessage"):
        return "[o cliente mandou um figurinha; responda de forma natural]"
    # buttons / list responses
    btn = message.get("buttonsResponseMessage") or message.get("templateButtonReplyMessage") or {}
    if btn.get("selectedDisplayText") or btn.get("selectedId"):
        return str(btn.get("selectedDisplayText") or btn.get("selectedId")).strip()
    lst = message.get("listResponseMessage") or {}
    if lst.get("title") or (lst.get("singleSelectReply") or {}).get("selectedRowId"):
        return str(
            lst.get("title") or (lst.get("singleSelectReply") or {}).get("selectedRowId")
        ).strip()
    return None
