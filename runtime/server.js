/**
* 🌐 runtime/server.js
* Main backend entry point.
* Serves frontend files, initializes WebSocket server, boots eventBus,
* connects all agents, routes messages to frontend.
* ES Modules. Node 18+.
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

// ── Load env ──
dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = process.env.PORT || 3000;

// ── Express app ──
const app = express();
const server = createServer(app);

// ── Middleware ──
app.use(helmet({
  contentSecurityPolicy: false,
}));
app.use(cors());
app.use(compression());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ── Serve static frontend files ──
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

  if (!eventType || typeof eventType !== 'string') {
    return res.status(400).json({ error: 'eventType required' });
  }

  // Inject into eventBus — StreamManager is already subscribed
  eventBus.publish(eventType, payload);

  // Also log to audit
  auditLogger.logEvent(eventType, payload, 'python-agent');

  res.json({ status: 'published', eventType });
});

// ── API: Get recent agent messages ──
app.get('/api/chat/history', (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  const history = eventBus.getHistory('AGENT_MESSAGE', limit);
  res.json({ history, count: history.length });
});

// ── API: Get market data ──
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

// ── API: Trigger manual investigation ──
app.post('/api/analyze', (req, res) => {
  const { tokenAddress, chain } = req.body;

  if (!tokenAddress) {
    return res.status(400).json({ error: 'tokenAddress required' });
  }

  const validChains = ['bsc', 'ethereum', 'solana', 'base'];
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

// ── API: Get audit stats ──
app.get('/api/audit/stats', (req, res) => {
  res.json(auditLogger.getStats());
});

// ── API: Get recent audit logs ──
app.get('/api/audit/logs', (req, res) => {
  const count = parseInt(req.query.count) || 100;
  res.json(auditLogger.readRecent(count));
});

// ── Catch-all: serve index.html for SPA routes ──
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'index.html'));
});

// ── Initialize subsystems ──
const auditLogger = new AuditLogger();
const eventQueue = new EventQueue(eventBus);
let streamManager = null;

// ── Boot sequence ──
async function boot() {
  console.log('\n🚀 CLAW INTEL — Boot Sequence');
  console.log('═══════════════════════════════════════');

  auditLogger.logInfo('server', 'ClawIntel server starting', {
    port: PORT,
    nodeVersion: process.version,
    env: process.env.NODE_ENV || 'development',
  });

  // Initialize WebSocket stream manager
  streamManager = new StreamManager(server, eventBus);
  auditLogger.logInfo('server', 'Stream manager initialized');

  // Subscribe to key events for audit logging
  eventBus.subscribe('NEW_TOKEN', (payload) => {
    auditLogger.logEvent('NEW_TOKEN', payload, 'Nova');
  });

  eventBus.subscribe('SIMULATION_COMPLETE', (payload) => {
    auditLogger.logEvent('SIMULATION_COMPLETE', payload, 'Atlas');
  });

  eventBus.subscribe('ANALYSIS_COMPLETE', (payload) => {
    auditLogger.logEvent('ANALYSIS_COMPLETE', payload, 'Vega');
  });

  eventBus.subscribe('DECISION_COMPLETE', (payload) => {
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

  // Handle market engine responses
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

  // 🔥 CRITICAL FIX: Bind to 0.0.0.0 for Render/external access
  server.listen(PORT, '0.0.0.0', () => {
    console.log(`✅ Server running on http://0.0.0.0:${PORT}`);
    console.log(`✅ WebSocket ready on ws://0.0.0.0:${PORT}`);
    console.log(`✅ Frontend served from root folder`);
    console.log('═══════════════════════════════════════\n');

    auditLogger.logInfo('server', 'Server listening', { port: PORT, host: '0.0.0.0' });
  });

  // Graceful shutdown
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

function shutdown() {
  console.log('\n🛑 Shutting down ClawIntel...');

  if (streamManager) {
    streamManager.shutdown();
  }

  eventQueue.shutdown();
  auditLogger.shutdown();

  server.close(() => {
    console.log('✅ Server closed');
    process.exit(0);
  });

  setTimeout(() => {
    console.error('❌ Forced shutdown');
    process.exit(1);
  }, 5000);
}

// ── Start ──
boot().catch((err) => {
  console.error('❌ Boot failed:', err);
  process.exit(1);
});