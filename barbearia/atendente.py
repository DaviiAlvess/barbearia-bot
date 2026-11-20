"""O 'cérebro' do atendimento: junta histórico, IA, ferramentas e humanização.
Funciona com qualquer canal (terminal, WhatsApp...)."""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import timedelta

from barbearia import agenda, db, ferramentas, guardrails, humanizar, persona
from barbearia.ia import ErroIA, _limpar_part

log = logging.getLogger(__name__)

CONVERSA_EXPIRA_HORAS = 6       # depois disso, começa conversa nova (mas lembra do cliente)
MAX_HISTORICO = 40              # quantas mensagens guardar por conversa
MAX_RODADAS_FERRAMENTA = 6
MAX_CARACTERES = 1500           # textos maiores são cortados (evita abuso e gasto de IA)
LIMITE_MENSAGENS = 12           # máximo de mensagens por cliente...
JANELA_SEGUNDOS = 60            # ...dentro desta janela
HORARIO_SILENCIO = (21, 8)      # não manda lembrete/avaliação entre 21h e 8h
FOLLOWUP_MIN_HORAS = 2          # silêncio mínimo antes de retomar conversa esquecida
FOLLOWUP_MAX_HORAS = 18         # depois disso, deixa quieto (próximo "oi" reabre)

Enviar = Callable[[str, str], None]

_travas: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_recentes: defaultdict[str, deque] = defaultdict(deque)


def _cortar_historico(hist: list[dict]) -> list[dict]:
    if len(hist) <= MAX_HISTORICO:
        return hist
    hist = hist[-MAX_HISTORICO:]
    # precisa começar numa mensagem de texto do cliente (não numa resposta de ferramenta)
    while hist and not (hist[0]["role"] == "user" and any("text" in p for p in hist[0]["parts"])):
        hist = hist[1:]
    return hist


def _excedeu_limite(telefone: str, agora: float) -> bool:
    fila = _recentes[telefone]
    while fila and agora - fila[0] > JANELA_SEGUNDOS:
        fila.popleft()
    fila.append(agora)
    return len(fila) > LIMITE_MENSAGENS


def em_horario_de_silencio() -> bool:
    h = agenda.agora().hour
    inicio, fim = HORARIO_SILENCIO
    return h >= inicio or h < fim


_PALAVRAS_ATENDIMENTO = (
    "horário", "horario", "marcar", "agendar", "corte", "barba", "vaga",
    "disponí", "disponi", "sábado", "sabado", "amanhã", "amanha", "hoje",
    "preço", "preco", "serviço", "servico", "barbeiro", "quando", "às", "as ",
)


def _textos_do_historico(hist: list[dict]) -> list[str]:
    textos = []
    for h in hist:
        for p in h.get("parts") or []:
            if "text" in p and p["text"]:
                textos.append(str(p["text"]))
    return textos


def _parece_atendimento_aberto(hist: list[dict]) -> bool:
    """True se a conversa parou no meio (pergunta aberta ou intenção de marcar sem fechar)."""
    if not hist:
        return False
    textos = _textos_do_historico(hist)
    if not textos:
        return False
    ultimo = textos[-1].strip()
    if ultimo.endswith("?"):
        return True
    junto = " ".join(textos).lower()
    if any(p in junto for p in _PALAVRAS_ATENDIMENTO):
        # já agendou nesta conversa? (functionResponse de agendar com ok)
        for h in hist:
            for p in h.get("parts") or []:
                fr = p.get("functionResponse") or {}
                if fr.get("name") == "agendar" and (fr.get("response") or {}).get("ok"):
                    return False
        return True
    return False


