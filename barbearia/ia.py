"""Cliente do Google Gemini com chamada de ferramentas (function calling)."""
import logging
import os
import random
import re
import time

import requests

log = logging.getLogger(__name__)

MODELO = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Se o modelo do .env sumir na API do Google, tenta nesta ordem (prioriza rápido).
FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


class ErroIA(Exception):
    pass


def _modelo_sugerido(erro: str) -> str | None:
    """Extrai models/xxx da mensagem de 404 do Google, se houver."""
    m = re.search(r"models/([a-z0-9.\-]+)", erro or "", re.I)
    return m.group(1) if m else None


class Gemini:
    def __init__(self, api_key=None, modelo=None, temperatura=0.8):
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

    def gerar(self, instrucoes, historico, ferramentas):
        """Retorna o 'content' do modelo: {"role": "model", "parts": [...]}"""
        corpo = {
            "systemInstruction": {"parts": [{"text": instrucoes}]},
            "contents": historico,
            "tools": [{"functionDeclarations": ferramentas}] if ferramentas else [],
            "generationConfig": {
                "temperature": self.temperatura,
                "maxOutputTokens": 1024,
                # Sem "thinking": resposta em segundos, não em ~1 min
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        ultimo_erro = None
        candidatos = self._modelos_candidatos()
        i = 0
        while i < len(candidatos):
            modelo = candidatos[i]
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
                        return conteudo
                    ultimo_erro = f"HTTP {r.status_code}: {r.text[:300]}"
                    if r.status_code == 404 and "no longer available" in r.text:
                        sugerido = _modelo_sugerido(r.text)
                        if sugerido and sugerido not in candidatos:
                            candidatos.append(sugerido)
                        break  # tenta próximo modelo
                    if r.status_code not in (429, 500, 502, 503, 504):
                        raise ErroIA(ultimo_erro)
                except ErroIA:
                    raise
                except requests.RequestException as e:
                    ultimo_erro = str(e)
                time.sleep(2 ** tentativa + random.random())
            i += 1
        raise ErroIA(ultimo_erro or "Falha ao chamar o Gemini")
