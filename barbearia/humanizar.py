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


# Respostas de emergência se a IA cair (variam para não soar repetido)
SEM_IA = [
    "Opa, meu sistema deu uma travada aqui 😅 Me manda de novo em um minutinho?",
    "Eita, deu uma instabilidade aqui. Já já te respondo, pode mandar de novo daqui a pouco?",
    "Foi mal, a internet aqui oscilou. Tenta de novo rapidinho?",
]
