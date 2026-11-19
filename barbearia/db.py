"""Banco de dados SQLite: clientes, agendamentos e conversas."""
import json
import os
import sqlite3
from contextlib import contextmanager

CAMINHO_BANCO = os.getenv("BANCO", "barbearia.db")


@contextmanager
def conexao(imediata: bool = False):
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


def criar_tabelas():
    with conexao() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                telefone TEXT PRIMARY KEY,
                nome TEXT,
                barbeiro_preferido TEXT,
                observacoes TEXT,
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
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
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
            CREATE INDEX IF NOT EXISTS idx_ag_barbeiro_inicio
                ON agendamentos (barbeiro, inicio);

            CREATE TABLE IF NOT EXISTS conversas (
                telefone TEXT PRIMARY KEY,
                historico TEXT NOT NULL DEFAULT '[]',
                atualizado_em REAL NOT NULL,
                humano_ate REAL NOT NULL DEFAULT 0   -- bot pausado até esse horário (atendente humano)
            );
            """
        )


# ---------- clientes ----------
def obter_cliente(telefone):
    with conexao() as con:
        row = con.execute("SELECT * FROM clientes WHERE telefone = ?", (telefone,)).fetchone()
        return dict(row) if row else None


def salvar_cliente(telefone, nome=None, barbeiro_preferido=None, observacoes=None):
    with conexao() as con:
        con.execute("INSERT OR IGNORE INTO clientes (telefone) VALUES (?)", (telefone,))
        if nome:
            con.execute("UPDATE clientes SET nome = ? WHERE telefone = ?", (nome, telefone))
        if barbeiro_preferido:
            con.execute("UPDATE clientes SET barbeiro_preferido = ? WHERE telefone = ?",
                        (barbeiro_preferido, telefone))
        if observacoes:
            con.execute("UPDATE clientes SET observacoes = ? WHERE telefone = ?",
                        (observacoes, telefone))


def ultimo_atendimento(telefone):
    with conexao() as con:
        row = con.execute(
            """SELECT servico, barbeiro, inicio FROM agendamentos
               WHERE telefone = ? AND status = 'confirmado'
               ORDER BY inicio DESC LIMIT 1""",
            (telefone,),
        ).fetchone()
        return dict(row) if row else None


# ---------- conversas ----------
def carregar_conversa(telefone):
    with conexao() as con:
        row = con.execute("SELECT * FROM conversas WHERE telefone = ?", (telefone,)).fetchone()
        if not row:
            return [], 0.0, 0.0
        return json.loads(row["historico"]), row["atualizado_em"], row["humano_ate"]


def salvar_conversa(telefone, historico, agora):
    with conexao() as con:
        con.execute(
            """INSERT INTO conversas (telefone, historico, atualizado_em) VALUES (?, ?, ?)
               ON CONFLICT(telefone) DO UPDATE SET historico = excluded.historico,
                                                   atualizado_em = excluded.atualizado_em""",
            (telefone, json.dumps(historico, ensure_ascii=False), agora),
        )


def pausar_bot(telefone, ate):
    with conexao() as con:
        con.execute(
            """INSERT INTO conversas (telefone, historico, atualizado_em, humano_ate)
               VALUES (?, '[]', ?, ?)
               ON CONFLICT(telefone) DO UPDATE SET humano_ate = excluded.humano_ate""",
            (telefone, ate, ate),
        )
