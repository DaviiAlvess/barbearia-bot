"""Regras da agenda: dias abertos, horários livres por barbeiro, agendar e cancelar."""
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
from barbearia import db

TZ = ZoneInfo(config.FUSO_HORARIO)
FMT = "%Y-%m-%d %H:%M"
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


class ErroAgenda(Exception):
    """Erro com mensagem amigável para a IA repassar ao cliente."""


def agora():
    return datetime.now(TZ).replace(tzinfo=None)


def _normalizar(txt):
    txt = unicodedata.normalize("NFKD", txt.lower().strip())
    return "".join(c for c in txt if not unicodedata.combining(c))


def achar_servico(nome):
    alvo = _normalizar(nome)
    for s in config.SERVICOS:
        if _normalizar(s) == alvo:
            return s
    alvo = alvo.replace("+", "e")
    nomes = {s: _normalizar(s).replace("+", "e").split(" (")[0] for s in config.SERVICOS}
    for s, ns in nomes.items():  # "platinado" -> "Luzes / Platinado"
        if alvo in ns:
            return s
    # "quero corte e barba" -> pega o nome mais longo contido no texto
    for s, ns in sorted(nomes.items(), key=lambda x: -len(x[1])):
        if ns in alvo:
            return s
    raise ErroAgenda(f"Serviço '{nome}' não existe. Serviços: {', '.join(config.SERVICOS)}")


def achar_barbeiro(nome):
    if not nome:
        return None
    alvo = _normalizar(nome)
    for b in config.BARBEIROS:
        if _normalizar(b) == alvo:
            return b
    raise ErroAgenda(f"Não temos barbeiro chamado '{nome}'. Equipe: {', '.join(config.BARBEIROS)}")


def ler_data(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ErroAgenda("Data inválida, use o formato AAAA-MM-DD.")


def _hm(d: date, hhmm: str):
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def expediente(d: date):
    """Retorna (abre, fecha) do dia ou None se fechado."""
    faixa = config.HORARIO_FUNCIONAMENTO.get(d.weekday())
    if not faixa:
        return None
    return _hm(d, faixa[0]), _hm(d, faixa[1])


def barbeiros_do_dia(d: date):
    if not expediente(d):
        return []
    return [b for b, info in config.BARBEIROS.items() if d.weekday() not in info.get("folgas", [])]


def _ocupados(con, barbeiro, d: date):
    rows = con.execute(
        """SELECT inicio, fim FROM agendamentos
           WHERE barbeiro = ? AND status = 'confirmado' AND inicio LIKE ?""",
        (barbeiro, d.isoformat() + "%"),
    ).fetchall()
    return [(datetime.strptime(r["inicio"], FMT), datetime.strptime(r["fim"], FMT)) for r in rows]


def _cabe(inicio, fim, d, ocupados):
    abre, fecha = expediente(d)
    if inicio < abre or fim > fecha:
        return False
    if config.ALMOCO:
        a1, a2 = _hm(d, config.ALMOCO[0]), _hm(d, config.ALMOCO[1])
        if inicio < a2 and fim > a1:
            return False
    if inicio < agora() + timedelta(minutes=15):  # não agenda no passado nem em cima da hora
        return False
    return all(not (inicio < o_fim and fim > o_ini) for o_ini, o_fim in ocupados)


def horarios_livres(data_txt, servico, barbeiro=None):
    d = ler_data(data_txt)
    servico = achar_servico(servico)
    barbeiro = achar_barbeiro(barbeiro)
    hoje = agora().date()
    if d < hoje:
        raise ErroAgenda("Essa data já passou.")
    if d > hoje + timedelta(days=config.DIAS_ANTECEDENCIA):
        raise ErroAgenda(f"Só abrimos agenda com até {config.DIAS_ANTECEDENCIA} dias de antecedência.")
    if not expediente(d):
        return {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()],
                "fechado": True, "mensagem": "A barbearia não abre nesse dia."}

    duracao = timedelta(minutes=config.SERVICOS[servico][1])
    passo = timedelta(minutes=config.INTERVALO_AGENDA)
    equipe = [barbeiro] if barbeiro else barbeiros_do_dia(d)
    if barbeiro and barbeiro not in barbeiros_do_dia(d):
        return {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()],
                "mensagem": f"{barbeiro} está de folga nesse dia.",
                "outros_barbeiros_no_dia": barbeiros_do_dia(d)}

    abre, fecha = expediente(d)
    resultado = {}
    with db.conexao() as con:
        for b in equipe:
            ocup = _ocupados(con, b, d)
            livres, t = [], abre
            while t + duracao <= fecha:
                if _cabe(t, t + duracao, d, ocup):
                    livres.append(t.strftime("%H:%M"))
                t += passo
            resultado[b] = livres
    return {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()],
            "servico": servico, "duracao_min": config.SERVICOS[servico][1],
            "livres_por_barbeiro": resultado}


