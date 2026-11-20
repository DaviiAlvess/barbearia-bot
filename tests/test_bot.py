"""Testes sem internet: a IA é simulada (FakeIA) e o relógio é fixo."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from barbearia import agenda, atendente, db, ferramentas, humanizar, persona  # noqa: E402
from barbearia.atendente import Atendente  # noqa: E402

# Quinta-feira 19/11/2026 10:00
AGORA = datetime(2026, 11, 19, 10, 0)
SABADO = "2026-11-21"
SEGUNDA = "2026-11-23"
QUARTA = "2026-11-25"
TEL = "5575911112222"


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "CAMINHO_BANCO", str(tmp_path / "t.db"))
    monkeypatch.setattr(agenda, "agora", lambda: AGORA)
    monkeypatch.delenv("TELEFONE_DONO", raising=False)
    atendente._recentes.clear()
    db.criar_tabelas()


class FakeIA:
    """Devolve respostas roteirizadas e guarda o que recebeu."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = []

    def gerar(self, instrucoes, historico, ferramentas_):
        self.chamadas.append((instrucoes, [dict(h) for h in historico]))
        item = self.roteiro.pop(0)
        if isinstance(item, str):
            return {"role": "model", "parts": [{"text": item}]}
        return {"role": "model", "parts": [{"functionCall": {"name": item[0], "args": item[1]}}]}


# ---------------- agenda ----------------
def test_dia_fechado():
    r = agenda.horarios_livres(SEGUNDA, "corte")
    assert r["fechado"] is True


def test_almoco_e_folga():
    r = agenda.horarios_livres(SABADO, "Corte")
    livres = r["livres_por_barbeiro"]
    assert "Thiago" not in livres  # folga sábado
    assert "12:00" not in livres["Rafael"] and "12:30" not in livres["Rafael"]
    assert livres["Rafael"][0] == "08:00" and livres["Rafael"][-1] == "16:30"


def test_hoje_nao_oferece_horario_passado():
    r = agenda.horarios_livres("2026-11-19", "Corte", "Rafael")
    assert r["livres_por_barbeiro"]["Rafael"][0] == "10:30"


def test_servico_longo_respeita_almoco_e_conflito():
    agenda.agendar(TEL, "Ana", SABADO, "09:00", "Corte", "Rafael")
    r = agenda.horarios_livres(SABADO, "Corte + Barba", "Rafael")["livres_por_barbeiro"]["Rafael"]
    assert "09:00" not in r and "08:30" not in r  # 60 min bateria no 09:00
    assert "11:30" not in r                         # bateria no almoço
    assert "10:00" in r and "11:00" in r


def test_nao_deixa_marcar_duas_vezes():
    agenda.agendar(TEL, "A", SABADO, "10:00", "Corte", "Diego")
    with pytest.raises(agenda.ErroAgenda):
        agenda.agendar("outro", "B", SABADO, "10:00", "Barba", "Diego")


def test_sem_barbeiro_pega_quem_esta_livre():
    a = agenda.agendar(TEL, "A", SABADO, "10:00", "Corte")
    b = agenda.agendar("2", "B", SABADO, "10:00", "Corte")
    assert a["barbeiro"] != b["barbeiro"]


def test_nomes_de_servico():
    assert agenda.achar_servico("corte e barba") == "Corte + Barba"
    assert agenda.achar_servico("quero corte e barba") == "Corte + Barba"
    assert agenda.achar_servico("platinado") == "Luzes / Platinado"
    assert agenda.achar_servico("CORTE") == "Corte"
    assert agenda.achar_barbeiro("rafael") == "Rafael"


def test_remarcar_e_lista_de_espera():
    # sábado do Diego lotado por um cliente; outro entra na espera
    ag = agenda.agendar(TEL, "Ana", SABADO, "10:00", "Corte", "Diego")
    ferramentas.executar("entrar_lista_espera", {"data": SABADO, "servico": "Corte", "barbeiro": "Diego"}, "espera")
    enviados = []
    r = ferramentas.executar("remarcar_agendamento",
                             {"id": ag["id"], "nova_data": QUARTA, "nova_hora": "15:00", "barbeiro": "Rafael"},
                             TEL, lambda t, m: enviados.append((t, m)))
    assert r["ok"] and r["novo"]["barbeiro"] == "Rafael"
    assert len(agenda.agendamentos_futuros(TEL)) == 1
    assert enviados and enviados[0][0] == "espera" and "Abriu vaga" in enviados[0][1]
    # não avisa duas vezes
    assert agenda.quem_esperava(SABADO, "Diego") == []


