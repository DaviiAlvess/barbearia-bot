// Servidor que conecta o WhatsApp (pelo QR code) ao bot em Python.
// Mesmo esquema da Belinha: emite "novaMensagem" por Socket.IO e recebe POST /enviarMensagem.
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const qrcode = require('qrcode-terminal');
const { Client, LocalAuth } = require('whatsapp-web.js');

const PORTA = process.env.PORTA || 3000;
const ID_SESSAO = process.env.ID_SESSAO || '8113';

const app = express();
app.use(express.json());
const server = http.createServer(app);
const io = new Server(server);

const client = new Client({
  authStrategy: new LocalAuth({ clientId: `sessao-${ID_SESSAO}` }), // não precisa ler o QR toda vez
  puppeteer: {
    headless: true,
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  },
});

let pronto = false;

client.on('qr', (qr) => {
  console.log('📱 Escaneie o QR code no WhatsApp > Aparelhos conectados:');
  qrcode.generate(qr, { small: true });
});
client.on('ready', () => { pronto = true; console.log('✅ WhatsApp conectado!'); });
client.on('disconnected', (motivo) => {
  pronto = false;
  console.log('⚠️ WhatsApp desconectado:', motivo, '- reiniciando...');
  client.initialize();
});

client.on('message', async (msg) => {
  if (msg.fromMe || msg.isStatus || msg.from.endsWith('@g.us')) return;
  io.emit('novaMensagem', {
    idSessao: ID_SESSAO,
    id: msg.id._serialized,
    from: msg.from,
    body: msg.body || '',
    type: msg.type,
  });
});

const paraChatId = (numero) => (String(numero).includes('@') ? String(numero) : `${numero}@c.us`);

app.post('/enviarMensagem', async (req, res) => {
  const { numero, mensagem } = req.body || {};
  if (!pronto) return res.status(503).json({ erro: 'WhatsApp ainda não conectado' });
  if (!numero || !mensagem) return res.status(400).json({ erro: 'numero e mensagem são obrigatórios' });
  try {
    await client.sendMessage(paraChatId(numero), mensagem);
    res.json({ ok: true });
  } catch (e) {
    console.error('Erro ao enviar:', e.message);
    res.status(500).json({ erro: e.message });
  }
});

// Mostra "digitando..." para o cliente (deixa o atendimento mais natural)
app.post('/digitando', async (req, res) => {
  try {
    const chat = await client.getChatById(paraChatId(req.body.numero));
    await chat.sendSeen();
    await chat.sendStateTyping();
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ erro: e.message });
  }
});

app.get('/status', (_req, res) => res.json({ conectado: pronto, idSessao: ID_SESSAO }));

io.on('connection', () => console.log('🐍 Bot Python conectado'));

server.listen(PORTA, () => console.log(`Servidor do WhatsApp na porta ${PORTA}`));
client.initialize();

// Encerra com calma (salva a sessão do WhatsApp) ao parar o servidor
for (const sinal of ['SIGINT', 'SIGTERM']) {
  process.on(sinal, async () => {
    console.log('Encerrando...');
    try { await client.destroy(); } catch (_) { /* já estava fechado */ }
    process.exit(0);
  });
}
