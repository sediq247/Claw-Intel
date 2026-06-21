/**
* 🌐 runtime/server.js
* ClawIntel Production Backend
**/
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

/**
* Crash Protection
*/
process.on('uncaughtException', err => {
  console.error('UNCAUGHT EXCEPTION:', err);
});

process.on('unhandledRejection', err => {
  console.error('UNHANDLED REJECTION:', err);
});

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = process.env.PORT || 3000;
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8081';

const app = express();
const server = createServer(app);

/**
* Core Middleware
*/
app.use(
  helmet({
    contentSecurityPolicy: false,
  })
);

app.use(cors());
app.use(compression());

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

/**
* Static Frontend
*/
app.use(express.static(path.join(__dirname, '..')));

app.use(
  '/frontend',
  express.static(path.join(__dirname, '..', 'frontend'))
);

/**
* Runtime Services
*/
const auditLogger = new AuditLogger();
const eventQueue = new EventQueue(eventBus);

let streamManager = null;

/**
* Market Request State
*/
const pendingMarketRequests = new Map();
let marketRequestId = 0;

/* ════════════════════════════════════════
   HEALTH
════════════════════════════════════════ */

app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'ok',
    uptime: process.uptime(),
    timestamp: Date.now(),
    clients: streamManager
      ? streamManager.getClientCount()
      : 0,
    events: eventBus.getActiveEventTypes(),
    memory: process.memoryUsage(),
  });
});

/* ════════════════════════════════════════
   PYTHON AGENT BRIDGE
════════════════════════════════════════ */

app.post('/api/publish', (req, res) => {
  try {
    const { eventType, payload } = req.body;

    console.log(
      `[publish] ⬅️ ${eventType || 'UNKNOWN'}`
    );

    if (!eventType || typeof eventType !== 'string') {
      return res.status(400).json({
        error: 'eventType required',
      });
    }

    eventBus.publish(eventType, payload);

    auditLogger.logEvent(
      eventType,
      payload,
      'python-agent'
    );

    return res.json({
      status: 'published',
      eventType,
    });
  } catch (err) {
    console.error('❌ Publish error:', err);

    return res.status(500).json({
      error: 'publish_failed',
    });
  }
});

/* ════════════════════════════════════════
   CHAT HISTORY
════════════════════════════════════════ */

