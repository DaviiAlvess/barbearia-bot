# 💈 Barbearia Bot

Atendente de barbearia no WhatsApp com IA (Google Gemini), baseado no **Bella Bot**
(github.com/davialvs908/ChatBot-bellabot), com atendimento bem mais humano.

## O que mudou em relação ao Bella Bot

| Bella Bot | Barbearia Bot |
|---|---|
| Menu numerado (1, 2, 3...) | Conversa livre: o cliente escreve como quiser ("tem horário sábado de tarde com o Rafael?") |
| Horários fixos, sem data: um horário marcado ficava ocupado para sempre | Agenda real por **data, barbeiro e duração do serviço**, com almoço, folgas e dias fechados |
| A IA não sabia dos horários (podia inventar) | A IA **consulta a agenda por ferramentas** e nunca inventa horário ou preço |
| Filtro de palavras-chave barrava perguntas normais | A IA entende o contexto e só redireciona de leve quando o assunto foge muito |
| Sem memória | Lembra da conversa e **reconhece o cliente que volta** (nome, barbeiro preferido, como gosta do corte) |
| Textões | Mensagens curtas, divididas em balões, com tempo de "digitando..." e "visto" |
| WhatsApp por QR code com servidor Node à parte (fora do repositório) | Mesmo esquema da Belinha (QR code + Socket.IO), **com o servidor Node incluído**, mais a opção da API oficial da Meta |
| Modelo `gemini-2.0-flash` fixo | Modelo configurável no `.env` |

## Funções

- **Agendar** com data em linguagem natural ("amanhã", "sábado", "semana que vem")
- **Remarcar** e **cancelar** pelo chat
- **Lista de espera**: se o dia estiver lotado e alguém cancelar, quem esperava recebe mensagem na hora
- **Cartão fidelidade**: a cada 10 atendimentos ganha um corte (configurável)
- **Lembretes automáticos**: na véspera (a partir das 18h) e 2h antes
- **Sugestão de estilo**: indica serviço e o barbeiro que manda bem naquilo
- **Passa para um humano** quando o cliente pede, reclama ou está irritado (o bot fica quieto por 2h e avisa o dono)
- Responde áudio/foto pedindo com jeito para escrever
- **Comandos do dono** (pelo WhatsApp do `TELEFONE_DONO`):
  - `#agenda` / `#agenda amanha` / `#agenda 2026-11-21`: agenda do dia com o total em R$
  - `#cancelar 12`: cancela o agendamento #12 (e avisa a lista de espera)
  - `#pausar 5575...`: você assume a conversa / `#bot 5575...`: religa o bot

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env        # coloque sua GEMINI_API_KEY
```

Edite **`config.py`** com o nome, endereço, barbeiros, serviços, preços e horários.

**Testar no terminal:**
```bash
python terminal.py
```
Comandos no terminal: `/telefone 5575...` (simula outro cliente), `/dono`, `/lembretes`, `/sair`.

**Colocar no WhatsApp pelo QR code (mesmo esquema da Belinha):**

Precisa de Node.js 18+ instalado.
```bash
# terminal 1: servidor do WhatsApp
cd servidor-whatsapp
npm install
npm start          # aparece o QR code: WhatsApp > Aparelhos conectados > Conectar
```
```bash
# terminal 2: o bot
python bot_whatsapp.py
```
O login fica salvo; nas próximas vezes não precisa ler o QR de novo.
O protocolo é o mesmo da branch `belinhafuncional` (evento `novaMensagem` e `POST /enviarMensagem`
em `localhost:3000`, sessão `8113`), então também funciona com o servidor Node que vocês já usavam.
Atenção: conexão por QR code não é oficial; use com moderação para o número não ser bloqueado.

**Opção: API oficial da Meta** (mais estável, exige app na Meta e servidor com HTTPS):
1. Crie um app em developers.facebook.com, adicione o produto WhatsApp e pegue o token e o Phone Number ID.
2. Preencha `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_VERIFY_TOKEN` no `.env`.
3. Rode `uvicorn whatsapp:app --host 0.0.0.0 --port 8000` em um servidor com HTTPS
   (para testar no PC dá para usar `ngrok http 8000`).
4. No painel da Meta, cadastre o webhook `https://SEU_ENDERECO/webhook` com o mesmo verify token
   e assine o campo **messages**.

**Testes** (não usam internet, a IA é simulada):
```bash
pip install pytest httpx && python -m pytest -q
```

## Estrutura

```
config.py               dados da barbearia (edite aqui)
terminal.py             chat no terminal
bot_whatsapp.py         bot no WhatsApp pelo QR code (fala com o servidor-whatsapp)
servidor-whatsapp/      servidor Node (whatsapp-web.js) que lê o QR code
whatsapp.py             opção com a API oficial da Meta (webhook)
barbearia/
  atendente.py          orquestra conversa, IA e ferramentas; comandos do dono
  persona.py            personalidade e regras do "Léo" (o atendente)
  ferramentas.py        funções que a IA pode chamar (agenda, fidelidade, humano...)
  agenda.py             regras de horários, conflitos, lista de espera, lembretes
  ia.py                 cliente do Gemini com function calling
  humanizar.py          balões, tempo de digitação, respostas de emergência
  db.py                 SQLite (clientes, agendamentos, conversas, lista de espera)
tests/test_bot.py       17 testes
```

## Para deixar com a cara da sua barbearia

- Troque o nome e o jeito do atendente em `config.py` (`NOME_ATENDENTE`) e o texto em `barbearia/persona.py`.
- `INFO_EXTRA` em `config.py` é onde entram regras da casa (tolerância de atraso, estacionamento etc.).
