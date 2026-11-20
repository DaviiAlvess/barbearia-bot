"""Ferramentas que a IA pode chamar. É assim que ela consulta a agenda de verdade
em vez de inventar horário ou preço."""
import time

from barbearia import agenda, db

PAUSA_HUMANO_HORAS = 2

DECLARACOES = [
    {
        "name": "resolver_data",
        "description": "Converte o que o cliente disse (hoje, amanhã, sábado, 21/11, 2026-11-21) "
                       "na data certa e no dia da semana CORRETO. Use SEMPRE antes de falar "
                       "qual dia da semana é, e antes de chamar ver_horarios_livres/agendar. "
                       "Nunca invente dia da semana de cabeça.",
        "parameters": {
            "type": "object",
            "properties": {
                "quando": {
                    "type": "string",
                    "description": "Texto do cliente: 'sábado', 'amanhã', '21/11', '2026-11-21'…",
                },
            },
            "required": ["quando"],
        },
    },
    {
        "name": "ver_horarios_livres",
        "description": "Consulta a agenda REAL de um dia para um serviço: desconta o que já "
                       "está marcado e só devolve horários em que a DURAÇÃO do serviço cabe "
                       "inteira (sem bater em outro cliente, almoço ou fechamento). "
                       "Use SEMPRE antes de oferecer/confirmar horário ou quando o cliente "
                       "pedir 'todos os horários', 'o que tem vago', 'quais livres'. "
                       "Precisa do serviço (a duração muda o que cabe). "
                       "Data AAAA-MM-DD via resolver_data. Fale só com livres_por_barbeiro — "
                       "nunca invente. ocupados_por_barbeiro mostra o que já foi preenchido.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data no formato AAAA-MM-DD"},
                "servico": {"type": "string", "description": "Nome do serviço, ex.: Corte, Barba, Corte + Barba"},
                "barbeiro": {"type": "string", "description": "Opcional. Nome do barbeiro preferido"},
            },
            "required": ["data", "servico"],
        },
    },
    {
        "name": "agendar",
        "description": "Marca o horário. Só chame DEPOIS de: (1) ter o nome, (2) serviço da tabela, "
                       "(3) data via resolver_data, (4) horários via ver_horarios_livres, "
                       "(5) cliente confirmou com 'sim'. A data deve ser AAAA-MM-DD.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_cliente": {"type": "string"},
                "data": {"type": "string", "description": "AAAA-MM-DD (de resolver_data)"},
                "hora": {"type": "string", "description": "HH:MM (deve estar em ver_horarios_livres)"},
                "servico": {"type": "string", "description": "Nome EXATO da tabela de serviços"},
                "barbeiro": {"type": "string", "description": "Opcional. Se vazio, pega quem estiver livre"},
            },
            "required": ["nome_cliente", "data", "hora", "servico"],
        },
    },
    {
        "name": "checar_horario",
        "description": "MODO DONO: verifica se um horário pedido está livre na agenda "
                       "(considerando o serviço). Se estiver ocupado, devolve quem está lá "
                       "(ocupado_com com nome_cliente), o mais próximo e os vagos até fechar. "
                       "Use SEMPRE antes de agendar_para_cliente.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "AAAA-MM-DD"},
                "hora": {"type": "string", "description": "HH:MM pedida"},
                "servico": {"type": "string"},
                "barbeiro": {"type": "string", "description": "Opcional. Nome do profissional"},
            },
            "required": ["data", "hora", "servico"],
        },
    },
    {
        "name": "quem_no_horario",
        "description": "MODO DONO: responde 'quem está nesse horário?' / 'quem é às 15h?'. "
                       "Devolve nome do cliente, serviço, início/fim e telefone se houver. "
                       "Não invente — só o que a ferramenta retornar.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "AAAA-MM-DD (hoje se o dono não disser)"},
                "hora": {"type": "string", "description": "HH:MM"},
                "barbeiro": {"type": "string", "description": "Opcional"},
            },
            "required": ["data", "hora"],
        },
    },
    {
        "name": "agendar_para_cliente",
        "description": "MODO DONO: marca horário para um cliente (nome) na agenda. "
                       "Só depois de checar_horario e o dono aprovar o horário. "
                       "telefone_cliente é opcional (WhatsApp do cliente).",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_cliente": {"type": "string"},
                "data": {"type": "string", "description": "AAAA-MM-DD"},
                "hora": {"type": "string", "description": "HH:MM aprovada"},
                "servico": {"type": "string"},
                "barbeiro": {"type": "string", "description": "Opcional"},
                "telefone_cliente": {
                    "type": "string",
                    "description": "Opcional. WhatsApp do cliente com DDD",
                },
            },
            "required": ["nome_cliente", "data", "hora", "servico"],
        },
    },
    {
        "name": "meus_agendamentos",
        "description": "Lista os próximos horários marcados por este cliente (para lembrar, cancelar ou remarcar).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancelar_agendamento",
        "description": "Cancela um agendamento do cliente pelo id (pegue o id em meus_agendamentos). "
                       "Para trocar de horário use remarcar_agendamento.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "remarcar_agendamento",
        "description": "Troca um agendamento existente para outro dia/hora (mesmo serviço). "
                       "Confira antes com ver_horarios_livres e confirme com o cliente.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "nova_data": {"type": "string", "description": "AAAA-MM-DD"},
                "nova_hora": {"type": "string", "description": "HH:MM"},
                "barbeiro": {"type": "string", "description": "Opcional. Para trocar de barbeiro"},
            },
            "required": ["id", "nova_data", "nova_hora"],
        },
    },
    {
        "name": "entrar_lista_espera",
        "description": "Coloca o cliente na lista de espera de um dia lotado. Se alguém cancelar, "
                       "ele recebe uma mensagem automática. Ofereça quando não houver horário bom.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "AAAA-MM-DD"},
                "servico": {"type": "string"},
                "barbeiro": {"type": "string", "description": "Opcional"},
            },
            "required": ["data", "servico"],
        },
    },
    {
        "name": "ver_tabela_servicos",
        "description": "ÚNICA fonte de serviços/preços. Use antes de citar qualquer serviço. "
                       "Nunca invente item que não venha nesta resposta.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "ver_fidelidade",
        "description": "Mostra quantos atendimentos o cliente já fez e quanto falta para o brinde do cartão fidelidade.",
        "parameters": {"type": "object", "properties": {}},
    },

    {
        "name": "lembrar_cliente",
        "description": "Guarda o nome do cliente, o barbeiro preferido ou uma observação útil "
                       "(ex.: 'gosta de degradê na régua 1'). Use ASSIM QUE o cliente disser o nome "
                       "(primeiro contato) ou qualquer preferência — não espere até agendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {"type": "string"},
                "barbeiro_preferido": {"type": "string"},
                "observacoes": {"type": "string"},
            },
        },
    },
    {
        "name": "registrar_avaliacao",
        "description": "Guarda a nota (1 a 5) e o comentário que o cliente deu sobre o último atendimento.",
        "parameters": {
            "type": "object",
            "properties": {
                "nota": {"type": "integer", "description": "1 a 5"},
                "comentario": {"type": "string"},
            },
            "required": ["nota"],
        },
    },
    {
        "name": "preferencia_mensagens",
        "description": "Liga ou desliga lembretes, avisos e pedidos de avaliação para este cliente. "
                       "Use aceita=false se ele pedir para não receber mais mensagens (ex.: 'parar', 'sair').",
        "parameters": {
            "type": "object",
            "properties": {"aceita": {"type": "boolean"}},
            "required": ["aceita"],
        },
    },
    {
        "name": "apagar_meus_dados",
        "description": "Apaga os dados do cliente (LGPD) e cancela os horários futuros dele. "
                       "Só chame depois de o cliente confirmar que quer mesmo apagar.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "chamar_atendente_humano",
        "description": "Passa a conversa para uma pessoa da barbearia. Use se o cliente pedir, "
                       "estiver irritado, for reclamação, pedido especial ou algo que você não resolve.",
        "parameters": {
            "type": "object",
            "properties": {"motivo": {"type": "string"}},
            "required": ["motivo"],
        },
    },
]