def test_cancelar_so_o_proprio():
    ag = agenda.agendar(TEL, "Ana", SABADO, "10:00", "Corte", "Diego")
    assert "erro" in ferramentas.executar("cancelar_agendamento", {"id": ag["id"]}, "intruso")
    assert ferramentas.executar("cancelar_agendamento", {"id": ag["id"]}, TEL)["ok"]


def test_fidelidade(monkeypatch):
    for i in range(3):
        agenda.agendar(TEL, "Ana", SABADO, f"0{8 + i}:00", "Corte", "Rafael")
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 22, 9, 0))
    f = agenda.fidelidade(TEL)
    assert f["atendimentos_feitos"] == 3 and f["faltam_para_brinde"] == 7


def test_lembretes(monkeypatch):
    agenda.agendar(TEL, "Carlos Souza", "2026-11-20", "15:00", "Corte", "Rafael")
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 19, 18, 30))
    bot = Atendente(FakeIA([]))
    msgs = bot.mensagens_programadas()
    assert len(msgs) == 1 and "Carlos" in msgs[0][1] and "15:00" in msgs[0][1]
    assert bot.mensagens_programadas() == []  # não repete
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 20, 13, 30))
    msgs = bot.mensagens_programadas()
    assert len(msgs) == 1 and config.ENDERECO in msgs[0][1]  # lembrete de 2h antes, com endereço


# ---------------- conversa ----------------
def test_conversa_com_ferramentas_e_memoria():
    ia = FakeIA([
        ("ver_horarios_livres", {"data": SABADO, "servico": "Corte", "barbeiro": "Rafael"}),
        "Sábado com o Rafael tenho 08:00, 08:30 e 09:00.\n\nQual fica melhor pra você?",
        ("agendar", {"nome_cliente": "Marcos", "data": SABADO, "hora": "09:00",
                     "servico": "Corte", "barbeiro": "Rafael"}),
        "Fechado, Marcos! Sábado 21/11 às 09:00 com o Rafael. R$ 35,00.",
    ])
    bot = Atendente(ia)
    b1 = bot.responder(TEL, "fala, tem horário sábado com o rafael?")
    assert b1 == ["Sábado com o Rafael tenho 08:00, 08:30 e 09:00.", "Qual fica melhor pra você?"]
    # a IA recebeu o resultado da ferramenta com os horários reais
    hist = ia.chamadas[1][1]
    resp = hist[-1]["parts"][0]["functionResponse"]["response"]
    assert "08:00" in resp["livres_por_barbeiro"]["Rafael"]
    assert "início da conversa" in ia.chamadas[0][0]

    b2 = bot.responder(TEL, "9h, meu nome é Marcos")
    assert "Fechado" in b2[0]
    assert agenda.agendamentos_futuros(TEL)[0]["hora"] == "09:00"
    assert db.obter_cliente(TEL)["nome"] == "Marcos"
    assert "NÃO cumprimente" in ia.chamadas[2][0]  # não repete o "oi"


def test_cliente_que_volta_e_reconhecido():
    db.salvar_cliente(TEL, nome="Marcos", barbeiro_preferido="Diego", observacoes="degradê na 1")
    txt = persona.montar(db.obter_cliente(TEL), None, True)
    assert "Marcos" in txt and "Diego" in txt and "degradê na 1" in txt
    assert "2026-11-21" in txt and "sábado 21/11" in txt


def test_passa_para_humano_e_avisa_dono(monkeypatch):
    monkeypatch.setenv("TELEFONE_DONO", "dono")
    enviados = []
    ia = FakeIA([("chamar_atendente_humano", {"motivo": "reclamação"}),
                 "Poxa, sinto muito. Já chamei o pessoal aqui, um minutinho."])
    bot = Atendente(ia, enviar=lambda t, m: enviados.append((t, m)))
    assert bot.responder(TEL, "o corte ficou horrível")
    assert enviados[0][0] == "dono"
    assert bot.responder(TEL, "alô?") == []  # bot fica quieto enquanto o humano atende
    assert "Bot religado" in bot.responder("dono", f"#bot {TEL}")[0]


def test_comandos_do_dono(monkeypatch):
    monkeypatch.setenv("TELEFONE_DONO", "dono")
    agenda.agendar(TEL, "Marcos", SABADO, "09:00", "Corte", "Rafael")
    bot = Atendente(FakeIA([]))
    r = bot.responder("dono", f"#agenda {SABADO}")[0]
    assert "Marcos" in r and "R$ 35.00" in r
    assert "Comandos" in bot.responder("dono", "#ajuda")[0]


