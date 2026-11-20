"""Deixa a resposta com cara de gente: quebra em balões e calcula tempo de 'digitando...'."""
import random
import re

MAX_BALOES = 3


def limpar(texto):
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)      # tira negrito de markdown
    texto = re.sub(r"(?m)^\s*#+\s*", "", texto)          # tira títulos
    texto = re.sub(r"(?m)^\s*[-*]\s+", "• ", texto)      # listas viram bolinhas
    return texto.strip()


def em_baloes(texto):
    partes = [p.strip() for p in re.split(r"\n\s*\n", limpar(texto)) if p.strip()]
    if len(partes) > MAX_BALOES:  # junta o excesso no último balão
        partes = partes[:MAX_BALOES - 1] + ["\n".join(partes[MAX_BALOES - 1:])]
    return partes


def tempo_digitando(balao):
    """Segundos de 'digitando...' proporcionais ao tamanho (como alguém digitando no celular)."""
    return round(min(6.0, 0.8 + len(balao) / 28) * random.uniform(0.85, 1.15), 1)


# Fallback se a IA falhar — NUNCA falar de sistema/internet/travamento
SEM_IA = [
    "Desculpa, não peguei direito. Pode mandar de novo, por favor?",
    "Poxa, me perde. Repete o que você precisa que eu te ajudo agora?",
    "Não entendi bem aqui. Me fala de novo: quer marcar horário ou ver os serviços?",
    "Opa, pode repetir? Assim eu te ajudo certinho — marcar, preço ou outra dúvida.",
]
