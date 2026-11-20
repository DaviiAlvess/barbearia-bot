# Agendbarber

Atendente de barbearia no WhatsApp com IA (Google Gemini). O app se chama **Agendbarber**;
o nome do seu salão você define no painel (**Salão**). Feito a partir do Bella Bot
(branch `belinhafuncional`). O atendimento é mais humano, educado e completo.

![testes](https://github.com/DaviiAlvess/barbearia-bot/actions/workflows/testes.yml/badge.svg)

## Como é a conversa

```
Cliente: fala, tem horário sábado de tarde com o Rafael?
Léo:     Boa noite! Tenho sim 😊 Sábado com o Rafael tem 14:00, 14:30 e 15:30.
Léo:     Qual fica melhor pra você?
Cliente: 14h, corte e barba. Meu nome é Marcos
Léo:     Fechado, Marcos: corte + barba no sábado (21/11) às 14:00 com o Rafael, R$ 55,00. Posso confirmar?
Cliente: pode
Léo:     Prontinho, tá marcado! Obrigado pela preferência 🙏
Léo:     Fica na Rua Exemplo, 123 - Centro. Até sábado!
```

## O que mudou em relação ao Bella Bot

| Bella Bot | Barbearia Bot |
|---|---|
| Menu numerado e fluxo engessado | Conversa livre: o cliente escreve do jeito dele |
| A IA não via a agenda (podia inventar) | A IA **consulta a agenda por ferramentas** e nunca inventa horário ou preço |
| Horários sem data e sem duração | Agenda por **data, barbeiro e duração**, com almoço, folgas, feriados e dias fechados |
| Textões | Mensagens curtas em balões, com "digitando..." |
| Esquecia tudo | Lembra da conversa e **reconhece quem volta** (nome, barbeiro preferido, estilo) |
| Chave da API escrita no código | Chave só no `.env`, que nunca vai para o GitHub |
| WhatsApp via whatsapp-web.js (Chromium) | **Evolution API** (Baileys) — QR no painel, sem Chrome no container |

## Funções

**Para o cliente**
- Agendar com data em linguagem natural ("amanhã", "sábado", "semana que vem")
- Remarcar e cancelar pelo chat
- Lista de espera: se o dia está lotado e alguém cancela, ele recebe uma mensagem na hora
- Cartão fidelidade: a cada 10 atendimentos ganha um corte (configurável)
- Lembretes na véspera e 2h antes, com o endereço
- Pedido de avaliação (nota de 1 a 5) depois do atendimento
- Sugestão de estilo e de barbeiro
- Pode pedir para **não receber mais mensagens** ou **apagar os dados** (LGPD)
- Áudio e foto: o bot pede com educação para escrever

**Para o dono**
- Alerta no WhatsApp quando um cliente pede atendimento humano ou dá nota baixa
- Comandos pelo WhatsApp do `TELEFONE_DONO`:

| Comando | O que faz |
|---|---|
| `#agenda` / `#agenda amanha` / `#agenda 25/12` | Agenda do dia com o total em R$ |
| `#cancelar 12` | Cancela o agendamento #12 e avisa a lista de espera |
| `#fechar 25/12 Natal` | Fecha a barbearia no dia (e mostra quem já estava marcado) |
| `#folga 28/11 Rafael` | Folga de um barbeiro |
| `#abrir 25/12` | Desfaz o bloqueio |
| `#avaliacoes` | Média de cada barbeiro e últimos comentários |
| `#aviso 5575... texto` | Manda uma mensagem para um cliente |
| `#pausar 5575...` / `#bot 5575...` | Você assume a conversa / religa o bot |

- **Painel web** (`painel.py`): agenda por dia, cancelar, folgas e feriados, avaliações. Protegido por senha.

## Boas maneiras do atendente

O atendente "Léo" segue regras de etiqueta (veja `barbearia/persona.py`):
- É educado ("por favor", "obrigado") e trata o cliente pelo nome, sem apelidos como "mano" ou "querido".
- Não insiste quando o cliente diz que vai pensar e não comenta aparência, peso, idade ou vida pessoal.
- Pede desculpas quando algo dá errado e, se o cliente estiver irritado, chama um humano.
- Só pede o nome, nunca CPF, endereço ou e-mail.
- Não diz que é humano. Se perguntarem, diz com honestidade que é o atendimento automático.
- Não manda lembretes nem avaliações entre 21h e 8h e respeita quem pediu para parar.

## Como rodar

### 1. Configurar
```bash
pip install -r requirements.txt
cp .env.example .env      # coloque GEMINI_API_KEY, TELEFONE_DONO e PAINEL_SENHA
```
Edite **`config.py`** com nome, endereço, barbeiros, serviços, preços e horários.

### 2. Testar no terminal
```bash
python terminal.py
```
Comandos: `/telefone 5575...` (simula outro cliente), `/dono`, `/lembretes`, `/sair`.

### 3. WhatsApp com Evolution API (QR code)
O stack usa a [Evolution API](https://docs.evolutionfoundation.com.br/evolution-api)
(Baileys). No Docker Compose ela sobe sozinha; o bot recebe mensagens por webhook
e o painel mostra o QR.

```bash
docker compose up -d --build
# abra o painel → página WhatsApp e escaneie o QR
```

Localmente (sem Compose completo): suba a Evolution (`evoapicloud/evolution-api`),
defina `EVOLUTION_URL`, `EVOLUTION_API_KEY` e `EVOLUTION_WEBHOOK_URL` no `.env`,
depois:

```bash
uvicorn bot_whatsapp:app --port 8000
uvicorn painel:app --port 8080
```

Conexão por QR não é a API oficial da Meta: use com moderação.

### 4. Painel do dono
```bash
uvicorn painel:app --port 8080
```
Abra http://localhost:8080 (senha `PAINEL_SENHA`).
Na página **WhatsApp** você lê o QR Code no navegador.

### Tudo de uma vez com Docker
```bash
docker compose up -d --build
# QR: painel → /whatsapp  (ou logs: docker compose logs -f evolution)
```

### Na mesma VPS de outro projeto (Ubuntu) — isolamento forte
Recomendado: usuário Linux `barbearia` + **Docker rootless** (sem sudo, sem grupo
`docker` do sistema). Assim o bot não enxerga o código/banco do outro projeto
(ex.: Condo Organize), tem teto de RAM e o painel abre só por túnel SSH
(sem mexer no Nginx dele).

```bash
# 1) como root, uma vez:
sudo bash deploy/setup-rootless.sh

# 2) como usuário barbearia:
sudo -iu barbearia
git clone https://github.com/DaviiAlvess/barbearia-bot.git ~/barbearia-bot
bash ~/barbearia-bot/deploy/instalar-bot.sh
# edite o .env (GEMINI, PAINEL_SENHA, EVOLUTION_API_KEY), rode o instalar de novo
# escaneie o QR em https://barbearia.SEU_DOMINIO/whatsapp
```

Passo a passo completo, tabela do que fica separado e troubleshooting:
**[`deploy/README.md`](deploy/README.md)**.

### Opção: API oficial da Meta
Mais estável, mas exige um app na Meta e um servidor com HTTPS. Preencha `WHATSAPP_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_VERIFY_TOKEN`, rode `uvicorn whatsapp:app --port 8000`
e cadastre `https://SEU_ENDERECO/webhook` no painel da Meta (campo **messages**).

## Desenvolvimento

```bash
pip install -r requirements-dev.txt
pytest -q        # 26 testes, sem internet (a IA é simulada)
ruff check .     # padrão de código
```
O GitHub Actions roda os testes e o lint a cada push.

## Estrutura

```
config.py                dados da barbearia (edite aqui)
terminal.py              chat no terminal
bot_whatsapp.py          webhook Evolution + atendente
whatsapp.py              opção com a API oficial da Meta
painel.py                painel web do dono (agenda + QR)
docker-compose.yml       evolution + bot + painel
barbearia/
  evolution.py           cliente da Evolution API (QR, envio, webhook helpers)
  atendente.py           conversa, IA, ferramentas, comandos do dono, lembretes
  persona.py             personalidade e boas maneiras do atendente
  ferramentas.py         o que a IA pode fazer (agendar, remarcar, avaliar...)
  agenda.py              horários, conflitos, bloqueios, lista de espera, avaliações
  ia.py                  cliente do Gemini com function calling
  humanizar.py           balões, tempo de digitação, respostas de emergência
  db.py                  SQLite com migração automática
tests/test_bot.py        testes
```

## Privacidade (LGPD)

- Guardamos só o necessário: telefone, nome, preferências de corte e histórico de agendamentos.
- O cliente pode pedir pelo chat para não receber mensagens ou para apagar os dados.
- Nunca suba o `.env` ou o arquivo `.db` para o GitHub (o `.gitignore` já bloqueia).

## Licença

MIT. Veja `LICENSE`.