def avisar_lista_espera(data_iso, barbeiro, enviar):
    for a in agenda.quem_esperava(data_iso, barbeiro):
        if not db.aceita_mensagens(a["telefone"]):
            continue
        dia = agenda.ler_data(a["data"])
        enviar(a["telefone"],
               f"Opa! Abriu vaga {agenda.DIAS_SEMANA[dia.weekday()]} ({dia.strftime('%d/%m')}) "
               f"pra {a['servico'].lower()}: {', '.join(a['horarios'])}. Quer que eu reserve algum?")


def executar(nome, args, telefone, enviar=None):
    """Roda a ferramenta e devolve um dict (que volta para a IA).
    enviar(telefone, texto) é usado para mandar mensagem para outras pessoas
    (dono da barbearia, clientes da lista de espera)."""
    try:
        if nome == "resolver_data":
            return agenda.interpretar_data(args.get("quando") or args.get("data") or "")
        if nome == "ver_horarios_livres":
            return agenda.horarios_livres(args.get("data"), args.get("servico", ""), args.get("barbeiro"))
        if nome == "agendar":
            r = agenda.agendar(telefone, args.get("nome_cliente"), args.get("data"),
                               args.get("hora"), args.get("servico", ""), args.get("barbeiro"))
            db.salvar_cliente(telefone, nome=args.get("nome_cliente"))
            return r
        if nome == "checar_horario":
            return agenda.checar_horario_pedido(
                args.get("data"), args.get("hora"), args.get("servico", ""), args.get("barbeiro"),
            )
        if nome == "quem_no_horario":
            return agenda.quem_no_horario(
                args.get("data"), args.get("hora"), args.get("barbeiro"),
            )
        if nome == "agendar_para_cliente":
            from barbearia.atendente import _eh_dono
            if not _eh_dono(telefone):
                return {"erro": "Só o dono cadastrado pode marcar horário para outra pessoa."}
            tel_informado = db.normalizar_telefone(args.get("telefone_cliente") or "")
            tel_cli = tel_informado or f"90{int(time.time()) % 10**9:09d}"
            nome_cli = (args.get("nome_cliente") or "").strip()
            if not nome_cli:
                return {"erro": "Informe o nome da pessoa."}
            r = agenda.agendar(
                tel_cli, nome_cli, args.get("data"), args.get("hora"),
                args.get("servico", ""), args.get("barbeiro"),
            )
            if tel_informado:
                db.salvar_cliente(tel_cli, nome=nome_cli)
            return {**r, "telefone_cliente": tel_cli, "nome_cliente": nome_cli}
        if nome == "meus_agendamentos":
            return {"agendamentos": agenda.agendamentos_futuros(telefone)}
        if nome == "cancelar_agendamento":
            r = agenda.cancelar(telefone, int(args.get("id")))
            if enviar:
                c = r["cancelado"]
                avisar_lista_espera(c["inicio"][:10], c["barbeiro"], enviar)
            return r
        if nome == "remarcar_agendamento":
            r = agenda.remarcar(telefone, int(args.get("id")), args.get("nova_data"),
                                args.get("nova_hora"), args.get("barbeiro"))
            if enviar:
                avisar_lista_espera(r["antigo"][:10], r["antigo_barbeiro"], enviar)
            return r
        if nome == "entrar_lista_espera":
            return agenda.entrar_lista_espera(telefone, args.get("data"), args.get("servico", ""),
                                              args.get("barbeiro"))
        if nome == "ver_tabela_servicos":
            tabela = [
                {"servico": n, "preco": p, "minutos": m}
                for n, (p, m) in db.listar_servicos().items()
            ]
            return {"servicos": tabela, "texto": db.tabela_servicos_texto()}
        if nome == "ver_fidelidade":
            return agenda.fidelidade(telefone)
        if nome == "lembrar_cliente":
            barbeiro = args.get("barbeiro_preferido")
            if barbeiro:
                barbeiro = agenda.achar_barbeiro(barbeiro)
            db.salvar_cliente(telefone, args.get("nome"), barbeiro, args.get("observacoes"))
            return {"ok": True}
        if nome == "registrar_avaliacao":
            r = agenda.registrar_avaliacao(telefone, args.get("nota"), args.get("comentario"))
            from barbearia.atendente import telefone_dono
            dono = telefone_dono()
            if enviar and dono and r["nota"] <= 3:
                enviar(dono, f"⚠️ Avaliação {r['nota']}/5 para {r['barbeiro']} (cliente {telefone}): "
                             f"{args.get('comentario') or 'sem comentário'}")
            return r
        if nome == "preferencia_mensagens":
            db.definir_aceita_mensagens(telefone, bool(args.get("aceita")))
            return {"ok": True, "aceita_mensagens": bool(args.get("aceita"))}
        if nome == "apagar_meus_dados":
            cancelados = 0
            for ag in agenda.agendamentos_futuros(telefone):
                agenda.cancelar(telefone, ag["id"])
                cancelados += 1
            db.apagar_dados_cliente(telefone)
            return {"ok": True, "horarios_cancelados": cancelados}
        if nome == "chamar_atendente_humano":
            db.pausar_bot(telefone, time.time() + PAUSA_HUMANO_HORAS * 3600)
            from barbearia.atendente import telefone_dono
            dono = telefone_dono()
            if enviar and dono:
                enviar(dono, f"🔔 {db.nome_salao()}: cliente {telefone} precisa de atendimento. "
                            f"Motivo: {args.get('motivo')}")
            return {"ok": True, "info": "Um atendente vai assumir. Avise o cliente de forma natural."}
        return {"erro": f"Ferramenta desconhecida: {nome}"}
    except agenda.ErroAgenda as e:
        return {"erro": str(e)}
    except (TypeError, ValueError) as e:
        return {"erro": f"Parâmetro inválido: {e}"}
