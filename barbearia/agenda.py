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


def servicos():
    """Tabela atual (painel ou config.py): {nome: (preco, minutos)}."""
    return db.listar_servicos()


def achar_servico(nome):
    tabela = servicos()
    alvo = _normalizar(nome)
    for s in tabela:
        if _normalizar(s) == alvo:
            return s
    alvo = alvo.replace("+", "e")
    nomes = {s: _normalizar(s).replace("+", "e").split(" (")[0] for s in tabela}
    for s, ns in nomes.items():  # "platinado" -> "Luzes / Platinado"
        if alvo in ns:
            return s
    # "quero corte e barba" -> pega o nome mais longo contido no texto
    for s, ns in sorted(nomes.items(), key=lambda x: -len(x[1])):
        if ns in alvo:
            return s
    raise ErroAgenda(f"Serviço '{nome}' não existe. Serviços: {', '.join(tabela)}")


def barbeiros():
    """Equipe atual (painel ou config.py)."""
    return db.listar_barbeiros()


def achar_barbeiro(nome):
    if not nome:
        return None
    equipe = barbeiros()
    alvo = _normalizar(nome)
    for b in equipe:
        if _normalizar(b) == alvo:
            return b
    raise ErroAgenda(f"Não temos barbeiro chamado '{nome}'. Equipe: {', '.join(equipe)}")


