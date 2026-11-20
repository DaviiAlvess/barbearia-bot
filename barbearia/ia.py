"""Cliente do Google Gemini com chamada de ferramentas (function calling)."""
import logging
import os
import random
import re
import time

import requests

log = logging.getLogger(__name__)

MODELO = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Ordem: modelos com cota livre separada / rápidos primeiro.
FALLBACKS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


class ErroIA(Exception):
    pass


def _modelo_sugerido(erro: str) -> str | None:
    """Extrai models/xxx da mensagem de 404 do Google, se houver."""
    m = re.search(r"models/([a-z0-9.\-]+)", erro or "", re.I)
    return m.group(1) if m else None


_CAMPOS_PART = ("text", "functionCall", "functionResponse", "inlineData", "fileData")


def _limpar_part(p: dict) -> dict | None:
    """Mantém só campos que a API aceita de volta (tira thoughtSignature etc.)."""
    if not isinstance(p, dict):
        return None
    out = {k: p[k] for k in _CAMPOS_PART if k in p and p[k] not in (None, "", [], {})}
    return out or None


def _sanitizar_historico(historico: list) -> list:
    """Remove turnos inválidos que geram HTTP 400 (parts vazias, roles quebradas)."""
    limpo = []
    for h in historico or []:
        if not isinstance(h, dict):
            continue
        parts = []
        for p in h.get("parts") or []:
            lp = _limpar_part(p)
            if lp:
                parts.append(lp)
        if not parts:
            continue
        role = h.get("role") or "user"
        limpo.append({"role": role, "parts": parts})
    while limpo and limpo[0]["role"] == "user" and any("functionResponse" in p for p in limpo[0]["parts"]):
        limpo = limpo[1:]
    return limpo


class Gemini:
    def __init__(self, api_key=None, modelo=None, temperatura=0.4):
        # Temperatura baixa: menos alucinação de serviço/data/horário
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ErroIA("Configure GEMINI_API_KEY no arquivo .env")
        self.modelo = modelo or MODELO
        self.temperatura = temperatura

    def _modelos_candidatos(self) -> list[str]:
        vistos: set[str] = set()
        out: list[str] = []
        for m in [self.modelo, *FALLBACKS]:
            if m and m not in vistos:
                vistos.add(m)
                out.append(m)
        return out

    def _montar_corpo(self, instrucoes, historico, ferramentas, com_thinking: bool):
        cfg = {
            "temperature": self.temperatura,
            "maxOutputTokens": 1024,
        }
        if com_thinking:
            # Só em modelos 2.5 que aceitam; 3.5-flash-lite rejeita (400)
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        return {
            "systemInstruction": {"parts": [{"text": instrucoes}]},
            "contents": _sanitizar_historico(historico),
            "tools": [{"functionDeclarations": ferramentas}] if ferramentas else [],
            "generationConfig": cfg,
        }

    def gerar(self, instrucoes, historico, ferramentas):
        """Retorna o 'content' do modelo: {"role": "model", "parts": [...]}"""
        ultimo_erro = None
        candidatos = self._modelos_candidatos()
        i = 0
        while i < len(candidatos):
            modelo = candidatos[i]
            # 3.5-lite rejeita thinkingConfig; 2.5 gosta de thinkingBudget=0.
            # Ordem: sem thinking primeiro (mais compatível), depois com.
            for com_thinking in (False, True):
                corpo = self._montar_corpo(instrucoes, historico, ferramentas, com_thinking)
                for tentativa in range(3):
                    try:
                        r = requests.post(
                            URL.format(modelo=modelo),
                            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                            json=corpo, timeout=60,
                        )
                        if r.status_code == 200:
                            if modelo != self.modelo:
                                log.warning("Modelo %s indisponível; usando %s", self.modelo, modelo)
                                self.modelo = modelo
                            dados = r.json()
                            cands = dados.get("candidates") or []
                            if not cands or "content" not in cands[0]:
                                raise ErroIA(f"Resposta vazia: {dados.get('promptFeedback')}")
                            conteudo = cands[0]["content"]
                            conteudo.setdefault("role", "model")
                            conteudo.setdefault("parts", [])
                            if not conteudo["parts"]:
                                # MAX_TOKENS / thinking comeu a resposta — tenta sem thinking ou próximo
                                ultimo_erro = "Resposta sem parts"
                                break
                            return conteudo
                        ultimo_erro = f"HTTP {r.status_code}: {r.text[:400]}"
                        if r.status_code == 404:
                            sugerido = _modelo_sugerido(r.text)
                            if sugerido and sugerido not in candidatos:
                                candidatos.append(sugerido)
                            break  # próximo modelo
                        if r.status_code == 400:
                            # argumento inválido: tenta sem thinking; depois próximo modelo
                            log.warning("Gemini 400 em %s (thinking=%s): %s",
                                        modelo, com_thinking, r.text[:200])
                            break
                        if r.status_code == 429:
                            # cota: espera um pouco e, se persistir, troca de modelo
                            log.warning("Gemini 429 (cota) em %s: tentativa %s", modelo, tentativa + 1)
                            time.sleep(min(8, 2 ** tentativa) + random.random())
                            continue
                        if r.status_code not in (500, 502, 503, 504):
                            raise ErroIA(ultimo_erro)
                    except ErroIA:
                        raise
                    except requests.RequestException as e:
                        ultimo_erro = str(e)
                        time.sleep(2 ** tentativa + random.random())
                        continue
                    time.sleep(2 ** tentativa + random.random())
                else:
                    continue
                # saiu do for tentativa com break → próximo com_thinking ou modelo
            i += 1
        raise ErroIA(ultimo_erro or "Falha ao chamar o Gemini")
