"""O 'cérebro' do atendimento: junta histórico, IA, ferramentas e humanização.
Funciona com qualquer canal (terminal, WhatsApp...)."""
import os
import random
import threading
import time
from collections import defaultdict
from datetime import timedelta

from barbearia import agenda, db, ferramentas, humanizar, persona
from barbearia.ia import ErroIA

CONVERSA_EXPIRA_HORAS = 6       # depois disso, começa conversa nova (mas lembra do cliente)
MAX_HISTORICO = 40              # quantas mensagens guardar por conversa
MAX_RODADAS_FERRAMENTA = 6

_travas = defaultdict(threading.Lock)


def _cortar_historico(hist):
    if len(hist) <= MAX_HISTORICO:
        return hist
    hist = hist[-MAX_HISTORICO:]
    # precisa começar numa mensagem de texto do cliente (não numa resposta de ferramenta)
    while hist and not (hist[0]["role"] == "user" and any("text" in p for p in hist[0]["parts"])):
        hist = hist[1:]
    return hist


class Atendente:
    def __init__(self, ia, enviar=None):
        """ia: objeto com .gerar(instrucoes, historico, ferramentas)
        enviar(telefone, texto): manda mensagem ativa (lista de espera, aviso ao dono)."""
        self.ia = ia
        self.enviar = enviar
        db.criar_tabelas()

    # ------------------------------------------------------------------
    def responder(self, telefone, texto):
        """Recebe a mensagem do cliente e devolve a lista de balões de resposta."""
        texto = (texto or "").strip()
        if not texto:
            return []
        dono = os.getenv("TELEFONE_DONO")
        if dono and telefone == dono and texto.startswith("#"):
            return [self._comando_dono(texto)]

        with _travas[telefone]:
            agora = time.time()
            hist, atualizado, humano_ate = db.carregar_conversa(telefone)
            if humano_ate > agora:
                return []  # um atendente humano está cuidando dessa conversa
            conversa_nova = not hist or agora - atualizado > CONVERSA_EXPIRA_HORAS * 3600
            if conversa_nova:
                hist = []

            cliente = db.obter_cliente(telefone)
            instrucoes = persona.montar(cliente, db.ultimo_atendimento(telefone), conversa_nova)
            hist.append({"role": "user", "parts": [{"text": texto}]})

            try:
                resposta = self._rodar_ia(instrucoes, hist, telefone)
            except ErroIA as e:
                print(f"[IA] erro: {e}")
                hist.pop()  # não salva a mensagem sem resposta
                return [random.choice(humanizar.SEM_IA)]

            db.salvar_conversa(telefone, _cortar_historico(hist), agora)
            return humanizar.em_baloes(resposta) or ["Pode repetir? Não entendi bem 😅"]

    def _rodar_ia(self, instrucoes, hist, telefone):
        for _ in range(MAX_RODADAS_FERRAMENTA):
            conteudo = self.ia.gerar(instrucoes, hist, ferramentas.DECLARACOES)
            hist.append(conteudo)
            chamadas = [p["functionCall"] for p in conteudo["parts"] if "functionCall" in p]
            if not chamadas:
                return "".join(p.get("text", "") for p in conteudo["parts"]
                               if not p.get("thought"))
            respostas = []
            for c in chamadas:
                resultado = ferramentas.executar(c["name"], c.get("args") or {}, telefone, self.enviar)
                print(f"[ferramenta] {c['name']}({c.get('args')}) -> {str(resultado)[:200]}")
                respostas.append({"functionResponse": {"name": c["name"], "response": resultado}})
            hist.append({"role": "user", "parts": respostas})
        raise ErroIA("A IA ficou em loop chamando ferramentas")

    # ------------------------------------------------------------------
    def _comando_dono(self, texto):
        partes = texto.split()
        cmd = partes[0].lower()
        arg = partes[1] if len(partes) > 1 else ""
        if cmd == "#agenda":
            hoje = agenda.agora().date()
            d = hoje + timedelta(days=1) if arg.lower().startswith("amanh") else (
                agenda.ler_data(arg) if arg and arg[0].isdigit() else hoje)
            itens = agenda.agenda_do_dia(d)
            if not itens:
                return f"📅 {d.strftime('%d/%m')}: nenhum horário marcado."
            total = sum(i["preco"] or 0 for i in itens)
            linhas = [f"{i['inicio'][11:]} {i['barbeiro']}: {i['servico']} - {i['nome_cliente']} "
                      f"(#{i['id']})" for i in itens]
            return (f"📅 Agenda {d.strftime('%d/%m')} ({len(itens)} atendimentos, "
                    f"R$ {total:.2f}):\n" + "\n".join(linhas))
        if cmd == "#pausar" and arg:
            db.pausar_bot(arg, time.time() + 12 * 3600)
            return f"⏸️ Bot pausado para {arg} por 12h. Use #bot {arg} para religar."
        if cmd == "#bot" and arg:
            db.pausar_bot(arg, 0)
            return f"▶️ Bot religado para {arg}."
        if cmd == "#cancelar" and arg.isdigit():
            with db.conexao() as con:
                row = con.execute("SELECT telefone FROM agendamentos WHERE id = ?", (int(arg),)).fetchone()
            if not row:
                return "Não achei esse agendamento."
            r = ferramentas.executar("cancelar_agendamento", {"id": int(arg)}, row["telefone"], self.enviar)
            return "❌ Cancelado." if r.get("ok") else f"Erro: {r.get('erro')}"
        return ("Comandos do dono:\n#agenda [hoje|amanha|AAAA-MM-DD]\n#cancelar <id>\n"
                "#pausar <telefone>  (você assume a conversa)\n#bot <telefone>  (religa o bot)")

    # ------------------------------------------------------------------
    def mensagens_de_lembrete(self):
        """Gera [(telefone, texto)] dos lembretes que estão na hora de mandar."""
        saida = []
        for l in agenda.lembretes_pendentes():
            nome = (l["nome"] or "").split(" ")[0] or "chefe"
            if l["tipo"] == "vespera":
                txt = random.choice([
                    f"Fala, {nome}! Passando pra lembrar do seu horário amanhã às {l['hora']} com o "
                    f"{l['barbeiro']} ({l['servico'].lower()}). Tá confirmado?",
                    f"E aí, {nome}, tudo certo? Amanhã às {l['hora']} tem {l['servico'].lower()} com o "
                    f"{l['barbeiro']}. Se precisar remarcar é só me falar 👊",
                ])
            else:
                txt = random.choice([
                    f"{nome}, daqui a pouco, às {l['hora']}, é seu horário com o {l['barbeiro']}. Te esperamos!",
                    f"Opa {nome}! Seu horário é às {l['hora']} hoje. Até já 💈",
                ])
            saida.append((l["telefone"], txt))
        return saida