def ler_data(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ErroAgenda("Data inválida, use o formato AAAA-MM-DD.") from None


def _proximo_dia_semana(alvo: int, a_partir: date | None = None) -> date:
    """Próxima ocorrência do weekday (0=segunda … 6=domingo), incluindo hoje."""
    base = a_partir or agora().date()
    delta = (alvo - base.weekday()) % 7
    return base + timedelta(days=delta)


def interpretar_data(txt: str) -> dict:
    """Converte 'hoje', 'amanhã', 'sábado', '21/11', '2026-11-21' em data + dia_semana corretos.

    Use SEMPRE antes de falar o dia da semana para o cliente — não invente.
    """
    if not txt or not str(txt).strip():
        raise ErroAgenda("Informe a data (ex.: sábado, amanhã, 21/11 ou 2026-11-21).")
    bruto = str(txt).strip()
    n = _normalizar(bruto)
    hoje = agora().date()

    if n in ("hoje", "hj"):
        d = hoje
    elif n.startswith("amanh"):
        d = hoje + timedelta(days=1)
    elif n in ("depois de amanha", "depois de amanhã"):
        d = hoje + timedelta(days=2)
    else:
        # AAAA-MM-DD
        try:
            d = ler_data(bruto[:10] if len(bruto) >= 10 and bruto[4] == "-" else bruto)
        except ErroAgenda:
            d = None
        # DD/MM ou DD/MM/AAAA
        if d is None and "/" in bruto:
            partes = bruto.replace("-", "/").split("/")
            try:
                dia, mes = int(partes[0]), int(partes[1])
                ano = int(partes[2]) if len(partes) >= 3 else hoje.year
                d = date(ano, mes, dia)
                if d < hoje and len(partes) < 3:
                    d = date(ano + 1, mes, dia)
            except (ValueError, IndexError):
                d = None
        # nome do dia da semana → próxima ocorrência
        if d is None:
            for i, nome in enumerate(DIAS_SEMANA):
                if _normalizar(nome) == n or n.startswith(_normalizar(nome)[:3]):
                    d = _proximo_dia_semana(i, hoje)
                    break
        if d is None:
            raise ErroAgenda(
                f"Não entendi a data '{txt}'. Use hoje, amanhã, um dia da semana "
                f"(sábado…), DD/MM ou AAAA-MM-DD."
            )

    aberto = expediente(d) is not None
    return {
        "ok": True,
        "pedido": bruto,
        "data": d.isoformat(),
        "dia_semana": DIAS_SEMANA[d.weekday()],
        "dd_mm": d.strftime("%d/%m"),
        "rotulo": (
            "hoje" if d == hoje else
            "amanhã" if d == hoje + timedelta(days=1) else
            DIAS_SEMANA[d.weekday()]
        ),
        "aberto": aberto,
        "texto": (
            f"{DIAS_SEMANA[d.weekday()]} {d.strftime('%d/%m/%Y')} ({d.isoformat()})"
            + (" — aberto" if aberto else " — FECHADO")
        ),
    }


def _hm(d: date, hhmm: str):
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def _bloqueios(d: date):
    with db.conexao() as con:
        rows = con.execute("SELECT barbeiro, motivo FROM bloqueios WHERE data = ?",
                           (d.isoformat(),)).fetchall()
    return [dict(r) for r in rows]


def motivo_fechado(d: date):
    """Se a barbearia inteira estiver bloqueada nesse dia (feriado etc.), devolve o motivo."""
    for b in _bloqueios(d):
        if b["barbeiro"] is None:
            return b["motivo"] or "fechado"
    return None


def expediente(d: date):
    """Retorna (abre, fecha) do dia ou None se fechado."""
    faixa = config.HORARIO_FUNCIONAMENTO.get(d.weekday())
    if not faixa or motivo_fechado(d):
        return None
    return _hm(d, faixa[0]), _hm(d, faixa[1])


def barbeiros_do_dia(d: date):
    if not expediente(d):
        return []
    de_folga = {b["barbeiro"] for b in _bloqueios(d) if b["barbeiro"]}
    return [b for b, info in barbeiros().items()
            if d.weekday() not in info.get("folgas", []) and b not in de_folga]


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


def _ocupados_detalhe(con, barbeiro, d: date) -> list[dict]:
    rows = con.execute(
        """SELECT inicio, fim, servico, nome_cliente FROM agendamentos
           WHERE barbeiro = ? AND status = 'confirmado' AND inicio LIKE ?
           ORDER BY inicio""",
        (barbeiro, d.isoformat() + "%"),
    ).fetchall()
    return [
        {
            "inicio": r["inicio"][11:16],
            "fim": r["fim"][11:16],
            "servico": r["servico"],
        }
        for r in rows
    ]


def horarios_livres(data_txt, servico, barbeiro=None):
    """Horários em que o serviço INTEIRO cabe — desconta o que já está marcado.

    Um slot só entra se início+duração não bater em outro atendimento, almoço,
    folga ou fora do expediente. Por isso "todos os vagos" depende do serviço.
    """
    d = ler_data(data_txt)
    servico = achar_servico(servico)
    barbeiro = achar_barbeiro(barbeiro)
    hoje = agora().date()
    if d < hoje:
        raise ErroAgenda("Essa data já passou.")
    if d > hoje + timedelta(days=config.DIAS_ANTECEDENCIA):
        raise ErroAgenda(f"Só abrimos agenda com até {config.DIAS_ANTECEDENCIA} dias de antecedência.")
    if not expediente(d):
        motivo = motivo_fechado(d)
        return {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()], "fechado": True,
                "mensagem": f"A barbearia não abre nesse dia{f' ({motivo})' if motivo else ''}."}

    preco, mins = servicos()[servico]
    duracao = timedelta(minutes=mins)
    passo = timedelta(minutes=config.INTERVALO_AGENDA)
    equipe = [barbeiro] if barbeiro else barbeiros_do_dia(d)
    if barbeiro and barbeiro not in barbeiros_do_dia(d):
        return {"data": d.isoformat(), "dia_semana": DIAS_SEMANA[d.weekday()],
                "mensagem": f"{barbeiro} está de folga nesse dia.",
                "outros_barbeiros_no_dia": barbeiros_do_dia(d)}

    abre, fecha = expediente(d)
    livres_por = {}
    ocupados_por = {}
    with db.conexao() as con:
        for b in equipe:
            ocup = _ocupados(con, b, d)
            ocupados_por[b] = _ocupados_detalhe(con, b, d)
            livres, t = [], abre
            while t + duracao <= fecha:
                if _cabe(t, t + duracao, d, ocup):
                    livres.append(t.strftime("%H:%M"))
                t += passo
            livres_por[b] = livres

    total_livres = sum(len(v) for v in livres_por.values())
    return {
        "data": d.isoformat(),
        "dia_semana": DIAS_SEMANA[d.weekday()],
        "servico": servico,
        "preco": preco,
        "duracao_min": mins,
        "intervalo_min": config.INTERVALO_AGENDA,
        "livres_por_barbeiro": livres_por,
        "ocupados_por_barbeiro": ocupados_por,
        "total_livres": total_livres,
        "regra": (
            f"Só entram horários em que o serviço '{servico}' ({mins} min) cabe inteiro, "
            "sem sobrepor atendimento já marcado, almoço ou fechamento. "
            "Nunca invente horário fora de livres_por_barbeiro."
        ),
    }


