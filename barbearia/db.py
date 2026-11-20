"""Banco de dados SQLite: clientes, agendamentos, conversas, lista de espera e bloqueios."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

CAMINHO_BANCO = os.getenv("BANCO", "barbearia.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    telefone TEXT PRIMARY KEY,
    nome TEXT,
    barbeiro_preferido TEXT,
    observacoes TEXT,
    aceita_mensagens INTEGER NOT NULL DEFAULT 1,   -- 0 = não quer lembretes/avisos
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agendamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telefone TEXT NOT NULL,
    nome_cliente TEXT,
    barbeiro TEXT NOT NULL,
    servico TEXT NOT NULL,
    preco REAL,
    inicio TEXT NOT NULL,   -- 'AAAA-MM-DD HH:MM'
    fim TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmado',  -- confirmado | cancelado
    lembrete_vespera INTEGER NOT NULL DEFAULT 0,
    lembrete_proximo INTEGER NOT NULL DEFAULT 0,
    pedido_avaliacao INTEGER NOT NULL DEFAULT 0,
    nota INTEGER,
    comentario TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ag_barbeiro_inicio ON agendamentos (barbeiro, inicio);
CREATE INDEX IF NOT EXISTS idx_ag_telefone ON agendamentos (telefone);

CREATE TABLE IF NOT EXISTS conversas (
    telefone TEXT PRIMARY KEY,
    historico TEXT NOT NULL DEFAULT '[]',
    atualizado_em REAL NOT NULL,
    humano_ate REAL NOT NULL DEFAULT 0,  -- bot pausado até esse horário (atendente humano)
    avisos TEXT NOT NULL DEFAULT '[]'    -- mensagens que o bot mandou por conta própria
);

CREATE TABLE IF NOT EXISTS lista_espera (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telefone TEXT NOT NULL,
    data TEXT NOT NULL,          -- AAAA-MM-DD
    servico TEXT NOT NULL,
    barbeiro TEXT,
    avisado INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bloqueios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,          -- AAAA-MM-DD
    barbeiro TEXT,               -- NULL = barbearia inteira fechada
    motivo TEXT
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

# colunas adicionadas depois da primeira versão (para quem já tem o banco criado)
MIGRACOES = {
    "conversas": {
        "avisos": "TEXT NOT NULL DEFAULT '[]'",
        "followup_em": "REAL NOT NULL DEFAULT 0",  # último toque de conversa esquecida
    },
    "clientes": {"aceita_mensagens": "INTEGER NOT NULL DEFAULT 1"},
    "agendamentos": {"lembrete_vespera": "INTEGER NOT NULL DEFAULT 0",
                     "lembrete_proximo": "INTEGER NOT NULL DEFAULT 0",
                     "pedido_avaliacao": "INTEGER NOT NULL DEFAULT 0",
                     "nota": "INTEGER", "comentario": "TEXT"},
}


@contextmanager
def conexao(imediata: bool = False) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(CAMINHO_BANCO, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        if imediata:
            # trava escrita: evita dois clientes pegarem o mesmo horário ao mesmo tempo
            con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def criar_tabelas() -> None:
    with conexao() as con:
        con.executescript(ESQUEMA)
        for tabela, colunas in MIGRACOES.items():
            existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


# ---------- clientes ----------
def obter_cliente(telefone: str) -> dict[str, Any] | None:
    with conexao() as con:
        row = con.execute("SELECT * FROM clientes WHERE telefone = ?", (telefone,)).fetchone()
        return dict(row) if row else None


def salvar_cliente(telefone: str, nome: str | None = None, barbeiro_preferido: str | None = None,
                   observacoes: str | None = None) -> None:
    with conexao() as con:
        con.execute("INSERT OR IGNORE INTO clientes (telefone) VALUES (?)", (telefone,))
        for campo, valor in (("nome", nome), ("barbeiro_preferido", barbeiro_preferido),
                             ("observacoes", observacoes)):
            if valor:
                con.execute(f"UPDATE clientes SET {campo} = ? WHERE telefone = ?", (valor, telefone))


def definir_aceita_mensagens(telefone: str, aceita: bool) -> None:
    with conexao() as con:
        con.execute("INSERT OR IGNORE INTO clientes (telefone) VALUES (?)", (telefone,))
        con.execute("UPDATE clientes SET aceita_mensagens = ? WHERE telefone = ?",
                    (1 if aceita else 0, telefone))


def aceita_mensagens(telefone: str) -> bool:
    cliente = obter_cliente(telefone)
    return cliente is None or bool(cliente.get("aceita_mensagens", 1))


def ultimo_atendimento(telefone: str) -> dict[str, Any] | None:
    with conexao() as con:
        row = con.execute(
            """SELECT servico, barbeiro, inicio FROM agendamentos
               WHERE telefone = ? AND status = 'confirmado'
               ORDER BY inicio DESC LIMIT 1""",
            (telefone,),
        ).fetchone()
        return dict(row) if row else None


# ---------- conversas ----------
def carregar_conversa(telefone: str) -> tuple[list[dict], float, float]:
    with conexao() as con:
        row = con.execute("SELECT * FROM conversas WHERE telefone = ?", (telefone,)).fetchone()
        if not row:
            return [], 0.0, 0.0
        return json.loads(row["historico"]), row["atualizado_em"], row["humano_ate"]


def salvar_conversa(telefone: str, historico: list[dict], agora: float) -> None:
    with conexao() as con:
        con.execute(
            """INSERT INTO conversas (telefone, historico, atualizado_em) VALUES (?, ?, ?)
               ON CONFLICT(telefone) DO UPDATE SET historico = excluded.historico,
                                                   atualizado_em = excluded.atualizado_em""",
            (telefone, json.dumps(historico, ensure_ascii=False), agora),
        )


def guardar_aviso(telefone: str, texto: str) -> None:
    with conexao() as con:
        con.execute("INSERT OR IGNORE INTO conversas (telefone, atualizado_em) VALUES (?, 0)", (telefone,))
        row = con.execute("SELECT avisos FROM conversas WHERE telefone = ?", (telefone,)).fetchone()
        avisos = (json.loads(row["avisos"]) + [texto])[-3:]
        con.execute("UPDATE conversas SET avisos = ? WHERE telefone = ?",
                    (json.dumps(avisos, ensure_ascii=False), telefone))


def pegar_avisos(telefone: str) -> list[str]:
    """Devolve e limpa os avisos enviados desde a última resposta do cliente."""
    with conexao() as con:
        row = con.execute("SELECT avisos FROM conversas WHERE telefone = ?", (telefone,)).fetchone()
        if not row:
            return []
        con.execute("UPDATE conversas SET avisos = '[]' WHERE telefone = ?", (telefone,))
        return json.loads(row["avisos"])


def pausar_bot(telefone: str, ate: float) -> None:
    with conexao() as con:
        con.execute(
            """INSERT INTO conversas (telefone, historico, atualizado_em, humano_ate)
               VALUES (?, '[]', 0, ?)
               ON CONFLICT(telefone) DO UPDATE SET humano_ate = excluded.humano_ate""",
            (telefone, ate),
        )


def marcar_followup(telefone: str, quando: float) -> None:
    with conexao() as con:
        con.execute("INSERT OR IGNORE INTO conversas (telefone, atualizado_em) VALUES (?, 0)", (telefone,))
        con.execute("UPDATE conversas SET followup_em = ? WHERE telefone = ?", (quando, telefone))


def conversas_esquecidas(agora: float, min_silencio: float = 2 * 3600,
                         max_idade: float = 18 * 3600) -> list[dict[str, Any]]:
    """Conversas com histórico recente, paradas há um tempo, ainda sem follow-up nesta pausa."""
    limiar_min = agora - max_idade
    limiar_max = agora - min_silencio
    with conexao() as con:
        rows = con.execute(
            """SELECT telefone, historico, atualizado_em, humano_ate, followup_em
               FROM conversas
               WHERE atualizado_em >= ? AND atualizado_em <= ?
                 AND humano_ate < ?
                 AND historico != '[]'
                 AND followup_em < atualizado_em""",
            (limiar_min, limiar_max, agora),
        ).fetchall()
    return [dict(r) for r in rows]


def apagar_dados_cliente(telefone: str) -> None:
    """LGPD: apaga cadastro, conversa e lista de espera (agendamentos viram anônimos)."""
    with conexao() as con:
        con.execute("DELETE FROM clientes WHERE telefone = ?", (telefone,))
        con.execute("DELETE FROM conversas WHERE telefone = ?", (telefone,))
        con.execute("DELETE FROM lista_espera WHERE telefone = ?", (telefone,))
        con.execute("""UPDATE agendamentos SET nome_cliente = 'anônimo', telefone = 'removido',
                       comentario = NULL WHERE telefone = ?""", (telefone,))


# ---------- configuracoes do salão ----------
def obter_config(chave: str, padrao: str | None = None) -> str | None:
    with conexao() as con:
        row = con.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
        return row["valor"] if row else padrao


def salvar_config(chave: str, valor: str) -> None:
    with conexao() as con:
        con.execute(
            """INSERT INTO configuracoes (chave, valor) VALUES (?, ?)
               ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
            (chave, valor),
        )