def test_ia_fora_do_ar_responde_humano():
    class Quebrada:
        def gerar(self, *a):
            from barbearia.ia import ErroIA
            raise ErroIA("503")
    bot = Atendente(Quebrada())
    assert bot.responder(TEL, "oi")[0] in humanizar.SEM_IA
    assert db.carregar_conversa(TEL)[0] == []


def test_baloes():
    assert humanizar.em_baloes("**Oi!**\n\nTudo bem?") == ["Oi!", "Tudo bem?"]
    assert len(humanizar.em_baloes("a\n\nb\n\nc\n\nd")) == 3
    assert 0.5 < humanizar.tempo_digitando("oi") < 7


# ---------------- versão 2: boas maneiras e novas funções ----------------
def test_feriado_e_folga_pelo_dono(monkeypatch):
    monkeypatch.setenv("TELEFONE_DONO", "dono")
    agenda.agendar(TEL, "Marcos", SABADO, "09:00", "Corte", "Rafael")
    bot = Atendente(FakeIA([]))
    r = bot.responder("dono", "#folga 21/11 Rafael")[0]
    assert "Marcos" in r  # avisa que já tinha cliente marcado
    assert "Rafael" not in agenda.horarios_livres(SABADO, "Corte")["livres_por_barbeiro"]
    bot.responder("dono", f"#fechar {QUARTA} Feriado municipal")
    fechado = agenda.horarios_livres(QUARTA, "Corte")
    assert fechado["fechado"] and "Feriado municipal" in fechado["mensagem"]
    assert "liberado" in bot.responder("dono", f"#abrir {QUARTA}")[0]
    assert "livres_por_barbeiro" in agenda.horarios_livres(QUARTA, "Corte")


def test_avaliacao_pos_atendimento(monkeypatch):
    monkeypatch.setenv("TELEFONE_DONO", "dono")
    agenda.agendar(TEL, "Marcos Lima", SABADO, "09:00", "Corte", "Rafael")
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 21, 10, 45))
    enviados = []
    ia = FakeIA([("registrar_avaliacao", {"nota": 2, "comentario": "demorou muito"}),
                 "Poxa, Marcos, me desculpa pela demora. Vou repassar pro dono, obrigado por avisar."])
    bot = Atendente(ia, enviar=lambda t, m: enviados.append((t, m)))
    assert bot.enviar_programadas() == 1
    assert enviados[0][0] == TEL and "1 a 5" in enviados[0][1] and "Marcos" in enviados[0][1]
    bot.responder(TEL, "2, demorou muito")
    # a IA sabia que estava respondendo ao pedido de avaliação
    assert "1 a 5" in ia.chamadas[0][1][-1]["parts"][0]["text"]
    assert "NÃO cumprimente" in ia.chamadas[0][0]
    assert enviados[-1][0] == "dono" and "2/5" in enviados[-1][1]  # nota baixa avisa o dono
    assert "demorou muito" in bot.responder("dono", "#avaliacoes")[0]


def test_cliente_que_pede_para_parar_nao_recebe_mais(monkeypatch):
    agenda.agendar(TEL, "Ana", "2026-11-20", "15:00", "Corte", "Rafael")
    ferramentas.executar("preferencia_mensagens", {"aceita": False}, TEL)
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 19, 19, 0))
    assert Atendente(FakeIA([])).mensagens_programadas() == []


def test_horario_de_silencio(monkeypatch):
    agenda.agendar(TEL, "Ana", "2026-11-20", "09:00", "Corte", "Rafael")
    monkeypatch.setattr(agenda, "agora", lambda: datetime(2026, 11, 19, 22, 0))
    assert Atendente(FakeIA([])).mensagens_programadas() == []


def test_followup_conversa_esquecida(monkeypatch):
    """Conversa parada no meio do agendamento recebe um toque; não repete; respeita quem já marcou."""
    import time as _time

    ia = FakeIA([
        ("ver_horarios_livres", {"data": SABADO, "servico": "Corte", "barbeiro": "Rafael"}),
        "Sábado com o Rafael tenho 08:00 e 09:00.\n\nQual fica melhor?",
    ])
    bot = Atendente(ia)
    bot.responder(TEL, "tem horário sábado com o rafael?")
    # simula silêncio de 3h
    hist, _, _ = db.carregar_conversa(TEL)
    parado = _time.time() - 3 * 3600
    db.salvar_conversa(TEL, hist, parado)

    msgs = bot.mensagens_programadas()
    assert len(msgs) == 1 and msgs[0][0] == TEL
    assert "marcar" in msgs[0][1].lower() or "horário" in msgs[0][1].lower() or "decidir" in msgs[0][1].lower()
    assert bot.mensagens_programadas() == []  # não martela

    # se já agendou, não manda follow-up de conversa (só lembretes de agenda, se houver)
    agenda.agendar(TEL, "Marcos", SABADO, "09:00", "Corte", "Rafael")
    db.salvar_conversa(TEL, hist, _time.time() - 3 * 3600)
    db.marcar_followup(TEL, 0)  # libera de novo
    msgs2 = Atendente(FakeIA([])).mensagens_programadas()
    assert not any("ainda quer marcar" in m[1].lower() or "conseguiu decidir" in m[1].lower()
                   for m in msgs2)


