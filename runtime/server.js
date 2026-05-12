import express from 'express';
import { createServer } from 'http';
import { WebSocketServer } from 'ws';
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
  contentSecurityPolicy: false, // Allow inline scripts for frontend
}));
app.use(cors());
app.use(compression());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ── Serve static frontend files ──
// index.html is in ROOT folder (as per spec)
// frontend/ contains CSS, JS, and other HTML pages
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

// ── API: Get recent agent messages (for new clients joining) ──
app.get('/api/chat/history', (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  const history = eventBus.getHistory('AGENT_MESSAGE', limit);
  res.json({ history, count: history.length });
});

// ── API: Get market data ──
app.get('/api/markets/:category', async (req, res) => {
  const { category } = req.params;
  const validCategories = ['trending', 'gainers', 'losers', 'ai-verified'];

  if (!validCategories.includes(category)) {
    return res.status(400).json({ error: 'Invalid category' });
  }

  // Forward to marketEngine via eventBus
  eventBus.publish('REQUEST_MARKET_DATA', { category, response: res });
});

// ── API: Trigger manual investigation ──
app.post('/api/analyze', (req, res) => {
  const { tokenAddress, chain } = req.body;

  if (!tokenAddress || !chain) {
    return res.status(400).json({ error: 'tokenAddress and chain required' });
  }

  // Validate address format
  const validChains = ['bsc', 'ethereum', 'solana', 'base'];
  if (!validChains.includes(chain.toLowerCase())) {
    return res.status(400).json({ error: `Invalid chain. Use: ${validChains.join(', ')}` });
  }

  // Publish to eventBus — agents will pick this up
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

  // 1. Audit logger
  auditLogger.logInfo('server', 'ClawIntel server starting', {
    port: PORT,
    nodeVersion: process.version,
    env: process.env.NODE_ENV || 'development',
  });

  // 2. Initialize WebSocket stream manager
  streamManager = new StreamManager(server, eventBus);
  auditLogger.logInfo('server', 'Stream manager initialized');

  // 3. Subscribe to key events for audit logging
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
    // Don't log every chat message to audit — too noisy
    // Only log if it's a system or error message
    if (payload.type === 'system' || payload.type === 'error') {
      auditLogger.logEvent('AGENT_MESSAGE', payload, payload.agent);
    }
  });

  // 4. Error handling
  eventBus.subscribe('ERROR', (payload) => {
    auditLogger.logError(payload.source, payload.error, payload.context);
  });

  // 5. Start HTTP + WebSocket server
  server.listen(PORT, () => {
    console.log(`✅ Server running on http://localhost:${PORT}`);
    console.log(`✅ WebSocket ready on ws://localhost:${PORT}`);
    console.log(`✅ Frontend served from root folder`);
    console.log('═══════════════════════════════════════\n');

    auditLogger.logInfo('server', 'Server listening', { port: PORT });
  });

  // 6. Graceful shutdown
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

  // Force exit after 5 seconds
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