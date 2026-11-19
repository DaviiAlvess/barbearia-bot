"""Ferramentas que a IA pode chamar. É assim que ela consulta a agenda de verdade
em vez de inventar horário ou preço."""
import os
import time

import config
from barbearia import agenda, db

PAUSA_HUMANO_HORAS = 2

DECLARACOES = [
    {
        "name": "ver_horarios_livres",
        "description": "Consulta os horários livres de um dia para um serviço. "
                       "Use SEMPRE antes de oferecer ou confirmar um horário.",
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
        "description": "Marca o horário. Só chame depois que o cliente confirmou dia, hora e serviço "
                       "e você já sabe o nome dele.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_cliente": {"type": "string"},
                "data": {"type": "string", "description": "AAAA-MM-DD"},
                "hora": {"type": "string", "description": "HH:MM"},
                "servico": {"type": "string"},
                "barbeiro": {"type": "string", "description": "Opcional. Se vazio, pega quem estiver livre"},
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
        "name": "ver_fidelidade",
        "description": "Mostra quantos atendimentos o cliente já fez e quanto falta para o brinde do cartão fidelidade.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "lembrar_cliente",
        "description": "Guarda o nome do cliente, o barbeiro preferido ou uma observação útil "
                       "(ex.: 'gosta de degradê na régua 1'). Use assim que descobrir algo assim.",
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
        dia = agenda.ler_data(a["data"])
        enviar(a["telefone"],
               f"Opa! Abriu vaga {agenda.DIAS_SEMANA[dia.weekday()]} ({dia.strftime('%d/%m')}) "
               f"pra {a['servico'].lower()}: {', '.join(a['horarios'])}. Quer que eu reserve algum?")


def executar(nome, args, telefone, enviar=None):
    """Roda a ferramenta e devolve um dict (que volta para a IA).
    enviar(telefone, texto) é usado para mandar mensagem para outras pessoas
    (dono da barbearia, clientes da lista de espera)."""
    try:
        if nome == "ver_horarios_livres":
            return agenda.horarios_livres(args.get("data"), args.get("servico", ""), args.get("barbeiro"))
        if nome == "agendar":
            r = agenda.agendar(telefone, args.get("nome_cliente"), args.get("data"),
                               args.get("hora"), args.get("servico", ""), args.get("barbeiro"))
            db.salvar_cliente(telefone, nome=args.get("nome_cliente"))
            return r
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
        if nome == "ver_fidelidade":
            return agenda.fidelidade(telefone)
        if nome == "lembrar_cliente":
            barbeiro = args.get("barbeiro_preferido")
            if barbeiro:
                barbeiro = agenda.achar_barbeiro(barbeiro)
            db.salvar_cliente(telefone, args.get("nome"), barbeiro, args.get("observacoes"))
            return {"ok": True}
        if nome == "chamar_atendente_humano":
            db.pausar_bot(telefone, time.time() + PAUSA_HUMANO_HORAS * 3600)
            dono = os.getenv("TELEFONE_DONO")
            if enviar and dono:
                enviar(dono, f"🔔 {config.NOME_BARBEARIA}: cliente {telefone} precisa de atendimento. "
                            f"Motivo: {args.get('motivo')}")
            return {"ok": True, "info": "Um atendente vai assumir. Avise o cliente de forma natural."}
        return {"erro": f"Ferramenta desconhecida: {nome}"}
    except agenda.ErroAgenda as e:
        return {"erro": str(e)}
    except (TypeError, ValueError) as e:
        return {"erro": f"Parâmetro inválido: {e}"}