def nome_salao() -> str:
    """Nome do salão: painel (banco) tem prioridade sobre config.py."""
    import config
    salvo = obter_config("nome_salao")
    if salvo and salvo.strip():
        return salvo.strip()[:80]
    return (config.NOME_BARBEARIA or "Meu Salão").strip()


def _servicos_padrao() -> dict[str, tuple[float, int]]:
    import config
    return {str(n): (float(p), int(m)) for n, (p, m) in config.SERVICOS.items()}


def listar_servicos() -> dict[str, tuple[float, int]]:
    """Tabela de serviços: painel (banco) tem prioridade; senão config.py.

    Retorno: {nome: (preco, minutos)}.
    """
    bruto = obter_config("servicos")
    if not bruto:
        return _servicos_padrao()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        return _servicos_padrao()
    out: dict[str, tuple[float, int]] = {}
    if isinstance(dados, dict):
        itens = dados.items()
    elif isinstance(dados, list):
        itens = ((i.get("nome"), i) for i in dados if isinstance(i, dict))
    else:
        return _servicos_padrao()
    for nome, val in itens:
        if not nome:
            continue
        nome = str(nome).strip()[:80]
        if not nome:
            continue
        try:
            if isinstance(val, dict):
                preco, mins = float(val["preco"]), int(val["minutos"])
            elif isinstance(val, (list, tuple)) and len(val) >= 2:
                preco, mins = float(val[0]), int(val[1])
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if mins < 5:
            mins = 5
        out[nome] = (round(preco, 2), mins)
    return out or _servicos_padrao()


