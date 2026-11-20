"""
Configuração da barbearia.
Edite este arquivo para endereço, barbeiros, serviços, preços e horários.
O nome do salão também pode ser definido no painel web (Salão).
"""

# Marca do aplicativo (fixa)
NOME_APP = "Agendbarber"

# Nome do salão (padrão). O dono pode trocar no painel → Salão.
NOME_BARBEARIA = "Meu Salão"
ENDERECO = "Rua Exemplo, 123 - Centro, Feira de Santana - BA"
FUSO_HORARIO = "America/Bahia"

# Nome e jeito do atendente virtual (a IA fala como se fosse ele)
NOME_ATENDENTE = "Léo"

# Dias da semana: 0=segunda, 1=terça, ... 6=domingo
# Cada dia: (abre, fecha) ou None se fechado
HORARIO_FUNCIONAMENTO = {
    0: None,                 # segunda: fechado
    1: ("09:00", "19:00"),   # terça
    2: ("09:00", "19:00"),   # quarta
    3: ("09:00", "19:00"),   # quinta
    4: ("09:00", "20:00"),   # sexta
    5: ("08:00", "17:00"),   # sábado
    6: None,                 # domingo: fechado
}

# Pausa do almoço (ninguém é agendado nesse intervalo)
ALMOCO = ("12:00", "13:00")

# De quanto em quanto tempo oferecer horários (minutos)
INTERVALO_AGENDA = 30

# Com quantos dias de antecedência dá para agendar
DIAS_ANTECEDENCIA = 14

# Barbeiros e os dias em que NÃO trabalham (além dos dias fechados)
BARBEIROS = {
    "Rafael": {"folgas": [], "especialidade": "degradê e navalhado"},
    "Diego": {"folgas": [2], "especialidade": "barba e barboterapia"},
    "Thiago": {"folgas": [5], "especialidade": "platinado, luzes e pigmentação"},
}

# Serviços padrão: nome -> (preço em reais, duração em minutos).
# No painel web (Serviços) dá para editar; o que estiver lá vale para o bot.
SERVICOS = {
    "Corte": (35.00, 30),
    "Barba": (25.00, 30),
    "Corte + Barba": (55.00, 60),
    "Pezinho (acabamento)": (10.00, 30),
    "Sobrancelha": (10.00, 30),
    "Pigmentação": (30.00, 30),
    "Hidratação": (20.00, 30),
    "Luzes / Platinado": (120.00, 120),
}

FORMAS_PAGAMENTO = "Pix, dinheiro, débito e crédito"

# Informações extras que a IA pode usar para responder dúvidas
INFO_EXTRA = """
- Tem estacionamento na rua e café de cortesia.
- Atendemos crianças a partir de 3 anos (mesmo preço do corte).
- Tolerância de atraso: 10 minutos. Depois disso pode ser preciso remarcar.
- Para cancelar ou remarcar, é só avisar aqui pelo chat.
"""

# Fidelidade: a cada X atendimentos o cliente ganha um brinde
FIDELIDADE_META = 10
FIDELIDADE_BRINDE = "um corte grátis"