def test_persona_sempre_ve_agendamentos_pendentes():
    agenda.agendar(TEL, "Marcos", SABADO, "09:00", "Corte", "Rafael")
    pend = agenda.agendamentos_futuros(TEL)
    txt = persona.montar(db.obter_cliente(TEL), None, False, pendentes=pend)
    assert "09:00" in txt and "Rafael" in txt and "Horários já marcados" in txt
    assert "retome de onde parou" in persona.montar(None, None, True, pendentes=[])


def test_apagar_dados(monkeypatch):
    ia = FakeIA([("apagar_meus_dados", {}), "Pronto, apaguei seus dados. Qualquer coisa é só chamar!"])
    bot = Atendente(ia)
    agenda.agendar(TEL, "Ana", SABADO, "10:00", "Corte", "Rafael")
    db.salvar_cliente(TEL, nome="Ana")
    bot.responder(TEL, "quero apagar meus dados, pode confirmar")
    assert db.obter_cliente(TEL) is None
    assert db.carregar_conversa(TEL)[0] == []
    assert agenda.agendamentos_futuros(TEL) == []


def test_anti_spam():
    bot = Atendente(FakeIA(["ok"] * 20))
    respostas = [bot.responder(TEL, f"msg {i}") for i in range(14)]
    assert all(respostas[:12]) and respostas[12] == [] and respostas[13] == []


def test_texto_gigante_e_cortado():
    ia = FakeIA(["ok"])
    Atendente(ia).responder(TEL, "a" * 10000)
    assert len(ia.chamadas[0][1][-1]["parts"][0]["text"]) == atendente.MAX_CARACTERES