def _minutos_hm(hora: str) -> int:
    h, m = hora.strip().split(":")[:2]
    return int(h) * 60 + int(m)


def checar_horario_pedido(data_txt, hora: str, servico, barbeiro=None) -> dict:
    """Para o dono marcar um cliente: livre? se não, mais próximo + vagos até fechar."""
    try:
        hora_norm = datetime.strptime(hora.strip()[:5], "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ErroAgenda("Hora inválida, use HH:MM (ex.: 15:00).") from exc

    base = horarios_livres(data_txt, servico, barbeiro)
    if base.get("fechado") or "livres_por_barbeiro" not in base:
        return base

    livres_por = base["livres_por_barbeiro"]
    ocupados_por = base.get("ocupados_por_barbeiro") or {}
    pedida = _minutos_hm(hora_norm)
    por_barbeiro = {}
    for b, livres in livres_por.items():
        livre = hora_norm in livres
        ate_fechar = [h for h in livres if _minutos_hm(h) >= pedida]
        # Mais próximo: prefere o próximo livre daí pra frente; senão o último antes.
        mais_proximo = None
        if ate_fechar:
            mais_proximo = ate_fechar[0]
        elif livres:
            mais_proximo = livres[-1]
        if not ate_fechar:
            ate_fechar = list(livres)
        quem = None
        if not livre:
            for o in ocupados_por.get(b) or []:
                ini, fim = _minutos_hm(o["inicio"]), _minutos_hm(o["fim"])
                if ini <= pedida < fim:
                    quem = o
                    break
        por_barbeiro[b] = {
            "livre": livre,
            "hora_pedida": hora_norm,
            "ocupado_com": quem,
            "mais_proximo": mais_proximo,
            "livres_ate_fechar": ate_fechar,
        }

    algum_livre = any(v["livre"] for v in por_barbeiro.values())
    return {
        **{k: base[k] for k in ("data", "dia_semana", "servico", "preco", "duracao_min")},
        "hora_pedida": hora_norm,
        "livre": algum_livre,
        "por_barbeiro": por_barbeiro,
        "regra": (
            "Se livre=true, confirme com o dono e use agendar_para_cliente. "
            "Se livre=false, fale o mais_proximo e liste livres_ate_fechar; "
            "só marque depois que ele aprovar um horário."
        ),
    }


def agendar(telefone, nome_cliente, data_txt, hora, servico, barbeiro=None):
    d = ler_data(data_txt)
    servico = achar_servico(servico)
    barbeiro = achar_barbeiro(barbeiro)
    try:
        inicio = _hm(d, hora)
    except (ValueError, AttributeError):
        raise ErroAgenda("Hora inválida, use HH:MM.") from None
    if not expediente(d):
        raise ErroAgenda("A barbearia não abre nesse dia.")
    preco, minutos = servicos()[servico]
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
            if tipo and db.aceita_mensagens(r["telefone"]) and not db.eh_sem_bot(r["telefone"]):
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


def resumo_dias(inicio: date | None = None, dias: int = 7) -> list[dict]:
    """Contagem e total (R$) por dia, a partir de `inicio` (padrão: hoje)."""
    base = inicio or agora().date()
    dias = max(1, min(int(dias), 31))
    saida = []
    with db.conexao() as con:
        for i in range(dias):
            d = base + timedelta(days=i)
            row = con.execute(
                """SELECT COUNT(*) AS n, COALESCE(SUM(preco), 0) AS total FROM agendamentos
                   WHERE status = 'confirmado' AND inicio LIKE ?""",
                (d.isoformat() + "%",),
            ).fetchone()
            saida.append({
                "data": d,
                "iso": d.isoformat(),
                "dd_mm": d.strftime("%d/%m"),
                "dia_semana": DIAS_SEMANA[d.weekday()],
                "quantidade": int(row["n"] or 0),
                "total": float(row["total"] or 0),
            })
    return saida


# ---------- bloqueios (folga, feriado) ----------
def bloquear(data_txt, barbeiro=None, motivo=None):
    d = ler_data(data_txt)
    barbeiro = achar_barbeiro(barbeiro)
    with db.conexao() as con:
        con.execute("INSERT INTO bloqueios (data, barbeiro, motivo) VALUES (?, ?, ?)",
                    (d.isoformat(), barbeiro, motivo))
        afetados = con.execute(
            """SELECT id, telefone, nome_cliente, barbeiro, servico, inicio FROM agendamentos
               WHERE status = 'confirmado' AND inicio LIKE ? AND (? IS NULL OR barbeiro = ?)""",
            (d.isoformat() + "%", barbeiro, barbeiro),
        ).fetchall()
    return [dict(r) for r in afetados]  # o dono precisa remarcar esses clientes


def desbloquear(data_txt, barbeiro=None):
    d = ler_data(data_txt)
    barbeiro = achar_barbeiro(barbeiro)
    with db.conexao() as con:
        if barbeiro:
            n = con.execute("DELETE FROM bloqueios WHERE data = ? AND barbeiro = ?",
                            (d.isoformat(), barbeiro)).rowcount
        else:
            n = con.execute("DELETE FROM bloqueios WHERE data = ? AND barbeiro IS NULL",
                            (d.isoformat(),)).rowcount
    return n


# ---------- avaliação pós-atendimento ----------
def avaliacoes_pendentes():
    """Atendimentos que terminaram há 1h+ (até 2 dias) e ainda não pediram avaliação."""
    n = agora()
    saida = []
    with db.conexao() as con:
        rows = con.execute(
            """SELECT * FROM agendamentos WHERE status = 'confirmado' AND pedido_avaliacao = 0
               AND fim <= ? AND fim >= ?""",
            ((n - timedelta(hours=1)).strftime(FMT), (n - timedelta(days=2)).strftime(FMT)),
        ).fetchall()
        for r in rows:
            con.execute("UPDATE agendamentos SET pedido_avaliacao = 1 WHERE id = ?", (r["id"],))
            if db.aceita_mensagens(r["telefone"]):
                saida.append({"id": r["id"], "telefone": r["telefone"], "nome": r["nome_cliente"],
                              "barbeiro": r["barbeiro"], "servico": r["servico"]})
    return saida


def registrar_avaliacao(telefone, nota, comentario=None):
    nota = int(nota)
    if not 1 <= nota <= 5:
        raise ErroAgenda("A nota precisa ser de 1 a 5.")
    with db.conexao() as con:
        row = con.execute(
            """SELECT id, barbeiro FROM agendamentos WHERE telefone = ? AND status = 'confirmado'
               AND inicio <= ? ORDER BY inicio DESC LIMIT 1""",
            (telefone, agora().strftime(FMT)),
        ).fetchone()
        if not row:
            raise ErroAgenda("Não achei atendimento recente desse cliente para avaliar.")
        con.execute("UPDATE agendamentos SET nota = ?, comentario = ? WHERE id = ?",
                    (nota, comentario, row["id"]))
    return {"ok": True, "barbeiro": row["barbeiro"], "nota": nota}


def resumo_avaliacoes(dias=30):
    desde = (agora() - timedelta(days=dias)).strftime(FMT)
    with db.conexao() as con:
        por_barbeiro = con.execute(
            """SELECT barbeiro, ROUND(AVG(nota), 1) AS media, COUNT(nota) AS total
               FROM agendamentos WHERE nota IS NOT NULL AND inicio >= ?
               GROUP BY barbeiro ORDER BY media DESC""", (desde,)).fetchall()
        comentarios = con.execute(
            """SELECT nome_cliente, barbeiro, nota, comentario FROM agendamentos
               WHERE comentario IS NOT NULL AND comentario != '' AND inicio >= ?
               ORDER BY inicio DESC LIMIT 10""", (desde,)).fetchall()
    return {"por_barbeiro": [dict(r) for r in por_barbeiro],
            "comentarios": [dict(r) for r in comentarios]}
