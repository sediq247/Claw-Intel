/**
 * 📡 runtime/stream.js
 * WebSocket Stream Manager.
 * Bridges eventBus ↔ frontend. Controls message timing for natural conversation flow.
 * 
 * FIX: Removed internal pipeline events (NEW_TOKEN, SIMULATION_COMPLETE, etc.) from broadcast.
 * Only AGENT_MESSAGE, DECISION_COMPLETE, SYSTEM, SIGNAL, TOKEN_VERIFIED, MARKET_UPDATE reach frontend.
 */

import { WebSocketServer } from 'ws';

class StreamManager {
  constructor(server, eventBus) {
    this.wss = new WebSocketServer({ server });
    this.eventBus = eventBus;
    this.clients = new Set();
    this.backendClients = new Set();
    this.messageQueue = [];
    this.isProcessing = false;
    this.minDelayMs = 800;
    this.maxDelayMs = 2500;

    this.pendingMarketRequests = new Map();
    this.marketRequestId = 0;

    this._init();
  }

  _init() {
    // ONLY these events go to frontend chat/UI
    const frontendEventTypes = [
      'AGENT_MESSAGE',
      'DECISION_COMPLETE',
      'SIGNAL',
      'TOKEN_VERIFIED',
      'MARKET_UPDATE',
      'MANUAL_INVESTIGATE',
      'SYSTEM',
    ];

    frontendEventTypes.forEach((type) => {
      this.eventBus.subscribe(type, (payload) => {
        this._queueMessage(type, payload);
      });
    });

    // Also forward to backend clients (Python bridge) if they subscribed
    this.eventBus.subscribe('MANUAL_INVESTIGATE', (payload) => {
      this._broadcastToBackends('MANUAL_INVESTIGATE', payload);
    });
    this.eventBus.subscribe('REQUEST_MARKET_DATA', (payload) => {
      this._broadcastToBackends('REQUEST_MARKET_DATA', payload);
    });

    this.wss.on('connection', (ws, req) => {
      console.log(`[stream] Client connected from ${req.socket.remoteAddress}`);
      this.clients.add(ws);

      ws.send(JSON.stringify({
        type: 'SYSTEM',
        payload: {
          message: 'Connected to the agents.',
          timestamp: Date.now(),
        },
      }));

      const recentChat = this.eventBus.getHistory('AGENT_MESSAGE', 20);
      if (recentChat.length > 0) {
        ws.send(JSON.stringify({
          type: 'CHAT_HISTORY',
          payload: recentChat,
        }));
      }

      ws.on('message', (raw) => {
        try {
          const msg = JSON.parse(raw.toString());
          this._handleClientMessage(ws, msg);
        } catch (err) {
          console.error('[stream] Invalid client message:', err.message);
        }
      });

      ws.on('close', () => {
        this.clients.delete(ws);
        this.backendClients.delete(ws);
        console.log('[stream] Client disconnected');
      });

      ws.on('error', (err) => {
        console.error('[stream] WebSocket error:', err.message);
        this.clients.delete(ws);
        this.backendClients.delete(ws);
      });
    });

    this._processQueue();
  }

  _queueMessage(eventType, payload) {
    this.messageQueue.push({ eventType, payload, queuedAt: Date.now() });
  }

  async _processQueue() {
    this.isProcessing = true;
    while (this.isProcessing) {
      if (this.messageQueue.length === 0) {
        await this._sleep(100);
        continue;
      }
      const item = this.messageQueue.shift();
      const delay = this._calculateDelay(item);
      if (delay > 0) {
        await this._sleep(delay);
      }
      this._broadcast(item.eventType, item.payload);
    }
  }

  _calculateDelay(item) {
    const { eventType, payload } = item;
    if (eventType === 'AGENT_MESSAGE') {
      const msgLength = payload.message?.length || 0;
      const baseDelay = Math.min(this.maxDelayMs, this.minDelayMs + msgLength * 15);
      return baseDelay + Math.random() * 500;
    }
    if (eventType === 'SYSTEM' || eventType === 'SIGNAL') {
      return 200;
    }
    return this.minDelayMs + Math.random() * 800;
  }

  _broadcast(eventType, payload) {
    const message = JSON.stringify({ type: eventType, payload });
    const deadClients = [];
    this.clients.forEach((ws) => {
      if (ws.readyState === 1) {
        try {
          ws.send(message);
        } catch (err) {
          deadClients.push(ws);
        }
      } else {
        deadClients.push(ws);
      }
    });
    deadClients.forEach((ws) => this.clients.delete(ws));
  }

  _broadcastToBackends(eventType, payload) {
    const message = JSON.stringify({ type: eventType, payload });
    const deadClients = [];
    this.backendClients.forEach((ws) => {
      if (ws.readyState === 1) {
        try {
          ws.send(message);
        } catch (err) {
          deadClients.push(ws);
        }
      } else {
        deadClients.push(ws);
      }
    });
    deadClients.forEach((ws) => this.backendClients.delete(ws));
  }

  _handleClientMessage(ws, msg) {
    const { type, payload } = msg;

    switch (type) {
      case 'REGISTER_BACKEND': {
        ws.isBackend = true;
        ws.backendEvents = new Set(payload.events || []);
        this.backendClients.add(ws);
        console.log('[stream] Backend client registered');
        ws.send(JSON.stringify({ type: 'SYSTEM', payload: { message: 'Backend registered', timestamp: Date.now() } }));
        break;
      }

      case 'MANUAL_INVESTIGATE': {
        this.eventBus.publish('MANUAL_INVESTIGATE', payload);
        break;
      }

      case 'PING': {
        ws.send(JSON.stringify({ type: 'PONG', payload: { timestamp: Date.now() } }));
        break;
      }

      case 'GET_MARKETS': {
        const reqId = ++this.marketRequestId;
        this.pendingMarketRequests.set(reqId, ws);
        this.eventBus.publish('REQUEST_MARKET_DATA', { requestId: reqId, ...payload });
        setTimeout(() => {
          if (this.pendingMarketRequests.has(reqId)) {
            this.pendingMarketRequests.delete(reqId);
          }
        }, 5000);
        break;
      }

      default: {
        console.log(`[stream] Unknown client message type: ${type}`);
      }
    }
  }

  _sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  getClientCount() {
    return this.clients.size;
  }

  shutdown() {
    this.isProcessing = false;
    this.clients.forEach((ws) => {
      try {
        ws.close(1000, 'Server shutting down');
      } catch (e) {}
    });
    this.backendClients.forEach((ws) => {
      try {
        ws.close(1000, 'Server shutting down');
      } catch (e) {}
    });
    this.wss.close();
    console.log('[stream] Stream manager shut down');
  }
}

export default StreamManager;
export { StreamManager };
