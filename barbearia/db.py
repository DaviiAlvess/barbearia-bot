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
    "conversas": {"avisos": "TEXT NOT NULL DEFAULT '[]'"},
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
