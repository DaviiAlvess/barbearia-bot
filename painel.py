"""Painel web Agendbarber: agenda, salão, QR do WhatsApp.

Rodar:  uvicorn painel:app --port 8080
Abrir:  http://localhost:8080  (senha: PAINEL_SENHA do .env)
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import os
import secrets
import time
from datetime import timedelta
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

load_dotenv()

import config  # noqa: E402
from barbearia import agenda, db  # noqa: E402
from barbearia import evolution as evo  # noqa: E402

app = FastAPI(title=f"{config.NOME_APP} — Painel", docs_url=None, redoc_url=None)
db.criar_tabelas()

COOKIE_SESSAO = "painel_sessao"
SESSAO_DIAS = 7


class PrecisaLogin(Exception):
    """Redireciona para /login (em vez de JSON do HTTP Basic)."""


e = html.escape  # nunca colocar texto do cliente no HTML sem escapar

# Tipografia: Cormorant (marca) + Manrope (UI). Paleta navalha: carvão + ouro.
ESTILO = """
:root{
  --ink:#141210;--paper:#f3eee6;--panel:#fffcf7;--line:#e4dcd0;
  --gold:#c9a227;--gold-soft:#f0e2b0;--muted:#6f675c;--danger:#a33b32;--ok:#2f6b45;
}
*{box-sizing:border-box}
body{
  margin:0;color:var(--ink);
  font-family:"Manrope",system-ui,sans-serif;
  background:
    radial-gradient(900px 420px at 10% -10%,#efe6d4 0%,transparent 55%),
    radial-gradient(700px 380px at 100% 0%,#e8dfc8 0%,transparent 50%),
    var(--paper);
  min-height:100vh;
}
header{
  background:linear-gradient(180deg,#1a1714 0%,#12100e 100%);
  color:var(--gold-soft);padding:18px 20px 16px;
  border-bottom:1px solid #2a2621;
}
header .brand{
  font-family:"Cormorant Garamond",Georgia,serif;
  font-size:clamp(1.45rem,4vw,1.85rem);font-weight:600;letter-spacing:.02em;margin:0;
}
header .sub{margin:4px 0 0;font-size:.78rem;color:#9a9184;font-weight:500;letter-spacing:.08em;text-transform:uppercase}
main{max-width:920px;margin:0 auto;padding:18px 16px 40px}
.nav{
  display:flex;gap:8px;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
  padding:10px 4px 14px;margin:0 0 8px;scrollbar-width:none;
}
.nav::-webkit-scrollbar{display:none}
.nav a{
  flex:0 0 auto;text-decoration:none;color:var(--ink);font-size:.9rem;font-weight:600;
  padding:8px 12px;border:1px solid transparent;border-radius:999px;white-space:nowrap;
}
.nav a:hover{background:#ebe4d8}
.nav a.sair{margin-left:auto;color:var(--muted);font-weight:500}
.card{
  background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:18px;margin-bottom:14px;
}
.card h2,.card h3{
  font-family:"Cormorant Garamond",Georgia,serif;font-weight:600;margin:0 0 12px;
  font-size:1.45rem;letter-spacing:.01em;
}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px}
.toolbar a{color:var(--ink);text-decoration:none;font-size:1.2rem;padding:4px 8px}
.toolbar b{font-size:1rem}
.toolbar form{display:flex;gap:8px;align-items:center;margin:0}
.toolbar input[type=date]{width:auto;margin:0;padding:8px 10px}
.semana{
  display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;
  padding:4px 0 12px;margin:0 0 4px;scrollbar-width:none;
}
.semana::-webkit-scrollbar{display:none}
.semana a{
  flex:1 0 3.4rem;min-width:3.4rem;text-align:center;text-decoration:none;color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:8px 4px;background:#fff;
  font-size:.78rem;font-weight:600;line-height:1.25;
}
.semana a:hover{background:#ebe4d8}
.semana a.hoje{border-color:var(--gold);box-shadow:inset 0 0 0 1px var(--gold-soft)}
.semana a.ativo{background:var(--ink);color:#f7f1e6;border-color:var(--ink)}
.semana a .n{display:block;font-size:1.05rem;font-weight:700;margin-top:2px}
.semana a .vazio-dia{color:var(--muted);font-weight:500}
.semana a.ativo .vazio-dia{color:#cfc6b8}
table{width:100%;border-collapse:collapse}
td,th{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700}
td small{color:var(--muted)}
button{
  background:var(--ink);color:#f7f1e6;border:0;border-radius:10px;
  padding:10px 16px;cursor:pointer;font:600 .95rem "Manrope",system-ui,sans-serif;
}
button:hover{filter:brightness(1.08)}
button.perigo{background:var(--danger);padding:8px 12px;font-size:.85rem}
button.largo{width:100%}
input,select{
  padding:11px 12px;border:1px solid var(--line);border-radius:10px;
  font:500 1rem "Manrope",system-ui,sans-serif;width:100%;margin:6px 0 12px;
  background:#fff;color:var(--ink);
}
label{font-size:.82rem;font-weight:650;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.total{font-size:1.05rem;font-weight:700;margin:4px 0 12px}
.vazio{color:var(--muted)}.ok{color:var(--ok);font-weight:700}
.aviso{color:#8a6a1f}.erro{color:var(--danger);font-weight:600}
.qr{
  display:block;margin:18px auto;max-width:300px;width:100%;
  background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px;
}
.passos{line-height:1.65;padding-left:1.2rem;color:#3a342c}
.login-wrap{min-height:70vh;display:grid;place-items:center;padding:12px}
.login-box{width:100%;max-width:380px;margin:0}
.login-box .hint{margin:14px 0 0;font-size:.85rem;color:var(--muted);line-height:1.45}
.form-row{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
.form-row > *{flex:1 1 140px;margin:0}
.form-row button{flex:0 0 auto;margin-bottom:12px}
@media(max-width:560px){
  td,th{padding:8px 6px;font-size:.9rem}
  .card{padding:14px}
}
"""


def _segredo() -> bytes:
    senha = os.getenv("PAINEL_SENHA") or ""
    return hashlib.sha256(f"barbearia-painel|{senha}".encode()).digest()


def _token_sessao() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(_segredo(), f"dono|{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def _sessao_ok(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    ts, sig = token.split(".", 1)
    esperado = hmac.new(_segredo(), f"dono|{ts}".encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, esperado):
        return False
    try:
        return int(time.time()) - int(ts) < SESSAO_DIAS * 86400
    except ValueError:
        return False


def autenticar(request: Request) -> None:
    if not os.getenv("PAINEL_SENHA"):
        raise HTTPException(503, "Defina PAINEL_SENHA no .env para usar o painel.")
    if not _sessao_ok(request.cookies.get(COOKIE_SESSAO)):
        raise PrecisaLogin()


@app.exception_handler(PrecisaLogin)
def precisa_login(request: Request, _exc: PrecisaLogin):
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    return RedirectResponse(f"/login?next={quote(nxt, safe='/')}", status_code=303)


@app.exception_handler(agenda.ErroAgenda)
def erro_agenda(_request, exc: agenda.ErroAgenda):
    return pagina("Erro", f"<div class=card><p>⚠️ {e(str(exc))}</p><a href=/>Voltar</a></div>")


def pagina(titulo: str, corpo: str, *, refresh: int | None = None, logado: bool = True) -> HTMLResponse:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    nav = ""
    if logado:
        nav = """<nav class="nav" aria-label="Principal">
<a href="/">Agenda</a><a href="/bloqueios">Folgas</a>
<a href="/avaliacoes">Avaliações</a><a href="/servicos">Serviços</a>
<a href="/profissionais">Profissionais</a>
<a href="/whatsapp">WhatsApp</a>
<a href="/salao">Salão</a>
<a href="/sem-chat">Sem chat</a>
<a class="sair" href="/sair">Sair</a></nav>"""
    salao = db.nome_salao()
    return HTMLResponse(f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{e(titulo)} · {e(config.NOME_APP)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&amp;family=Manrope:wght@500;600;700&amp;display=swap"
 rel="stylesheet">
<style>{ESTILO}</style></head><body>
<header>
  <p class="brand">{e(config.NOME_APP)}</p>
  <p class="sub">{e(salao)}</p>
</header>
<main>{nav}{corpo}</main></body></html>""")


def _status_whatsapp() -> dict:
    try:
        return evo.status_para_painel()
    except Exception as exc:  # noqa: BLE001
        return {"conectado": False, "temQr": False, "erro": str(exc)}


def _corpo_login(next: str, erro: str = "") -> str:
    msg = f'<p class="erro">{e(erro)}</p>' if erro else ""
    return f"""<div class="login-wrap"><div class="card login-box">
    <h2>Entrar</h2>
    {msg}
    <form method=post action=/login>
    <input type=hidden name=next value="{e(next)}">
    <label for=senha>Senha</label>
    <input id=senha type=password name=senha required autocomplete=current-password autofocus>
    <button class="largo" type=submit>Entrar</button>
    </form>
    <p class="hint">{e(config.NOME_APP)} — painel do salão.</p>
    </div></div>"""


@app.get("/login")
def login_form(next: str = "/"):
    return pagina("Entrar", _corpo_login(next), logado=False)


@app.post("/login")
def login_post(request: Request, senha: str = Form(...), next: str = Form("/")):
    esperada = os.getenv("PAINEL_SENHA") or ""
    if not esperada or not secrets.compare_digest(senha, esperada):
        return pagina("Entrar", _corpo_login(next, "Senha incorreta."), logado=False)
    destino = next if next.startswith("/") else "/"
    resp = RedirectResponse(destino, status_code=303)
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    resp.set_cookie(
        COOKIE_SESSAO, _token_sessao(),
        httponly=True, samesite="lax", secure=(proto == "https"),
        max_age=SESSAO_DIAS * 86400,
    )
    return resp


@app.get("/sair")
def sair():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_SESSAO)
    return resp


@app.get("/", dependencies=[Depends(autenticar)])
def ver_agenda(data: str | None = None):
    hoje = agenda.agora().date()
    d = agenda.ler_data(data) if data else hoje
    itens = agenda.agenda_do_dia(d)
    total = sum(i["preco"] or 0 for i in itens)
    linhas = "".join(
        f"<tr><td>{e(i['inicio'][11:])}</td><td>{e(i['barbeiro'])}</td><td>{e(i['servico'])}</td>"
        f"<td>{e(i['nome_cliente'] or '')}<br><small>{e(i['telefone'])}</small></td>"
        f"<td>R$ {i['preco'] or 0:.2f}</td><td><form method=post action=/cancelar "
        f"onsubmit=\"return confirm('Cancelar este horário?')\"><input type=hidden name=id value={i['id']}>"
        f"<input type=hidden name=data value={d.isoformat()}><button class=perigo>Cancelar</button>"
        f"</form></td></tr>" for i in itens)
    anterior, proximo = d - timedelta(days=1), d + timedelta(days=1)
    # Faixa da semana: 3 dias antes … 10 dias depois do dia aberto (fácil pular)
    inicio_faixa = d - timedelta(days=3)
    faixa = agenda.resumo_dias(inicio=inicio_faixa, dias=14)
    chips = []
    for r in faixa:
        classes = []
        if r["data"] == d:
            classes.append("ativo")
        if r["data"] == hoje:
            classes.append("hoje")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        qtd = (
            f'<span class=n>{r["quantidade"]}</span>'
            if r["quantidade"]
            else '<span class="n vazio-dia">·</span>'
        )
        chips.append(
            f'<a href="/?data={r["iso"]}"{cls}>'
            f'{r["dia_semana"][:3]}<br>{r["dd_mm"]}{qtd}</a>'
        )
    semana_html = '<div class=semana role=navigation aria-label="Outros dias">' + "".join(chips) + "</div>"
    corpo = f"""<div class=card>
    <div class=toolbar>
      <a href="/?data={anterior.isoformat()}" aria-label="Dia anterior">‹</a>
      <b>{agenda.DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m/%Y')}</b>
      <a href="/?data={proximo.isoformat()}" aria-label="Próximo dia">›</a>
      <a href="/?data={hoje.isoformat()}">Hoje</a>
      <form method=get action=/><input type=date name=data value="{d.isoformat()}"><button type=submit>Ir</button></form>
    </div>
    {semana_html}
    <p class=total>{len(itens)} atendimentos · R$ {total:.2f}</p>
    {"<table><tr><th>Hora</th><th>Barbeiro</th><th>Serviço</th><th>Cliente</th><th>Valor</th><th></th></tr>"
     + linhas + "</table>" if itens else
     "<p class=vazio>Nenhum horário neste dia. Toque em outro dia acima.</p>"}</div>"""
    if db.nome_salao() in ("Meu Salão", ""):
        corpo = (
            '<div class="card"><p class="aviso">Defina o nome do seu salão em '
            '<a href="/salao"><b>Salão</b></a>.</p></div>' + corpo
        )
    return pagina("Agenda", corpo)


@app.post("/cancelar", dependencies=[Depends(autenticar)])
def cancelar(id: int = Form(...), data: str = Form(...)):
    with db.conexao() as con:
        row = con.execute("SELECT telefone FROM agendamentos WHERE id = ?", (id,)).fetchone()
    if row:
        agenda.cancelar(row["telefone"], id)
    return RedirectResponse(f"/?data={data}", status_code=303)


@app.get("/bloqueios", dependencies=[Depends(autenticar)])
def ver_bloqueios():
    with db.conexao() as con:
        rows = con.execute("SELECT * FROM bloqueios WHERE data >= ? ORDER BY data",
                           (agenda.agora().date().isoformat(),)).fetchall()
    linhas = "".join(
        f"<tr><td>{e(r['data'])}</td><td>{e(r['barbeiro'] or 'Barbearia toda')}</td>"
        f"<td>{e(r['motivo'] or '')}</td><td><form method=post action=/desbloquear>"
        f"<input type=hidden name=data value={e(r['data'])}>"
        f"<input type=hidden name=barbeiro value=\"{e(r['barbeiro'] or '')}\"><button>Remover</button>"
        f"</form></td></tr>" for r in rows)
    opcoes = "".join(f"<option>{e(b)}</option>" for b in db.listar_barbeiros())
    corpo = f"""<div class=card><h3>Fechar dia ou dar folga</h3>
    <form method=post action=/bloquear class=form-row>
    <div><label>Data</label><input type=date name=data required></div>
    <div><label>Quem</label><select name=barbeiro><option value="">Barbearia toda</option>{opcoes}</select></div>
    <div><label>Motivo</label><input name=motivo placeholder="Opcional"></div>
    <button type=submit>Bloquear</button></form></div>
    <div class=card><h3>Próximos bloqueios</h3>{"<table><tr><th>Data</th><th>Quem</th><th>Motivo</th><th></th></tr>"
    + linhas + "</table>" if rows else "<p class=vazio>Nenhum bloqueio à frente.</p>"}</div>"""
    return pagina("Folgas e feriados", corpo)


@app.post("/bloquear", dependencies=[Depends(autenticar)])
def bloquear(data: str = Form(...), barbeiro: str = Form(""), motivo: str = Form("")):
    afetados = agenda.bloquear(data, barbeiro or None, motivo or None)
    if not afetados:
        return RedirectResponse("/bloqueios", status_code=303)
    lista = "".join(f"<li>{e(a['inicio'])} - {e(a['barbeiro'])} - {e(a['nome_cliente'] or '')} "
                    f"({e(a['telefone'])})</li>" for a in afetados)
    return pagina("Atenção", f"<div class=card><h3>Bloqueado, mas já tinha gente marcada</h3>"
                             f"<p>Fale com esses clientes para remarcar:</p><ul>{lista}</ul>"
                             f"<a href=/bloqueios>Voltar</a></div>")


@app.post("/desbloquear", dependencies=[Depends(autenticar)])
def desbloquear(data: str = Form(...), barbeiro: str = Form("")):
    agenda.desbloquear(data, barbeiro or None)
    return RedirectResponse("/bloqueios", status_code=303)


@app.get("/salao", dependencies=[Depends(autenticar)])
def ver_salao(ok: str | None = None, erro: str | None = None):
    nome = db.nome_salao()
    end = db.endereco()
    msg = ""
    if ok:
        msg = '<p class="ok">Dados do salão salvos. O WhatsApp já usa nome e endereço.</p>'
    if erro:
        msg = f'<p class="erro">{e(erro)}</p>'
    corpo = f"""<div class=card>
    <h2>Seu salão</h2>
    <p class=vazio>Nome e endereço aparecem no painel, nas conversas e nos lembretes do WhatsApp
    (o app continua sendo {e(config.NOME_APP)}).</p>
    {msg}
    <form method=post action=/salao>
      <label for=nome>Nome do salão</label>
      <input id=nome name=nome maxlength=80 required value="{e(nome)}"
       placeholder="Ex.: Barbearia Navalha de Ouro">
      <label for=endereco>Endereço</label>
      <input id=endereco name=endereco maxlength=200 required value="{e(end)}"
       placeholder="Ex.: Rua Exemplo, 123 - Centro">
      <button type=submit>Salvar</button>
    </form>
    </div>"""
    return pagina("Salão", corpo)


@app.post("/salao", dependencies=[Depends(autenticar)])
def salvar_salao(nome: str = Form(...), endereco: str = Form(...)):
    nome = (nome or "").strip()[:80]
    if not nome:
        return RedirectResponse("/salao?erro=" + quote("Informe o nome do salão."), status_code=303)
    try:
        db.salvar_config("nome_salao", nome)
        db.salvar_endereco(endereco)
    except ValueError as exc:
        return RedirectResponse("/salao?erro=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/salao?ok=1", status_code=303)


@app.get("/sem-chat", dependencies=[Depends(autenticar)])
def ver_sem_chat(ok: str | None = None, erro: str | None = None):
    """Números particulares: o bot não responde (amiga, família, etc.)."""
    msg = ""
    if ok == "add":
        msg = '<p class="ok">Número adicionado. O bot não vai mais responder essa conversa.</p>'
    elif ok == "rm":
        msg = '<p class="ok">Número removido. O bot volta a atender se a pessoa mandar mensagem.</p>'
    elif ok:
        msg = '<p class="ok">Salvo.</p>'
    if erro:
        msg = f'<p class="erro">{e(erro)}</p>'
    itens = db.listar_sem_bot()
    linhas = ""
    forms_rm = ""
    for i, item in enumerate(itens):
        fid = f"rm{i}"
        nome = e(item.get("nome") or "—")
        tel = e(item["telefone"])
        forms_rm += (
            f'<form id="{fid}" method=post action=/sem-chat/remover style="display:none">'
            f'<input type=hidden name=telefone value="{tel}"></form>'
        )
        linhas += (
            f"<tr><td>{tel}</td><td>{nome}</td>"
            f'<td><button class=perigo type=submit form="{fid}">Tirar</button></td></tr>'
        )
    tabela = (
        f"{forms_rm}<table><tr><th>Telefone</th><th>Quem</th><th></th></tr>{linhas}</table>"
        if itens else
        '<p class="vazio">Nenhum número ainda. Adicione amigos, família ou quem você '
        "quer atender na mão — o bot fica quieto.</p>"
    )
    corpo = f"""<div class=card>
    <h2>Sem chat (particular)</h2>
    <p class=vazio>Números nesta lista <b>não recebem resposta do bot</b>.
    Use para conversar com amiga, amigo, família etc. sem o atendimento automático entrar.
    Também dá pelo WhatsApp do dono: <code>#semchat 75999990000 Maria</code></p>
    {msg}
    {tabela}
    </div>
    <div class=card>
    <h3>Adicionar número</h3>
    <form method=post action=/sem-chat/adicionar class=form-row>
      <div><label>Telefone (com DDD)</label>
      <input name=telefone required placeholder="75999990000" inputmode=numeric></div>
      <div><label>Nome (opcional)</label>
      <input name=nome maxlength=60 placeholder="Ex.: Maria"></div>
      <div style="align-self:end"><button type=submit>Adicionar</button></div>
    </form>
    </div>"""
    return pagina("Sem chat", corpo)


@app.post("/sem-chat/adicionar", dependencies=[Depends(autenticar)])
def adicionar_sem_chat(telefone: str = Form(...), nome: str = Form("")):
    try:
        db.adicionar_sem_bot(telefone, nome)
    except ValueError as exc:
        return RedirectResponse("/sem-chat?erro=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/sem-chat?ok=add", status_code=303)


@app.post("/sem-chat/remover", dependencies=[Depends(autenticar)])
def remover_sem_chat(telefone: str = Form(...)):
    if not db.remover_sem_bot(telefone):
        return RedirectResponse(
            "/sem-chat?erro=" + quote("Número não encontrado."), status_code=303,
        )
    return RedirectResponse("/sem-chat?ok=rm", status_code=303)


DIAS_FOLGA = [
    (0, "Seg"), (1, "Ter"), (2, "Qua"), (3, "Qui"),
    (4, "Sex"), (5, "Sáb"), (6, "Dom"),
]


@app.get("/profissionais", dependencies=[Depends(autenticar)])
def ver_profissionais(ok: str | None = None, erro: str | None = None):
    equipe = list(db.listar_barbeiros().items())
    msg = ""
    if ok == "1":
        msg = '<p class="ok">Equipe salva. O WhatsApp já usa esses profissionais.</p>'
    elif ok == "add":
        msg = '<p class="ok">Profissional adicionado.</p>'
    elif ok == "rm":
        msg = '<p class="ok">Profissional removido.</p>'
    if erro:
        msg = f'<p class="erro">{e(erro)}</p>'

    forms_rm = ""
    linhas = ""
    for i, (n, info) in enumerate(equipe):
        fid = f"rm-{i}"
        folgas = set(info.get("folgas") or [])
        checks = "".join(
            f'<label style="display:inline;margin-right:8px;text-transform:none;letter-spacing:0">'
            f'<input type=checkbox name="folga_{i}" value="{d}" form="equipe"'
            f'{" checked" if d in folgas else ""}> {rot}</label>'
            for d, rot in DIAS_FOLGA
        )
        forms_rm += (
            f'<form id="{fid}" method=post action=/profissionais/remover style="display:none">'
            f'<input type=hidden name=nome value="{e(n)}"></form>'
        )
        linhas += (
            f'<tr><td><input name="nome" form="equipe" value="{e(n)}" required maxlength=60></td>'
            f'<td><input name="especialidade" form="equipe" value="{e(info.get("especialidade") or "")}" '
            f'maxlength=80 placeholder="Ex.: degradê"></td>'
            f'<td>{checks}</td>'
            f'<td><button class=perigo type=submit form="{fid}" '
            f"onclick=\"return confirm('Remover {e(n)} da equipe?')\">Remover</button></td></tr>"
        )

    if equipe:
        tabela = (
            f'{forms_rm}<form id="equipe" method=post action=/profissionais></form>'
            f'<table><tr><th>Nome</th><th>Especialidade</th><th>Folgas</th><th></th></tr>'
            f'{linhas}</table>'
            f'<p style="margin-top:14px"><button type=submit form="equipe">Salvar alterações</button></p>'
        )
    else:
        tabela = '<p class=aviso>Nenhum profissional cadastrado. Adicione o primeiro abaixo.</p>'

    corpo = f"""<div class=card>
    <h2>Profissionais</h2>
    <p class=vazio>Adicione ou remova quem atende. O bot usa esta lista no WhatsApp.
    Folgas: dias da semana em que a pessoa não trabalha.</p>
    {msg}
    {tabela}
    </div>
    <div class=card>
    <h3>Adicionar profissional</h3>
    <form method=post action=/profissionais/adicionar class=form-row>
      <div><label>Nome</label><input name=nome maxlength=60 required placeholder="Ex.: Rafael"></div>
      <div><label>Especialidade</label><input name=especialidade maxlength=80
       placeholder="Ex.: degradê e navalhado"></div>
      <button type=submit>Adicionar</button>
    </form>
    </div>"""
    return pagina("Profissionais", corpo)


@app.post("/profissionais", dependencies=[Depends(autenticar)])
async def salvar_profissionais_painel(request: Request):
    form = await request.form()
    nomes = form.getlist("nome")
    especialidades = form.getlist("especialidade")
    itens: list[dict] = []
    for i, nome in enumerate(nomes):
        nome = (nome or "").strip()
        if not nome:
            continue
        esp = especialidades[i] if i < len(especialidades) else ""
        vals = form.getlist(f"folga_{i}")
        folgas = []
        for v in vals:
            with contextlib.suppress(ValueError):
                folgas.append(int(v))
        itens.append({"nome": nome[:60], "especialidade": (esp or "").strip()[:80], "folgas": folgas})
    try:
        db.salvar_barbeiros(itens)
    except ValueError as exc:
        return RedirectResponse("/profissionais?erro=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/profissionais?ok=1", status_code=303)


@app.post("/profissionais/adicionar", dependencies=[Depends(autenticar)])
def adicionar_profissional(nome: str = Form(...), especialidade: str = Form("")):
    try:
        db.adicionar_barbeiro(nome, especialidade)
    except ValueError as exc:
        return RedirectResponse("/profissionais?erro=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/profissionais?ok=add", status_code=303)


@app.post("/profissionais/remover", dependencies=[Depends(autenticar)])
def remover_profissional(nome: str = Form(...)):
    try:
        if not db.remover_barbeiro(nome):
            return RedirectResponse(
                "/profissionais?erro=" + quote("Profissional não encontrado."),
                status_code=303,
            )
    except ValueError as exc:
        return RedirectResponse("/profissionais?erro=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/profissionais?ok=rm", status_code=303)


@app.get("/servicos", dependencies=[Depends(autenticar)])
def ver_servicos(ok: str | None = None, erro: str | None = None):
    """Tabela de serviços e preços — o bot WhatsApp usa estes valores."""
    tabela = db.listar_servicos()
    msg = ""
    if ok:
        msg = '<p class="ok">Tabela de serviços salva. O atendente do WhatsApp já usa esses valores.</p>'
    if erro:
        msg = f'<p class="erro">{e(erro)}</p>'
    linhas = "".join(
        f'<tr><td><input name="nome" value="{e(n)}" required maxlength=80></td>'
        f'<td><input name="preco" type="number" step="0.01" min="0" value="{p:.2f}" required></td>'
        f'<td><input name="minutos" type="number" step="5" min="5" value="{m}" required></td></tr>'
        for n, (p, m) in tabela.items()
    )
    # 2 linhas vazias para novos serviços
    for _ in range(2):
        linhas += (
            '<tr><td><input name="nome" maxlength=80 placeholder="Novo serviço"></td>'
            '<td><input name="preco" type="number" step="0.01" min="0" placeholder="0,00"></td>'
            '<td><input name="minutos" type="number" step="5" min="5" placeholder="30"></td></tr>'
        )
    corpo = f"""<div class=card>
    <h2>Serviços e preços</h2>
    <p class=vazio>O Léo no WhatsApp consulta esta tabela quando o cliente pergunta valores
    ou marca um horário. Deixe o nome em branco numa linha para removê-la.</p>
    {msg}
    <form method=post action=/servicos>
    <table>
      <tr><th>Serviço</th><th>Preço (R$)</th><th>Duração (min)</th></tr>
      {linhas}
    </table>
    <button type=submit>Salvar tabela</button>
    </form>
    </div>"""
    return pagina("Serviços", corpo)


@app.post("/servicos", dependencies=[Depends(autenticar)])
async def salvar_servicos_painel(request: Request):
    form = await request.form()
    nomes = form.getlist("nome")
    precos = form.getlist("preco")
    minutos = form.getlist("minutos")
    itens: list[dict] = []
    for nome, preco, mins in zip(nomes, precos, minutos, strict=False):
        nome = (nome or "").strip()
        if not nome:
            continue
        try:
            itens.append({
                "nome": nome[:80],
                "preco": float(str(preco).replace(",", ".")),
                "minutos": int(float(str(mins))),
            })
        except (TypeError, ValueError):
            return RedirectResponse(
                "/servicos?erro=" + quote("Preço ou duração inválidos."),
                status_code=303,
            )
    try:
        db.salvar_servicos(itens)
    except ValueError as exc:
        return RedirectResponse(
            "/servicos?erro=" + quote(str(exc)),
            status_code=303,
        )
    return RedirectResponse("/servicos?ok=1", status_code=303)


@app.get("/avaliacoes", dependencies=[Depends(autenticar)])
def ver_avaliacoes():
    r = agenda.resumo_avaliacoes()
    barbeiros = "".join(f"<tr><td>{e(b['barbeiro'])}</td><td>{b['media']} ⭐</td><td>{b['total']}</td></tr>"
                        for b in r["por_barbeiro"])
    comentarios = "".join(f"<tr><td>{c['nota']} ⭐</td><td>{e(c['barbeiro'])}</td>"
                          f"<td>{e(c['comentario'])}</td><td>{e(c['nome_cliente'] or '')}</td></tr>"
                          for c in r["comentarios"])
    corpo = f"""<div class=card><h3>Média dos últimos 30 dias</h3>{"<table><tr><th>Barbeiro</th><th>Média</th>"
    "<th>Avaliações</th></tr>" + barbeiros + "</table>" if barbeiros else "<p class=vazio>Sem avaliações.</p>"}</div>
    <div class=card><h3>Comentários</h3>{"<table>" + comentarios + "</table>" if comentarios
    else "<p class=vazio>Nenhum comentário.</p>"}</div>"""
    return pagina("Avaliações", corpo)


@app.get("/whatsapp", dependencies=[Depends(autenticar)])
def ver_whatsapp():
    """Só status + QR para conectar o celular. Não mostra conversas."""
    st = _status_whatsapp()
    if st.get("erro") and not st.get("conectado") and not st.get("temQr"):
        corpo = f"""<div class=card><h3>WhatsApp</h3>
        <p class=aviso>Não consegui falar com a Evolution API.</p>
        <p class=vazio>{e(st['erro'])}</p>
        <p>Confira se o container <code>evolution</code> está no ar.</p>
        <p><a href="/whatsapp">Tentar de novo</a></p></div>"""
        return pagina("WhatsApp", corpo, refresh=8)

    if st.get("conectado"):
        num = st.get("numero") or evo.numero_conectado() or ""
        num_txt = e(num) if num else "(ainda não li o número)"
        corpo = f"""<div class=card><h3>WhatsApp</h3>
        <p class=ok>Conectado. Não precisa escanear QR.</p>
        <p>Número do aparelho (dono / comandos <code>#agenda</code>): <b>{num_txt}</b></p>
        <p class=vazio>Esse é o WhatsApp que escaneou o QR. Comandos # e alertas vão para ele.
        Se desconectar, esta página mostra o QR automaticamente.</p>
        <p><a href="/whatsapp">Atualizar</a></p></div>"""
        return pagina("WhatsApp", corpo, refresh=30)

    if st.get("temQr"):
        idade = st.get("idadeQrSegundos")
        idade_txt = f"QR gerado há {idade}s." if idade is not None else ""
        ts = int(time.time())
        corpo = f"""<div class=card><h3>Escaneie o QR</h3>
        <ol class=passos>
          <li>No <b>mesmo celular</b> do WhatsApp: <b>Aparelhos conectados</b> → <b>Conectar um aparelho</b></li>
          <li>Escaneie <b>este</b> QR (ele muda a cada ~20s — use o mais novo)</li>
        </ol>
        <img class=qr src="/whatsapp/qr.png?t={ts}" alt="QR Code do WhatsApp">
        <p class=vazio>{e(idade_txt)} A página atualiza sozinha. Se não pegar,
        <form method=post action=/whatsapp/reiniciar style="display:inline">
        <button type=submit>Gerar QR novo</button></form></p>
        </div>"""
        return pagina("WhatsApp", corpo, refresh=4)

    corpo = """<div class=card><h3>WhatsApp</h3>
    <p class=aviso>Aguardando o QR… a Evolution ainda está gerando.</p>
    <p><a href="/whatsapp">Atualizar</a> ·
    <form method=post action=/whatsapp/reiniciar style="display:inline">
    <button type=submit>Gerar QR novo</button></form></p></div>"""
    return pagina("WhatsApp", corpo, refresh=5)


@app.get("/whatsapp/qr.png", dependencies=[Depends(autenticar)])
def whatsapp_qr_png():
    png = evo.qr_png_bytes()
    if not png:
        raise HTTPException(404, "Sem QR no momento")
    return Response(
        content=png, media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.post("/whatsapp/reiniciar", dependencies=[Depends(autenticar)])
def whatsapp_reiniciar():
    with contextlib.suppress(Exception):
        evo.reiniciar_qr()
    return RedirectResponse("/whatsapp", status_code=303)
