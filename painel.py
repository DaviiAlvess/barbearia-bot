"""Painel web do dono: agenda, bloqueios, avaliações e QR do WhatsApp.

Rodar:  uvicorn painel:app --port 8080
Abrir:  http://localhost:8080  (usuário: dono, senha: PAINEL_SENHA do .env)
"""
from __future__ import annotations

import html
import os
import secrets
from datetime import timedelta

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

load_dotenv()

import config  # noqa: E402
from barbearia import agenda, db  # noqa: E402

app = FastAPI(title=f"Painel - {config.NOME_BARBEARIA}", docs_url=None, redoc_url=None)
seguranca = HTTPBasic()
db.criar_tabelas()

SERVIDOR_WHATSAPP = os.getenv("SERVIDOR_WHATSAPP", "http://localhost:3000").rstrip("/")


def autenticar(cred: HTTPBasicCredentials = Depends(seguranca)) -> None:
    senha = os.getenv("PAINEL_SENHA")
    if not senha:
        raise HTTPException(503, "Defina PAINEL_SENHA no .env para usar o painel.")
    ok = secrets.compare_digest(cred.username, "dono") and secrets.compare_digest(cred.password, senha)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário ou senha incorretos",
                            headers={"WWW-Authenticate": "Basic"})


@app.exception_handler(agenda.ErroAgenda)
def erro_agenda(_request, exc: agenda.ErroAgenda):
    return pagina("Erro", f"<div class=card><p>⚠️ {e(str(exc))}</p><a href=/>Voltar</a></div>")


e = html.escape  # nunca colocar texto do cliente no HTML sem escapar

ESTILO = """
body{font-family:system-ui,sans-serif;margin:0;background:#f6f4f1;color:#222}
header{background:#1d1b19;color:#f2c14e;padding:14px 20px;font-size:20px;font-weight:600}
main{max-width:960px;margin:auto;padding:16px}
.card{background:#fff;border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px #0001}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}
th{font-size:13px;color:#666}.nav a{margin-right:12px;color:#1d1b19}
button{background:#1d1b19;color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer}
button.perigo{background:#b3261e}input,select{padding:6px;border:1px solid #ccc;border-radius:6px}
.total{font-size:18px;font-weight:600}.vazio{color:#888}
.ok{color:#1a7f37;font-weight:600}.aviso{color:#9a6700}.qr{display:block;margin:16px auto;max-width:360px;width:100%;
background:#fff;border:1px solid #eee;border-radius:8px}
.passos{line-height:1.6}
"""


def pagina(titulo: str, corpo: str, *, refresh: int | None = None) -> HTMLResponse:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return HTMLResponse(f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{e(titulo)}</title>
<style>{ESTILO}</style></head><body><header>💈 {e(config.NOME_BARBEARIA)}</header><main>
<div class="nav card"><a href="/">Agenda</a><a href="/bloqueios">Folgas e feriados</a>
<a href="/avaliacoes">Avaliações</a><a href="/whatsapp">WhatsApp / QR</a></div>
{corpo}</main></body></html>""")


def _status_whatsapp() -> dict:
    try:
        r = requests.get(f"{SERVIDOR_WHATSAPP}/status", timeout=3)
        if r.status_code == 200:
            return r.json()
        return {"conectado": False, "temQr": False, "erro": f"HTTP {r.status_code}"}
    except requests.RequestException as exc:
        return {"conectado": False, "temQr": False, "erro": str(exc)}


@app.get("/", dependencies=[Depends(autenticar)])
def ver_agenda(data: str | None = None):
    d = agenda.ler_data(data) if data else agenda.agora().date()
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
    corpo = f"""<div class=card><a href="/?data={anterior}">◀</a>
    <b>{agenda.DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m/%Y')}</b> <a href="/?data={proximo}">▶</a>
    <form style="display:inline;margin-left:12px"><input type=date name=data value="{d}"><button>Ir</button></form>
    <p class=total>{len(itens)} atendimentos · R$ {total:.2f}</p>
    {"<table><tr><th>Hora</th><th>Barbeiro</th><th>Serviço</th><th>Cliente</th><th>Valor</th><th></th></tr>"
     + linhas + "</table>" if itens else "<p class=vazio>Nenhum horário marcado.</p>"}</div>"""
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
    opcoes = "".join(f"<option>{e(b)}</option>" for b in config.BARBEIROS)
    corpo = f"""<div class=card><h3>Fechar dia ou dar folga</h3><form method=post action=/bloquear>
    <input type=date name=data required> <select name=barbeiro><option value="">Barbearia toda</option>
    {opcoes}</select> <input name=motivo placeholder="Motivo (opcional)"> <button>Bloquear</button></form></div>
    <div class=card><h3>Próximos bloqueios</h3>{"<table>" + linhas + "</table>" if rows
    else "<p class=vazio>Nenhum.</p>"}</div>"""
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
        <p class=aviso>Não consegui falar com o servidor do WhatsApp.</p>
        <p class=vazio>{e(st['erro'])}</p>
        <p>Confira se o container <code>whatsapp</code> está no ar.</p>
        <p><a href="/whatsapp">Tentar de novo</a></p></div>"""
        return pagina("WhatsApp", corpo, refresh=8)

    if st.get("conectado"):
        corpo = """<div class=card><h3>WhatsApp</h3>
        <p class=ok>Conectado. Não precisa escanear QR.</p>
        <p class=vazio>Se desconectar, esta página mostra o QR automaticamente.</p>
        <p><a href="/whatsapp">Atualizar</a></p></div>"""
        return pagina("WhatsApp", corpo, refresh=30)

    if st.get("temQr"):
        corpo = """<div class=card><h3>Escaneie o QR Code</h3>
        <ol class=passos>
          <li>No celular: WhatsApp → <b>Aparelhos conectados</b> → <b>Conectar aparelho</b></li>
          <li>Aponte a câmera para o código abaixo</li>
        </ol>
        <img class=qr src="/whatsapp/qr.png" alt="QR Code do WhatsApp">
        <p class=vazio>A página atualiza sozinha a cada 5s. O QR muda de tempos em tempos.</p>
        </div>"""
        return pagina("WhatsApp", corpo, refresh=5)

    corpo = """<div class=card><h3>WhatsApp</h3>
    <p class=aviso>Aguardando o QR… o Chromium ainda está iniciando.</p>
    <p><a href="/whatsapp">Atualizar</a></p></div>"""
    return pagina("WhatsApp", corpo, refresh=5)


@app.get("/whatsapp/qr.png", dependencies=[Depends(autenticar)])
def whatsapp_qr_png():
    try:
        r = requests.get(f"{SERVIDOR_WHATSAPP}/qr.png", timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(502, f"Servidor WhatsApp inacessível: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(404, "Sem QR no momento")
    return Response(content=r.content, media_type="image/png",
                    headers={"Cache-Control": "no-store"})
