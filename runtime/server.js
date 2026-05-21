/**
* runtime/server.js
* Main backend entry point — with Database API endpoints.
*/

import express from 'express';
import { createServer } from 'http';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import path from 'path';

import eventBus from './eventBus.js';
import StreamManager from './stream.js';
import EventQueue from './queue.js';
import AuditLogger from './audit.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = process.env.PORT || 3000;

const app = express();
const server = createServer(app);

app.use(helmet({ contentSecurityPolicy: false }));
app.use(cors());
app.use(compression());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use(express.static(path.join(__dirname, '..')));
app.use('/frontend', express.static(path.join(__dirname, '..', 'frontend')));

// ── Health check ──
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: Date.now(),
    uptime: process.uptime(),
    clients: streamManager ? streamManager.getClientCount() : 0,
    events: eventBus.getActiveEventTypes(),
  });
});

// ── API: Publish from Python agents ──
app.post('/api/publish', (req, res) => {
  const { eventType, payload } = req.body;
  console.log(`[publish] ⬅  Received: ${eventType} from Python`);

  if (!eventType || typeof eventType !== 'string') {
    console.log(`[publish]  Rejected: missing eventType`);
    return res.status(400).json({ error: 'eventType required' });
  }

  eventBus.publish(eventType, payload);
  auditLogger.logEvent(eventType, payload, 'python-agent');
  console.log(`[publish]  Published: ${eventType}`);
  res.json({ status: 'published', eventType });
});

// ── API: Chat history ──
app.get('/api/chat/history', (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  const history = eventBus.getHistory('AGENT_MESSAGE', limit);
  res.json({ history, count: history.length });
});

// ═══════════════════════════════════════════════════
// 🗄 DATABASE API ENDPOINTS
// ═══════════════════════════════════════════════════