def test_banco_antigo_e_migrado(tmp_path, monkeypatch):
    import sqlite3
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE clientes (telefone TEXT PRIMARY KEY, nome TEXT, barbeiro_preferido TEXT, "
                "observacoes TEXT, criado_em TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "CAMINHO_BANCO", str(caminho))
    db.criar_tabelas()
    assert db.aceita_mensagens("qualquer")


def _login_painel(client, senha="s3nha"):
    r = client.post("/login", data={"senha": senha, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303
    return client


def test_tabela_servicos_banco_e_ferramenta():
    assert "Corte" in db.listar_servicos()
    db.salvar_servicos({"Corte social": (40.0, 30), "Barba": (28.0, 25)})
    assert db.listar_servicos()["Corte social"] == (40.0, 30)
    assert agenda.achar_servico("corte social") == "Corte social"
    r = ferramentas.executar("ver_tabela_servicos", {}, TEL)
    assert any(s["servico"] == "Barba" and s["preco"] == 28.0 for s in r["servicos"])
    assert "R$" in r["texto"]


def test_endereco_e_profissionais_banco():
    db.salvar_endereco("Av. Central, 10")
    assert db.endereco() == "Av. Central, 10"
    db.salvar_barbeiros([
        {"nome": "João", "especialidade": "social", "folgas": [0]},
        {"nome": "Maria", "especialidade": "barba", "folgas": []},
    ])
    assert "João" in db.listar_barbeiros()
    assert agenda.achar_barbeiro("joao") == "João"
    assert 0 in db.listar_barbeiros()["João"]["folgas"]
    assert "João" in db.tabela_barbeiros_texto()
    db.adicionar_barbeiro("Pedro", "platinado")
    assert "Pedro" in db.listar_barbeiros()
    assert db.remover_barbeiro("Maria") is True
    assert "Maria" not in db.listar_barbeiros()


def test_nome_salao_painel_e_banco():

    assert db.nome_salao() == "Meu Salão"
    db.salvar_config("nome_salao", "Barbearia Teste")
    assert db.nome_salao() == "Barbearia Teste"


def test_painel(monkeypatch):
    from fastapi.testclient import TestClient

    import painel
    monkeypatch.setenv("PAINEL_SENHA", "s3nha")
    agenda.agendar(TEL, "<script>alert(1)</script>", SABADO, "09:00", "Corte", "Rafael")
    c = TestClient(painel.app)
    # sem login: redireciona para página HTML (não JSON)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers["location"]
    assert "Entrar" in c.get("/login").text and "Senha" in c.get("/login").text
    assert c.post("/login", data={"senha": "errada", "next": "/"}).status_code == 200
    assert "Senha incorreta" in c.post("/login", data={"senha": "errada", "next": "/"}).text
    _login_painel(c)
    assert "Agendbarber" in c.get("/login").text or "Agendbarber" in c.get("/").text
    r = c.get(f"/?data={SABADO}")
    assert r.status_code == 200 and "R$ 35.00" in r.text
    assert "<script>alert" not in r.text and "&lt;script&gt;" in r.text  # protegido contra XSS
    # nome + endereço do salão pelo painel
    assert c.get("/salao").status_code == 200 and "Nome do salão" in c.get("/salao").text
    r = c.post("/salao", data={"nome": "Navalha & Cia", "endereco": "Rua A, 1"}, follow_redirects=False)
    assert r.status_code == 303 and db.nome_salao() == "Navalha & Cia"
    assert db.endereco() == "Rua A, 1"
    assert "Navalha &amp; Cia" in c.get("/").text or "Navalha & Cia" in c.get("/").text
    # profissionais: listar, adicionar, remover
    assert c.get("/profissionais").status_code == 200 and "Adicionar profissional" in c.get("/profissionais").text
    assert "Remover" in c.get("/profissionais").text
    r = c.post("/profissionais/adicionar", data={"nome": "Ana", "especialidade": "sobrancelha"},
               follow_redirects=False)
    assert r.status_code == 303 and "ok=add" in r.headers["location"]
    assert "Ana" in db.listar_barbeiros()
    r = c.post("/profissionais/remover", data={"nome": "Thiago"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=rm" in r.headers["location"]
    assert "Thiago" not in db.listar_barbeiros()
    # salvar alterações (folgas)
    nomes = list(db.listar_barbeiros())
    r = c.post(
        "/profissionais",
        data={
            "nome": nomes,
            "especialidade": [db.listar_barbeiros()[n].get("especialidade", "") for n in nomes],
            "folga_0": ["1"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    assert 1 in db.listar_barbeiros()[nomes[0]]["folgas"]
    # tabela de serviços no painel
    assert c.get("/servicos").status_code == 200 and "Serviços e preços" in c.get("/servicos").text
    r = c.post(
        "/servicos",
        data={
            "nome": ["Corte", "Barba", ""],
            "preco": ["42", "22.5", ""],
            "minutos": ["30", "30", ""],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    assert db.listar_servicos()["Corte"] == (42.0, 30)
    assert db.listar_servicos()["Barba"] == (22.5, 30)
    r = c.post("/bloquear", data={"data": QUARTA, "barbeiro": "", "motivo": "Feriado"},
               follow_redirects=False)
    assert r.status_code == 303 and agenda.horarios_livres(QUARTA, "Corte")["fechado"]
    assert "Data inválida" in c.get("/?data=xx").text



def test_painel_whatsapp_qr(monkeypatch):
    """Página do QR: autentica, mostra status e PNG da Evolution — sem conversas."""
    from fastapi.testclient import TestClient

    import painel
    from barbearia import evolution as evo

    monkeypatch.setenv("PAINEL_SENHA", "s3nha")
    monkeypatch.setattr(
        evo, "status_para_painel",
        lambda: {"conectado": False, "temQr": True, "idadeQrSegundos": 2},
    )
    monkeypatch.setattr(evo, "qr_png_bytes", lambda: b"\x89PNG\r\n\x1a\nfake")

    c = TestClient(painel.app)
    assert c.get("/whatsapp", follow_redirects=False).status_code == 303
    _login_painel(c)
    r = c.get("/whatsapp")
    assert r.status_code == 200
    assert "Escaneie o QR" in r.text and 'src="/whatsapp/qr.png' in r.text
    assert "conversa" not in r.text.lower()
    png = c.get("/whatsapp/qr.png")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")

    monkeypatch.setattr(
        evo, "status_para_painel",
        lambda: {"conectado": True, "temQr": False},
    )
    r = c.get("/whatsapp")
    assert r.status_code == 200 and "Conectado" in r.text


def test_evolution_extrair_mensagem():
    from barbearia import evolution as evo

    assert evo.extrair_telefone("5511999999999@s.whatsapp.net") == "5511999999999"
    assert evo.extrair_telefone("120363@g.us") is None
    assert evo.extrair_texto_mensagem({"conversation": " oi "}) == "oi"
    assert "áudio" in (evo.extrair_texto_mensagem({"audioMessage": {}}, "audioMessage") or "")