app.get('/api/chat/history', (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 50;

    const history = eventBus.getHistory(
      'AGENT_MESSAGE',
      limit
    );

    res.json({
      history,
      count: history.length,
    });
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   SYSTEM STATS
════════════════════════════════════════ */

app.get('/api/stats', async (req, res) => {
  try {
    res.json({
      status: 'ok',
      tokens_scanned:
        eventBus.getHistory('NEW_TOKEN', 9999).length,

      investigations:
        eventBus.getHistory(
          'DECISION_COMPLETE',
          9999
        ).length,

      agents_online: [
        'Nova',
        'Atlas',
        'Vega',
        'Echo',
        'Orion',
      ],

      uptime: process.uptime(),
      timestamp: Date.now(),
    });
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   TOKENS
════════════════════════════════════════ */

app.get('/api/tokens', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 50;

    const chain = req.query.chain;

    let tokens = eventBus.getHistory(
      'NEW_TOKEN',
      limit
    );

    if (chain) {
      tokens = tokens.filter(
        t => t.chain === chain
      );
    }

    res.json({
      tokens,
      count: tokens.length,
    });
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   INVESTIGATIONS
════════════════════════════════════════ */

app.get('/api/investigations', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 50;

    const verdict = req.query.verdict;

    let investigations = eventBus
      .getHistory('DECISION_COMPLETE', limit * 2)
      .map(d => ({
        token_address: d.token_address,
        chain: d.chain,
        symbol: d.symbol,
        verdict: d.verdict,
        confidence: d.confidence,
        timestamp: d.timestamp,
        factors: d.factors,
      }));

    if (verdict) {
      investigations = investigations.filter(
        i => i.verdict === verdict
      );
    }

    investigations = investigations.slice(0, limit);

    res.json({
      investigations,
      count: investigations.length,
    });
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

app.get('/api/investigations/:token', async (req, res) => {
  try {
    const token = req.params.token;

    const history = eventBus.getHistory(
      'DECISION_COMPLETE',
      9999
    );

    const investigation = history.find(
      i => i.token_address === token
    );

    if (!investigation) {
      return res.status(404).json({
        error: 'Investigation not found',
      });
    }

    res.json(investigation);
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   MARKET DATA
════════════════════════════════════════ */

app.get('/api/markets/:category', async (req, res) => {
  try {
    const { category } = req.params;

    const validCategories = [
      'trending',
      'gainers',
      'losers',
      'ai-verified',
    ];

    if (!validCategories.includes(category)) {
      return res.status(400).json({
        error: 'Invalid category',
      });
    }

    const reqId = ++marketRequestId;

    pendingMarketRequests.set(reqId, res);

    eventBus.publish('REQUEST_MARKET_DATA', {
      requestId: reqId,
      category,
    });

    setTimeout(() => {
      if (pendingMarketRequests.has(reqId)) {
        pendingMarketRequests.delete(reqId);

        res.status(504).json({
          error: 'Market engine timeout',
        });
      }
    }, 5000);
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   MANUAL INVESTIGATION — FORENSIC LAB
════════════════════════════════════════ */

app.post('/api/analyze', async (req, res) => {
  try {
    const { tokenAddress, chain } = req.body;

    if (!tokenAddress) {
      return res.status(400).json({
        error: 'tokenAddress required',
      });
    }

    const validChains = [
      'bsc',
      'ethereum',
      'solana',
      'base',
      'mantle',
    ];

    if (
      !chain ||
      !validChains.includes(chain.toLowerCase())
    ) {
      return res.status(400).json({
        error: `Invalid chain. Supported: ${validChains.join(', ')}`,
      });
    }

    const normalizedChain = chain.toLowerCase();

    // Publish to eventBus for WebSocket broadcast
    eventBus.publish('MANUAL_INVESTIGATE', {
      token_address: tokenAddress,
      chain: normalizedChain,
      triggered_by: 'user',
      timestamp: Date.now(),
    });

    // FORWARD to Python orchestrator via HTTP
    // This is the critical fix — previously Python never received this
    try {
      const fetch = (await import('node-fetch')).default;
      const pyResponse = await fetch(`${PYTHON_API_URL}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tokenAddress: tokenAddress,
          chain: normalizedChain,
        }),
        timeout: 5000,
      });

      if (pyResponse.ok) {
        const pyData = await pyResponse.json();
        console.log(`[forensic] Python acknowledged: ${pyData.status}`);
      } else {
        console.warn(`[forensic] Python returned ${pyResponse.status}`);
      }
    } catch (pyErr) {
      console.warn(`[forensic] Could not reach Python API: ${pyErr.message}`);
      // Don't fail the request — the eventBus publish already happened
      // and WebSocket clients will see the investigation start
    }

    res.json({
      status: 'investigation_started',
      tokenAddress,
      chain: normalizedChain,
      message:
        'Agents are investigating. Watch the live feed.',
    });
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   AUDIT
════════════════════════════════════════ */

app.get('/api/audit/stats', (req, res) => {
  try {
    res.json(auditLogger.getStats());
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

app.get('/api/audit/logs', (req, res) => {
  try {
    const count = parseInt(req.query.count) || 100;

    res.json(auditLogger.readRecent(count));
  } catch (err) {
    res.status(500).json({
      error: err.message,
    });
  }
});

/* ════════════════════════════════════════
   SPA FALLBACK
════════════════════════════════════════ */

app.use((req, res) => {
  res.sendFile(
    path.join(__dirname, '..', 'index.html')
  );
});

/* ════════════════════════════════════════
   BOOT SYSTEM
════════════════════════════════════════ */

async function boot() {
  console.log('\n🚀 CLAWINTEL BOOT v2');
  console.log('═══════════════════════════════════════');

  /**
   * START SERVER FIRST
   * CRITICAL FOR RENDER/RAILWAY
   */
  server.listen(PORT, '0.0.0.0', () => {
    console.log(
      `Server running on port ${PORT}`
    );

    console.log(
      `HTTP ready`
    );

    console.log(
      `WebSocket ready`
    );

    console.log(
      '═══════════════════════════════════════\n'
    );

    auditLogger.logInfo(
      'server',
      'Server listening',
      {
        port: PORT,
        host: '0.0.0.0',
      }
    );
  });

  /**
   * INITIALIZE STREAM SYSTEM
   * AFTER SERVER BINDS
   */
  streamManager = new StreamManager(
    server,
    eventBus
  );

  auditLogger.logInfo(
    'server',
    'Stream manager initialized'
  );

  /**
   * EVENT SUBSCRIPTIONS
   */
  eventBus.subscribe('NEW_TOKEN', payload => {
    auditLogger.logEvent(
      'NEW_TOKEN',
      payload,
      'Nova'
    );
  });

  eventBus.subscribe(
    'SIMULATION_COMPLETE',
    payload => {
      auditLogger.logEvent(
        'SIMULATION_COMPLETE',
        payload,
        'Atlas'
      );
    }
  );

  eventBus.subscribe(
    'ANALYSIS_COMPLETE',
    payload => {
      auditLogger.logEvent(
        'ANALYSIS_COMPLETE',
        payload,
        'Vega'
      );
    }
  );

  eventBus.subscribe(
    'DECISION_COMPLETE',
    payload => {
      auditLogger.logDecision(
        'Orion',
        payload.token_address,
        payload.verdict,
        payload
      );
    }
  );

  eventBus.subscribe('ERROR', payload => {
    auditLogger.logError(
      payload.source,
      payload.error,
      payload.context
    );
  });

  eventBus.subscribe(
    'MARKET_DATA_RESPONSE',
    payload => {
      const { requestId, data, error } =
        payload;

      const res =
        pendingMarketRequests.get(requestId);

      if (!res) return;

      pendingMarketRequests.delete(requestId);

      if (error) {
        res.status(500).json({ error });
      } else {
        res.json(data);
      }
    }
  );

  // Subscribe to MANUAL_INVESTIGATE for logging
  eventBus.subscribe('MANUAL_INVESTIGATE', payload => {
    auditLogger.logEvent(
      'MANUAL_INVESTIGATE',
      payload,
      'user'
    );
    console.log(`[forensic] User requested investigation: ${payload.token_address} on ${payload.chain}`);
  });

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

/* ════════════════════════════════════════
   SHUTDOWN
════════════════════════════════════════ */

function shutdown() {
  console.log('\n🛑 Shutting down ClawIntel...');

  if (streamManager) {
    streamManager.shutdown();
  }

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

/**
* START SYSTEM
*/
boot().catch(err => {
  console.error(' Boot failed:', err);
  process.exit(1);
});