// ── Stats ──
app.get('/api/stats', async (req, res) => {
  try {
    // Forward to Python via eventBus or return cached
    // For now, return basic stats from eventBus
    res.json({
      status: 'ok',
      tokens_scanned: eventBus.getHistory('NEW_TOKEN', 9999).length,
      investigations: eventBus.getHistory('DECISION_COMPLETE', 9999).length,
      agents_online: ['Nova', 'Atlas', 'Vega', 'Echo', 'Orion'],
      uptime: process.uptime(),
      timestamp: Date.now()
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Recent tokens ──
app.get('/api/tokens', async (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  const chain = req.query.chain;
  const history = eventBus.getHistory('NEW_TOKEN', limit);

  let tokens = history;
  if (chain) {
    tokens = tokens.filter(t => t.chain === chain);
  }

  res.json({ tokens, count: tokens.length });
});

// ── Recent investigations ──
app.get('/api/investigations', async (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  const verdict = req.query.verdict;
  const history = eventBus.getHistory('DECISION_COMPLETE', limit * 2);

  let investigations = history.map(d => ({
    token_address: d.token_address,
    chain: d.chain,
    symbol: d.symbol,
    verdict: d.verdict,
    confidence: d.confidence,
    timestamp: d.timestamp,
    factors: d.factors
  }));

  if (verdict) {
    investigations = investigations.filter(i => i.verdict === verdict);
  }

  investigations = investigations.slice(0, limit);
  res.json({ investigations, count: investigations.length });
});

// ── Investigation detail ──
app.get('/api/investigations/:token', async (req, res) => {
  const token = req.params.token;
  const history = eventBus.getHistory('DECISION_COMPLETE', 9999);
  const investigation = history.find(i => i.token_address === token);

  if (!investigation) {
    return res.status(404).json({ error: 'Investigation not found' });
  }

  res.json(investigation);
});

// ── Market data ──
const pendingMarketRequests = new Map();
let marketRequestId = 0;

app.get('/api/markets/:category', async (req, res) => {
  const { category } = req.params;
  const validCategories = ['trending', 'gainers', 'losers', 'ai-verified'];

  if (!validCategories.includes(category)) {
    return res.status(400).json({ error: 'Invalid category' });
  }

  const reqId = ++marketRequestId;
  pendingMarketRequests.set(reqId, res);
  eventBus.publish('REQUEST_MARKET_DATA', { requestId: reqId, category });

  setTimeout(() => {
    if (pendingMarketRequests.has(reqId)) {
      pendingMarketRequests.delete(reqId);
      res.status(504).json({ error: 'Market engine timeout' });
    }
  }, 5000);
});

// ── Manual investigation ──
app.post('/api/analyze', (req, res) => {
  const { tokenAddress, chain } = req.body;

  if (!tokenAddress) {
    return res.status(400).json({ error: 'tokenAddress required' });
  }

  const validChains = ['bsc', 'ethereum', 'solana', 'base', 'mantle'];
  if (!chain || !validChains.includes(chain.toLowerCase())) {
    return res.status(400).json({ error: `Invalid chain. Use: ${validChains.join(', ')}` });
  }

  eventBus.publish('MANUAL_INVESTIGATE', {
    token_address: tokenAddress,
    chain: chain.toLowerCase(),
    triggered_by: 'user',
    timestamp: Date.now(),
  });

  res.json({
    status: 'investigation_started',
    tokenAddress,
    chain,
    message: 'Agents are investigating. Watch the live feed.',
  });
});

// ── Audit ──
app.get('/api/audit/stats', (req, res) => {
  res.json(auditLogger.getStats());
});

app.get('/api/audit/logs', (req, res) => {
  const count = parseInt(req.query.count) || 100;
  res.json(auditLogger.readRecent(count));
});

// ── SPA catch-all ──
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'index.html'));
});

// ── Initialize ──
const auditLogger = new AuditLogger();
const eventQueue = new EventQueue(eventBus);
let streamManager = null;

async function boot() {
  console.log('\n CLAW INTEL — Boot Sequence');
  console.log('═══════════════════════════════════════');

  auditLogger.logInfo('server', 'ClawIntel server starting', {
    port: PORT,
    nodeVersion: process.version,
    env: process.env.NODE_ENV || 'development',
  });

  streamManager = new StreamManager(server, eventBus);
  auditLogger.logInfo('server', 'Stream manager initialized');

  eventBus.subscribe('NEW_TOKEN', (payload) => {
    console.log(`[eventBus] NEW_TOKEN: ${payload.token_symbol || 'unknown'}`);
    auditLogger.logEvent('NEW_TOKEN', payload, 'Nova');
  });

  eventBus.subscribe('SIMULATION_COMPLETE', (payload) => {
    console.log(`[eventBus] SIMULATION_COMPLETE`);
    auditLogger.logEvent('SIMULATION_COMPLETE', payload, 'Atlas');
  });

  eventBus.subscribe('ANALYSIS_COMPLETE', (payload) => {
    console.log(`[eventBus] ANALYSIS_COMPLETE`);
    auditLogger.logEvent('ANALYSIS_COMPLETE', payload, 'Vega');
  });

  eventBus.subscribe('DECISION_COMPLETE', (payload) => {
    console.log(`[eventBus] DECISION_COMPLETE: ${payload.verdict}`);
    auditLogger.logDecision('Orion', payload.token_address, payload.verdict, payload);
  });

  eventBus.subscribe('AGENT_MESSAGE', (payload) => {
    if (payload.type === 'system' || payload.type === 'error') {
      auditLogger.logEvent('AGENT_MESSAGE', payload, payload.agent);
    }
  });

  eventBus.subscribe('ERROR', (payload) => {
    auditLogger.logError(payload.source, payload.error, payload.context);
  });

  eventBus.subscribe('MARKET_DATA_RESPONSE', (payload) => {
    const { requestId, data, error } = payload;
    const res = pendingMarketRequests.get(requestId);
    if (!res) return;
    pendingMarketRequests.delete(requestId);
    if (error) {
      res.status(500).json({ error });
    } else {
      res.json(data);
    }
  });

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
    console.log(`WebSocket ready on ws://0.0.0.0:${PORT}`);
    console.log('═══════════════════════════════════════\n');
    auditLogger.logInfo('server', 'Server listening', { port: PORT, host: '0.0.0.0' });
  });

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

function shutdown() {
  console.log('\n Shutting down ClawIntel...');
  if (streamManager) streamManager.shutdown();
  eventQueue.shutdown();
  auditLogger.shutdown();
  server.close(() => {
    console.log(' Server closed');
    process.exit(0);
  });
  setTimeout(() => {
    console.error('Forced shutdown');
    process.exit(1);
  }, 5000);
}

boot().catch((err) => {
  console.error('Boot failed:', err);
  process.exit(1);
});