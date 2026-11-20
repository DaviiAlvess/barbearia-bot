// Servidor que conecta o WhatsApp (pelo QR code) ao bot em Python.
// Serve o QR em /qr.png para o painel Agendbarber.
const express = require('express');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { Server } = require('socket.io');
const QRCode = require('qrcode');
const qrcode = require('qrcode-terminal');
const { Client, LocalAuth } = require('whatsapp-web.js');

const PORTA = process.env.PORTA || 3000;
const ID_SESSAO = process.env.ID_SESSAO || '8113';
const AUTH_DIR = path.join(process.cwd(), '.wwebjs_auth');

const app = express();
app.use(express.json());
const server = http.createServer(app);
const io = new Server(server);

let pronto = false;
let ultimoQr = null;
let qrEm = 0; // epoch ms do último QR
let cliente = null;
let iniciando = false;

function criarCliente() {
  return new Client({
    authStrategy: new LocalAuth({ clientId: `sessao-${ID_SESSAO}`, dataPath: AUTH_DIR }),
    puppeteer: {
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-extensions',
        '--no-first-run',
        '--disable-software-rasterizer',
        '--mute-audio',
      ],
    },
  });
}

function ligarEventos(client) {
  client.on('qr', (qr) => {
    pronto = false;
    ultimoQr = qr;
    qrEm = Date.now();
    console.log('📱 Novo QR gerado. Escaneie em Aparelhos conectados (ou no painel /whatsapp).');
    console.log(`   (qr id ${qrEm})`);
    qrcode.generate(qr, { small: true });
  });

  client.on('loading_screen', (pct, msg) => {
    console.log(`⏳ Carregando WhatsApp Web: ${pct}% ${msg || ''}`);
  });

  client.on('authenticated', () => {
    console.log('🔐 WhatsApp autenticado (sessão salva).');
  });

  client.on('ready', () => {
    pronto = true;
    ultimoQr = null;
    qrEm = 0;
    console.log('✅ WhatsApp conectado!');
  });

  client.on('auth_failure', (msg) => {
    pronto = false;
    ultimoQr = null;
    console.error('❌ Falha na autenticação:', msg);
  });

  client.on('disconnected', async (motivo) => {
    pronto = false;
    ultimoQr = null;
    console.log('⚠️ WhatsApp desconectado:', motivo, '- reiniciando...');
    try { await client.destroy(); } catch (_) { /* ignore */ }
    setTimeout(() => iniciarCliente(), 3000);
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
}

async function iniciarCliente() {
  if (iniciando) return;
  iniciando = true;
  try {
    if (cliente) {
      try { await cliente.destroy(); } catch (_) { /* ignore */ }
      cliente = null;
    }
    cliente = criarCliente();
    ligarEventos(cliente);
    await cliente.initialize();
  } catch (e) {
    console.error('❌ Erro ao iniciar cliente:', e.message);
    setTimeout(() => { iniciando = false; iniciarCliente(); }, 5000);
    return;
  }
  iniciando = false;
}

function limparSessaoDisco() {
  const alvo = path.join(AUTH_DIR, `session-sessao-${ID_SESSAO}`);
  try {
    fs.rmSync(alvo, { recursive: true, force: true });
    console.log('🧹 Sessão local apagada:', alvo);
  } catch (e) {
    console.error('Não deu para apagar sessão:', e.message);
  }
}

const paraChatId = (numero) => (String(numero).includes('@') ? String(numero) : `${numero}@c.us`);

app.post('/enviarMensagem', async (req, res) => {
  const { numero, mensagem } = req.body || {};
  if (!pronto) return res.status(503).json({ erro: 'WhatsApp ainda não conectado' });
  if (!numero || !mensagem) return res.status(400).json({ erro: 'numero e mensagem são obrigatórios' });
  try {
    await cliente.sendMessage(paraChatId(numero), mensagem);
    res.json({ ok: true });
  } catch (e) {
    console.error('Erro ao enviar:', e.message);
    res.status(500).json({ erro: e.message });
  }
});

app.post('/digitando', async (req, res) => {
  try {
    const chat = await cliente.getChatById(paraChatId(req.body.numero));
    await chat.sendSeen();
    await chat.sendStateTyping();
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ erro: e.message });
  }
});

app.get('/status', (_req, res) => res.json({
  conectado: pronto,
  temQr: Boolean(ultimoQr),
  qrEm,
  idadeQrSegundos: ultimoQr ? Math.floor((Date.now() - qrEm) / 1000) : null,
  idSessao: ID_SESSAO,
}));

app.get('/qr.png', async (_req, res) => {
  if (!ultimoQr) {
    return res.status(404).json({ erro: 'Sem QR no momento (já conectado ou ainda iniciando)' });
  }
  try {
    const png = await QRCode.toBuffer(ultimoQr, { type: 'png', width: 360, margin: 2 });
    res.set({
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      Pragma: 'no-cache',
      Expires: '0',
    });
    res.type('png').send(png);
  } catch (e) {
    res.status(500).json({ erro: e.message });
  }
});

// Apaga sessão e gera QR novo (painel pode chamar)
app.post('/reiniciar-qr', async (_req, res) => {
  console.log('🔄 Reinício de sessão pedido pelo painel');
  pronto = false;
  ultimoQr = null;
  try {
    if (cliente) {
      try { await cliente.destroy(); } catch (_) { /* ignore */ }
      cliente = null;
    }
    limparSessaoDisco();
    iniciando = false;
    await iniciarCliente();
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ erro: e.message });
  }
});

io.on('connection', () => console.log('🐍 Bot Python conectado'));

server.listen(PORTA, () => console.log(`Servidor do WhatsApp na porta ${PORTA}`));
iniciarCliente();

for (const sinal of ['SIGINT', 'SIGTERM']) {
  process.on(sinal, async () => {
    console.log('Encerrando...');
    try { if (cliente) await cliente.destroy(); } catch (_) { /* ignore */ }
    process.exit(0);
  });
}