def salvar_servicos(servicos: dict[str, tuple[float, int]] | list[dict]) -> None:
    """Persiste a tabela. Aceita dict nome→(preço, min) ou lista de {nome, preco, minutos}."""
    normalizado: dict[str, list] = {}
    if isinstance(servicos, dict):
        pares = servicos.items()
    else:
        pares = ((s.get("nome"), (s.get("preco"), s.get("minutos"))) for s in servicos)
    for nome, val in pares:
        nome = (str(nome) if nome is not None else "").strip()[:80]
        if not nome:
            continue
        try:
            if isinstance(val, dict):
                preco, mins = float(val["preco"]), int(val["minutos"])
            else:
                preco, mins = float(val[0]), int(val[1])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if mins < 5:
            mins = 5
        normalizado[nome] = [round(preco, 2), mins]
    if not normalizado:
        raise ValueError("Informe ao menos um serviço válido.")
    salvar_config("servicos", json.dumps(normalizado, ensure_ascii=False))


def tabela_servicos_texto() -> str:
    """Lista amigável para a IA / WhatsApp."""
    linhas = []
    for nome, (preco, mins) in listar_servicos().items():
        linhas.append(f"- {nome}: R$ {preco:.2f} (~{mins} min)".replace(".", ","))
    return "\n".join(linhas)


def endereco() -> str:
    """Endereço do salão: painel tem prioridade sobre config.py."""
    import config
    salvo = obter_config("endereco")
    if salvo and salvo.strip():
        return salvo.strip()[:200]
    return (config.ENDERECO or "").strip()


def salvar_endereco(texto: str) -> None:
    texto = (texto or "").strip()[:200]
    if not texto:
        raise ValueError("Informe o endereço.")
    salvar_config("endereco", texto)