def agendar(telefone, nome_cliente, data_txt, hora, servico, barbeiro=None):
    d = ler_data(data_txt)
    servico = achar_servico(servico)
    barbeiro = achar_barbeiro(barbeiro)
    try:
        inicio = _hm(d, hora)
    except (ValueError, AttributeError):
        raise ErroAgenda("Hora inválida, use HH:MM.")
    if not expediente(d):
        raise ErroAgenda("A barbearia não abre nesse dia.")
    preco, minutos = config.SERVICOS[servico]
    fim = inicio + timedelta(minutes=minutos)
    candidatos = [barbeiro] if barbeiro else barbeiros_do_dia(d)

    with db.conexao(imediata=True) as con:
        for b in candidatos:
            if b not in barbeiros_do_dia(d):
                continue
            if _cabe(inicio, fim, d, _ocupados(con, b, d)):
                cur = con.execute(
                    """INSERT INTO agendamentos
                       (telefone, nome_cliente, barbeiro, servico, preco, inicio, fim)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (telefone, nome_cliente, b, servico, preco,
                     inicio.strftime(FMT), fim.strftime(FMT)),
                )
                return {"ok": True, "id": cur.lastrowid, "barbeiro": b, "servico": servico,
                        "data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()],
                        "hora": hora, "preco": preco, "duracao_min": minutos}
    quem = barbeiro or "nenhum barbeiro"
    raise ErroAgenda(f"Esse horário não está livre para {quem}. Consulte os horários livres de novo.")


def agendamentos_futuros(telefone):
    with db.conexao() as con:
        rows = con.execute(
            """SELECT id, barbeiro, servico, preco, inicio FROM agendamentos
               WHERE telefone = ? AND status = 'confirmado' AND inicio >= ?
               ORDER BY inicio""",
            (telefone, agora().strftime(FMT)),
        ).fetchall()
    saida = []
    for r in rows:
        ini = datetime.strptime(r["inicio"], FMT)
        saida.append({"id": r["id"], "barbeiro": r["barbeiro"], "servico": r["servico"],
                      "preco": r["preco"], "data": ini.date().isoformat(),
                      "dia_semana": DIAS_SEMANA[ini.weekday()], "hora": ini.strftime("%H:%M")})
    return saida


def cancelar(telefone, agendamento_id):
    with db.conexao(imediata=True) as con:
        row = con.execute(
            "SELECT * FROM agendamentos WHERE id = ? AND telefone = ? AND status = 'confirmado'",
            (agendamento_id, telefone),
        ).fetchone()
        if not row:
            raise ErroAgenda("Não achei esse agendamento entre os horários desse cliente.")
        con.execute("UPDATE agendamentos SET status = 'cancelado' WHERE id = ?", (agendamento_id,))
    return {"ok": True, "cancelado": {"id": row["id"], "servico": row["servico"],
                                      "barbeiro": row["barbeiro"], "inicio": row["inicio"]}}


def remarcar(telefone, agendamento_id, nova_data, nova_hora, barbeiro=None):
    """Marca o novo horário primeiro; só cancela o antigo se o novo deu certo."""
    with db.conexao() as con:
        row = con.execute(
            "SELECT * FROM agendamentos WHERE id = ? AND telefone = ? AND status = 'confirmado'",
            (agendamento_id, telefone),
        ).fetchone()
    if not row:
        raise ErroAgenda("Não achei esse agendamento entre os horários desse cliente.")
    novo = agendar(telefone, row["nome_cliente"], nova_data, nova_hora, row["servico"],
                   barbeiro or row["barbeiro"])
    cancelar(telefone, agendamento_id)
    return {"ok": True, "antigo": row["inicio"], "antigo_barbeiro": row["barbeiro"], "novo": novo}


# ---------- lista de espera ----------
def entrar_lista_espera(telefone, data_txt, servico, barbeiro=None):
    d = ler_data(data_txt)
    servico = achar_servico(servico)
    barbeiro = achar_barbeiro(barbeiro)
    with db.conexao() as con:
        con.execute("INSERT INTO lista_espera (telefone, data, servico, barbeiro) VALUES (?, ?, ?, ?)",
                    (telefone, d.isoformat(), servico, barbeiro))
    return {"ok": True, "data": d.isoformat(), "servico": servico, "barbeiro": barbeiro}


def quem_esperava(data_iso, barbeiro):
    """Depois de um cancelamento: devolve quem está na espera daquele dia e marca como avisado."""
    with db.conexao() as con:
        rows = con.execute(
            """SELECT * FROM lista_espera WHERE data = ? AND avisado = 0
               AND (barbeiro IS NULL OR barbeiro = ?) ORDER BY id""",
            (data_iso, barbeiro),
        ).fetchall()
        avisar = []
        for r in rows:
            try:
                livres = horarios_livres(r["data"], r["servico"], r["barbeiro"])
            except ErroAgenda:
                continue
            horas = [h for hs in livres.get("livres_por_barbeiro", {}).values() for h in hs]
            if horas:
                con.execute("UPDATE lista_espera SET avisado = 1 WHERE id = ?", (r["id"],))
                avisar.append({"telefone": r["telefone"], "data": r["data"], "servico": r["servico"],
                               "horarios": sorted(set(horas))[:3]})
    return avisar


# ---------- fidelidade ----------
def fidelidade(telefone):
    meta = config.FIDELIDADE_META
    with db.conexao() as con:
        feitos = con.execute(
            """SELECT COUNT(*) FROM agendamentos WHERE telefone = ? AND status = 'confirmado'
               AND inicio < ?""",
            (telefone, agora().strftime(FMT)),
        ).fetchone()[0]
    no_ciclo = feitos % meta
    return {"atendimentos_feitos": feitos, "meta": meta,
            "faltam_para_brinde": meta - no_ciclo, "brinde": config.FIDELIDADE_BRINDE,
            "brinde_disponivel_agora": feitos > 0 and no_ciclo == 0}


# ---------- lembretes ----------
def lembretes_pendentes():
    """Agendamentos que precisam de lembrete (véspera às 18h+ e ~2h antes)."""
    n = agora()
    saida = []
    with db.conexao() as con:
        rows = con.execute(
            """SELECT * FROM agendamentos WHERE status = 'confirmado' AND inicio > ?
               AND (lembrete_vespera = 0 OR lembrete_proximo = 0)""",
            (n.strftime(FMT),),
        ).fetchall()
        for r in rows:
            ini = datetime.strptime(r["inicio"], FMT)
            falta = ini - n
            tipo = None
            if not r["lembrete_proximo"] and falta <= timedelta(hours=2):
                tipo = "proximo"
                con.execute("UPDATE agendamentos SET lembrete_proximo = 1, lembrete_vespera = 1 WHERE id = ?",
                            (r["id"],))
            elif (not r["lembrete_vespera"] and ini.date() == n.date() + timedelta(days=1)
                  and n.hour >= 18 and falta > timedelta(hours=2)):
                tipo = "vespera"
                con.execute("UPDATE agendamentos SET lembrete_vespera = 1 WHERE id = ?", (r["id"],))
            if tipo:
                saida.append({"tipo": tipo, "telefone": r["telefone"], "nome": r["nome_cliente"],
                              "servico": r["servico"], "barbeiro": r["barbeiro"],
                              "hora": ini.strftime("%H:%M"), "data": ini.strftime("%d/%m"),
                              "dia_semana": DIAS_SEMANA[ini.weekday()]})
    return saida


# ---------- visão do dono ----------
def agenda_do_dia(d: date):
    with db.conexao() as con:
        rows = con.execute(
            """SELECT id, inicio, barbeiro, servico, nome_cliente, telefone, preco FROM agendamentos
               WHERE status = 'confirmado' AND inicio LIKE ? ORDER BY barbeiro, inicio""",
            (d.isoformat() + "%",),
        ).fetchall()
    return [dict(r) for r in rows]