class Atendente:
    def __init__(self, ia, enviar: Enviar | None = None):
        """ia: objeto com .gerar(instrucoes, historico, ferramentas)
        enviar(telefone, texto): canal para mensagens ativas (lembretes, lista de espera, dono)."""
        self.ia = ia
        self._enviar_canal = enviar
        db.criar_tabelas()

    # ------------------------------------------------------------------
    def enviar(self, telefone: str, texto: str) -> None:
        """Manda mensagem por iniciativa do bot e guarda para dar contexto à próxima resposta."""
        if not self._enviar_canal:
            return
        if telefone != os.getenv("TELEFONE_DONO"):
            db.guardar_aviso(telefone, texto)
        self._enviar_canal(telefone, texto)

    def responder(self, telefone: str, texto: str) -> list[str]:
        """Recebe a mensagem do cliente e devolve a lista de balões de resposta."""
        texto = (texto or "").strip()[:MAX_CARACTERES]
        if not texto:
            return []
        dono = os.getenv("TELEFONE_DONO")
        if dono and telefone == dono and texto.startswith("#"):
            return [self._comando_dono(texto)]

        agora = time.time()
        if _excedeu_limite(telefone, agora):
            log.warning("Limite de mensagens excedido por %s", telefone)
            return []

        trava = _travas[telefone]
        if not trava.acquire(timeout=90):
            log.error("Timeout na trava de %s — outra resposta travou", telefone)
            return [random.choice(humanizar.SEM_IA)]
        try:
            hist, atualizado, humano_ate = db.carregar_conversa(telefone)
            if humano_ate > agora:
                return []  # um atendente humano está cuidando dessa conversa
            conversa_nova = not hist or agora - atualizado > CONVERSA_EXPIRA_HORAS * 3600
            if conversa_nova:
                hist = []

            avisos = db.pegar_avisos(telefone)
            texto_ia = texto
            if avisos:
                texto_ia = (f"[Contexto: antes desta mensagem, você mandou para o cliente: "
                            f"\"{' | '.join(avisos)}\". Ele está respondendo a isso.]\n{texto}")
                conversa_nova = False  # ele está respondendo a nós; não cumprimenta do zero

            pendentes = agenda.agendamentos_futuros(telefone)
            instrucoes = persona.montar(
                db.obter_cliente(telefone),
                db.ultimo_atendimento(telefone),
                conversa_nova,
                pendentes=pendentes,
            )
            inicio_turno = len(hist)
            hist.append({"role": "user", "parts": [{"text": texto_ia}]})

            try:
                resposta = self._rodar_ia(instrucoes, hist, telefone)
            except ErroIA as e:
                log.error("Falha na IA para %s: %s", telefone, e)
                for aviso in avisos:  # devolve os avisos para não perder o contexto
                    db.guardar_aviso(telefone, aviso)
                err = str(e).lower()
                if "429" in err or "quota" in err or "resource_exhausted" in err:
                    return [(
                        "Tô com bastante movimento agora. Me manda de novo em alguns minutos "
                        "que eu te atendo na hora, beleza?"
                    )]
                return [random.choice(humanizar.SEM_IA)]

            apagou = any(p.get("functionCall", {}).get("name") == "apagar_meus_dados"
                         for h in hist[inicio_turno:] for p in h["parts"])
            if not apagou:  # se o cliente pediu para apagar os dados, não guarda nem a conversa
                db.salvar_conversa(telefone, _cortar_historico(hist), agora)
            limpa = guardrails.sanitizar_resposta(resposta)
            return humanizar.em_baloes(limpa) or ["Desculpa, não entendi bem. Pode me explicar de novo?"]
        finally:
            trava.release()

    def _rodar_ia(self, instrucoes: str, hist: list[dict], telefone: str) -> str:
        for _ in range(MAX_RODADAS_FERRAMENTA):
            conteudo = self.ia.gerar(instrucoes, hist, ferramentas.DECLARACOES)
            # Guarda só campos aceitos pela API (sem thoughtSignature)
            parts = [lp for p in conteudo.get("parts") or [] if (lp := _limpar_part(p))]
            hist.append({"role": "model", "parts": parts})
            chamadas = [p["functionCall"] for p in parts if "functionCall" in p]
            if not chamadas:
                return "".join(p.get("text", "") for p in parts)
            respostas = []
            for c in chamadas:
                resultado = ferramentas.executar(c["name"], c.get("args") or {}, telefone, self.enviar)
                log.info("Ferramenta %s(%s) -> %s", c["name"], c.get("args"), str(resultado)[:200])
                respostas.append({"functionResponse": {"name": c["name"], "response": resultado}})
            hist.append({"role": "user", "parts": respostas})
        raise ErroIA("A IA ficou em loop chamando ferramentas")

    # ------------------------------------------------------------------
    def _comando_dono(self, texto: str) -> str:
        partes = texto.split()
        try:
            return self._executar_comando(partes[0].lower(), partes[1:], texto)
        except (agenda.ErroAgenda, ValueError) as e:
            return f"⚠️ {e}"

    @staticmethod
    def _data_arg(arg: str):
        hoje = agenda.agora().date()
        if not arg or arg.lower() == "hoje":
            return hoje
        if arg.lower().startswith("amanh"):
            return hoje + timedelta(days=1)
        if "/" in arg:  # aceita 25/12
            dia, mes = arg.split("/")[:2]
            d = hoje.replace(month=int(mes), day=int(dia))
            return d if d >= hoje else d.replace(year=d.year + 1)
        return agenda.ler_data(arg)

    def _executar_comando(self, cmd: str, args: list[str], texto: str) -> str:
        arg = args[0] if args else ""
        if cmd == "#agenda":
            d = self._data_arg(arg)
            itens = agenda.agenda_do_dia(d)
            if not itens:
                return f"📅 {d.strftime('%d/%m')}: nenhum horário marcado."
            total = sum(i["preco"] or 0 for i in itens)
            linhas = [f"{i['inicio'][11:]} {i['barbeiro']}: {i['servico']} - {i['nome_cliente']} (#{i['id']})"
                      for i in itens]
            return (f"📅 Agenda {d.strftime('%d/%m')} ({len(itens)} atendimentos, R$ {total:.2f}):\n"
                    + "\n".join(linhas))
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
        if cmd == "#folga" and len(args) < 2:
            return "Use: #folga <data> <barbeiro>"
        if cmd in ("#fechar", "#folga") and arg:
            d = self._data_arg(arg)
            barbeiro = args[1] if cmd == "#folga" else None
            motivo = " ".join(args[1:] if cmd == "#fechar" else args[2:]) or None
            afetados = agenda.bloquear(d.isoformat(), barbeiro, motivo)
            msg = f"🚫 {d.strftime('%d/%m')} bloqueado para {barbeiro or 'a barbearia'}."
            if afetados:
                msg += "\nAtenção, já tinha gente marcada (remarque com eles):\n" + "\n".join(
                    f"{a['inicio'][11:]} {a['barbeiro']} - {a['nome_cliente']} {a['telefone']} (#{a['id']})"
                    for a in afetados)
            return msg
        if cmd == "#abrir" and arg:
            d = self._data_arg(arg)
            n = agenda.desbloquear(d.isoformat(), args[1] if len(args) > 1 else None)
            return f"✅ {d.strftime('%d/%m')} liberado." if n else "Não tinha bloqueio nesse dia."
        if cmd == "#avaliacoes":
            r = agenda.resumo_avaliacoes()
            if not r["por_barbeiro"]:
                return "⭐ Ainda não tem avaliações nos últimos 30 dias."
            linhas = [f"{b['barbeiro']}: {b['media']}⭐ ({b['total']} avaliações)" for b in r["por_barbeiro"]]
            linhas += [f"• {c['nota']}⭐ {c['barbeiro']}: \"{c['comentario']}\" - {c['nome_cliente']}"
                       for c in r["comentarios"][:5]]
            return "⭐ Últimos 30 dias:\n" + "\n".join(linhas)
        if cmd == "#aviso" and len(args) >= 2:
            numero, mensagem = args[0], texto.split(maxsplit=2)[2]
            self.enviar(numero, mensagem)
            return f"📤 Enviado para {numero}."
        return ("Comandos do dono:\n"
                "#agenda [hoje|amanha|25/12]\n"
                "#cancelar <id>\n"
                "#fechar <data> [motivo]  (feriado, reforma...)\n"
                "#folga <data> <barbeiro>\n"
                "#abrir <data> [barbeiro]\n"
                "#avaliacoes\n"
                "#aviso <telefone> <mensagem>\n"
                "#pausar <telefone>  (você assume a conversa)\n"
                "#bot <telefone>  (religa o bot)")

    # ------------------------------------------------------------------
    def mensagens_programadas(self) -> list[tuple[str, str]]:
        """Lembretes, avaliações e retomada de conversas esquecidas: [(telefone, texto)]."""
        if em_horario_de_silencio():
            return []
        saida = [(lem["telefone"], self._texto_lembrete(lem)) for lem in agenda.lembretes_pendentes()]
        for a in agenda.avaliacoes_pendentes():
            nome = (a["nome"] or "").split(" ")[0]
            saud = f", {nome}" if nome else ""
            saida.append((a["telefone"], random.choice([
                f"Oi{saud}! Obrigado pela visita hoje 🙏 De 1 a 5, que nota você dá pro atendimento "
                f"do {a['barbeiro']}? Se quiser, conta o que achou.",
                f"E aí{saud}, curtiu o resultado? Se puder, dá uma nota de 1 a 5 pro atendimento "
                f"do {a['barbeiro']}. Ajuda muito a gente a melhorar!",
            ])))
        saida.extend(self._followups_esquecidos())
        return saida

    def _followups_esquecidos(self) -> list[tuple[str, str]]:
        """Retoma conversas que pararam no meio do atendimento (sem insistir demais)."""
        agora = time.time()
        saida = []
        for row in db.conversas_esquecidas(
            agora,
            min_silencio=FOLLOWUP_MIN_HORAS * 3600,
            max_idade=FOLLOWUP_MAX_HORAS * 3600,
        ):
            telefone = row["telefone"]
            if not db.aceita_mensagens(telefone):
                continue
            try:
                hist = json.loads(row["historico"]) if isinstance(row["historico"], str) else row["historico"]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not _parece_atendimento_aberto(hist or []):
                continue
            # já tem horário marcado: não fica cobrando; o lembrete de agenda cobre
            if agenda.agendamentos_futuros(telefone):
                db.marcar_followup(telefone, agora)
                continue
            cliente = db.obter_cliente(telefone) or {}
            nome = (cliente.get("nome") or "").split(" ")[0]
            saud = f", {nome}" if nome else ""
            texto = random.choice([
                f"Oi{saud}! Vi que a gente ficou no meio do papo. Ainda quer marcar o horário?",
                f"E aí{saud}, conseguiu decidir? Se quiser, eu fecho o horário pra você por aqui.",
                f"Oi{saud}, passando de novo: ainda posso te ajudar a marcar? Se mudou de ideia, "
                f"é só falar 👍",
            ])
            db.marcar_followup(telefone, agora)
            saida.append((telefone, texto))
        return saida

    def enviar_programadas(self) -> int:
        """Manda lembretes, avaliações e follow-ups. Chame de tempos em tempos (ex.: a cada 5 min)."""
        mensagens = self.mensagens_programadas()
        for telefone, texto in mensagens:
            self.enviar(telefone, texto)
        return len(mensagens)

    @staticmethod
    def _texto_lembrete(lembrete: dict) -> str:
        nome = (lembrete["nome"] or "").split(" ")[0]
        saud = f", {nome}" if nome else ""
        servico = lembrete["servico"].lower()
        if lembrete["tipo"] == "vespera":
            return random.choice([
                f"Oi{saud}, tudo bem? Passando pra lembrar do seu horário amanhã às {lembrete['hora']} "
                f"com o {lembrete['barbeiro']} ({servico}). Podemos confirmar?",
                f"Boa noite{saud}! Amanhã às {lembrete['hora']} tem {servico} com o {lembrete['barbeiro']}. "
                f"Se precisar remarcar, é só me avisar por aqui 😉",
            ])
        return random.choice([
            f"Oi{saud}! Seu horário com o {lembrete['barbeiro']} é hoje às {lembrete['hora']}. "
            f"Estamos te esperando 💈",
            f"Passando pra lembrar{saud}: hoje às {lembrete['hora']} com o {lembrete['barbeiro']}. "
            f"Até daqui a pouco!",
        ]) + f"\n📍 {db.endereco()}"
