"""Filtros duros contra alucinação: serviços inventados e falas de “sistema caiu”."""
from __future__ import annotations

import re
import unicodedata

from barbearia import db

# Frases que o bot NUNCA pode mandar ao cliente (sistema/infra)
_BLOQUEIO_SISTEMA = re.compile(
    r"("
    r"sistema\s+(deu|caiu|travou|trava|inst[aá]vel|fora|ruim)|"
    r"(deu|teve)\s+(uma\s+)?(travad|instabilidade|queda|falha)|"
    r"(internet|servidor|api)\s+(oscil|caiu|fora|trav|inst[aá]vel|ruim)|"
    r"(estou|t[aá]|to)\s+(com\s+)?(problema\s+t[eé]cnico|instabilidade|bug)|"
    r"meu\s+sistema|"
    r"fora\s+do\s+ar|"
    r"erro\s+(t[eé]cnico|interno|no\s+sistema)|"
    r"a\s+ia\s+(trav|caiu|falhou)|"
    r"assistente\s+virtual\s+(trav|fora)"
    r")",
    re.IGNORECASE,
)

_SUBSTITUTO_SISTEMA = (
    "Desculpa pela confusão. Me diz de novo o que você precisa "
    "(marcar horário, ver serviços ou outra dúvida) que eu te ajudo."
)

_REDIRECIONA_BARBEARIA = (
    "Aqui eu cuido só da barbearia — marcar horário, serviços ou dúvidas do salão. "
    "Em que posso te ajudar?"
)

# Respostas que fogem do escopo (saúde, papo aleatório)
_FORA_ESCOPO = re.compile(
    r"("
    r"\b(soro|rem[eé]dio|compressa|dipirona|paracetamol|antibiot|diagn[oó]stico|"
    r"m[eé]dic[oa]|hospital|farm[aá]cia|febre|inje[cç][aã]o)\b|"
    r"melhoras pro |"
    r"desejo melhoras|"
    r"toma um |"
    r"coloca gelo|"
    r"vai passar"
    r")",
    re.IGNORECASE,
)

# Nomes que a IA costuma inventar e que NÃO podem aparecer se não estiverem no banco
_FANTASMAS = (
    "escova progressiva", "progressiva", "botox capilar", "selagem",
    "combo completo", "pacote premium", "spa da barba", "barboterapia completa",
    "design de barba", "mega hair", "alisamento", "corte feminino",
    "manicure", "pedicure", "limpeza de pele", "coloracao", "coloração",
    "hidratacao capilar", "hidratação capilar profunda", "luzes platinadas",
    "corte infantil especial", "massagem capilar", "tonalizacao", "tonalização",
)


def _sem_acento(txt: str) -> str:
    n = unicodedata.normalize("NFKD", (txt or "").lower())
    return "".join(c for c in n if not unicodedata.combining(c))


def nomes_servicos_permitidos() -> set[str]:
    return set(db.listar_servicos().keys())


def sanitizar_resposta(texto: str) -> str:
    """Bloqueia falas de sistema caiu, serviços inventados e papo fora da barbearia."""
    if not (texto or "").strip():
        return texto
    if _BLOQUEIO_SISTEMA.search(texto):
        return _SUBSTITUTO_SISTEMA
    if _FORA_ESCOPO.search(texto) and not _parece_barbeiria(texto):
        return _REDIRECIONA_BARBEARIA

    permitidos = nomes_servicos_permitidos()
    if _tem_servico_fantasma(texto, permitidos):
        lista = db.tabela_servicos_texto()
        if lista:
            return f"Sobre serviços, a gente tem estes:\n{lista}\nQual desses te interessa?"
        return ("No momento a tabela de serviços está vazia no painel. "
                "Posso chamar alguém da equipe pra te atender?")
    return texto


def _parece_barbeiria(texto: str) -> bool:
    t = _sem_acento(texto)
    pistas = (
        "horario", "agend", "corte", "barba", "barbeir", "salao", "preco",
        "servico", "marcar", "vaga", "endereco", "fidelidade",
    )
    return any(p in t for p in pistas)

def _tem_servico_fantasma(texto: str, permitidos: set[str]) -> bool:
    texto_n = _sem_acento(texto)
    permitidos_n = {_sem_acento(p) for p in permitidos}
    for p in list(permitidos_n):
        for parte in re.split(r"[\s/+\-]+", p):
            if len(parte) >= 4:
                permitidos_n.add(parte)
    for fantasma in _FANTASMAS:
        fn = _sem_acento(fantasma)
        if fn not in texto_n:
            continue
        # Se o fantasma é (ou está contido em) um serviço real, ok
        if any(fn in p or p in fn for p in permitidos_n):
            continue
        return True
    return False


def lista_servicos_fechada() -> str:
    itens = db.listar_servicos()
    if not itens:
        return "(nenhum serviço no painel — NÃO invente; diga que a tabela está vazia e chame um atendente)"
    linhas = [
        f"- {nome}: R$ {preco:.2f} (~{mins} min)".replace(".", ",")
        for nome, (preco, mins) in itens.items()
    ]
    return "\n".join(linhas)