def _barbeiros_padrao() -> dict[str, dict[str, Any]]:
    import config
    out: dict[str, dict[str, Any]] = {}
    for nome, info in config.BARBEIROS.items():
        out[str(nome)] = {
            "folgas": list(info.get("folgas") or []),
            "especialidade": str(info.get("especialidade") or ""),
        }
    return out


def listar_barbeiros() -> dict[str, dict[str, Any]]:
    """Equipe: {nome: {folgas: [0-6], especialidade: str}}."""
    bruto = obter_config("barbeiros")
    if not bruto:
        return _barbeiros_padrao()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        return _barbeiros_padrao()
    out: dict[str, dict[str, Any]] = {}
    if isinstance(dados, dict):
        itens = dados.items()
    elif isinstance(dados, list):
        itens = ((i.get("nome"), i) for i in dados if isinstance(i, dict))
    else:
        return _barbeiros_padrao()
    for nome, val in itens:
        if not nome:
            continue
        nome = str(nome).strip()[:60]
        if not nome:
            continue
        if not isinstance(val, dict):
            val = {}
        folgas_raw = val.get("folgas") or []
        folgas: list[int] = []
        for f in folgas_raw:
            try:
                fi = int(f)
            except (TypeError, ValueError):
                continue
            if 0 <= fi <= 6:
                folgas.append(fi)
        out[nome] = {
            "folgas": sorted(set(folgas)),
            "especialidade": str(val.get("especialidade") or "")[:80],
        }
    return out or _barbeiros_padrao()


def salvar_barbeiros(barbeiros: dict[str, dict] | list[dict]) -> None:
    """Persiste a equipe. Aceita dict ou lista de {nome, especialidade, folgas}."""
    normalizado: dict[str, dict] = {}
    pares = barbeiros.items() if isinstance(barbeiros, dict) else ((b.get("nome"), b) for b in barbeiros)
    for nome, val in pares:
        nome = (str(nome) if nome is not None else "").strip()[:60]
        if not nome:
            continue
        if not isinstance(val, dict):
            val = {}
        folgas = []
        for f in val.get("folgas") or []:
            try:
                fi = int(f)
            except (TypeError, ValueError):
                continue
            if 0 <= fi <= 6:
                folgas.append(fi)
        normalizado[nome] = {
            "folgas": sorted(set(folgas)),
            "especialidade": str(val.get("especialidade") or "")[:80],
        }
    if not normalizado:
        raise ValueError("Informe ao menos um profissional.")
    salvar_config("barbeiros", json.dumps(normalizado, ensure_ascii=False))


def remover_barbeiro(nome: str) -> bool:
    """Remove um profissional. True se existia."""
    nome = (nome or "").strip()
    equipe = listar_barbeiros()
    if nome not in equipe:
        # tenta match case-insensitive
        chave = next((k for k in equipe if k.lower() == nome.lower()), None)
        if not chave:
            return False
        nome = chave
    del equipe[nome]
    if not equipe:
        raise ValueError("Não dá para remover o último profissional.")
    salvar_barbeiros(equipe)
    return True


def adicionar_barbeiro(nome: str, especialidade: str = "", folgas: list[int] | None = None) -> None:
    nome = (nome or "").strip()[:60]
    if not nome:
        raise ValueError("Informe o nome do profissional.")
    equipe = listar_barbeiros()
    if any(k.lower() == nome.lower() for k in equipe):
        raise ValueError(f"Já existe alguém chamado {nome}.")
    equipe[nome] = {
        "especialidade": (especialidade or "").strip()[:80],
        "folgas": list(folgas or []),
    }
    salvar_barbeiros(equipe)


def tabela_barbeiros_texto() -> str:
    from barbearia import agenda
    linhas = []
    for nome, info in listar_barbeiros().items():
        esp = info.get("especialidade") or "cortes em geral"
        folgas = info.get("folgas") or []
        extra = ""
        if folgas:
            dias = ", ".join(agenda.DIAS_SEMANA[f] for f in folgas if 0 <= f <= 6)
            extra = f" (folga: {dias})"
        linhas.append(f"- {nome}: manda bem em {esp}{extra}")
    return "\n".join(linhas)
