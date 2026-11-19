"""Cliente do Google Gemini com chamada de ferramentas (function calling)."""
import os
import random
import time

import requests

MODELO = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


class ErroIA(Exception):
    pass


class Gemini:
    def __init__(self, api_key=None, modelo=None, temperatura=0.8):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ErroIA("Configure GEMINI_API_KEY no arquivo .env")
        self.modelo = modelo or MODELO
        self.temperatura = temperatura

    def gerar(self, instrucoes, historico, ferramentas):
        """Retorna o 'content' do modelo: {"role": "model", "parts": [...]}"""
        corpo = {
            "systemInstruction": {"parts": [{"text": instrucoes}]},
            "contents": historico,
            "tools": [{"functionDeclarations": ferramentas}],
            "generationConfig": {"temperature": self.temperatura, "maxOutputTokens": 1024},
        }
        ultimo_erro = None
        for tentativa in range(3):
            try:
                r = requests.post(
                    URL.format(modelo=self.modelo),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=corpo, timeout=60,
                )
                if r.status_code == 200:
                    dados = r.json()
                    cands = dados.get("candidates") or []
                    if not cands or "content" not in cands[0]:
                        raise ErroIA(f"Resposta vazia: {dados.get('promptFeedback')}")
                    conteudo = cands[0]["content"]
                    conteudo.setdefault("role", "model")
                    conteudo.setdefault("parts", [])
                    return conteudo
                ultimo_erro = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            except requests.RequestException as e:
                ultimo_erro = str(e)
            time.sleep(2 ** tentativa + random.random())
        raise ErroIA(ultimo_erro or "Falha ao chamar o Gemini")
