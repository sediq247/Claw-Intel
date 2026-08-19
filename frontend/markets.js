const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
let ws = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;

// DOM element references
const els = {
  trending: document.getElementById('trending-grid'),
  gainers: document.getElementById('gainers-grid'),
  losers: document.getElementById('losers-grid'),
  aiVerified: document.getElementById('ai-verified-grid'),
  lastUpdated: document.getElementById('last-updated'),
  loading: document.getElementById('market-loading'),
};

// In-memory cache of current market data for SIGNAL patch-updates
let currentMarketData = {
  trending: [],
  gainers: [],
  losers: [],
  ai_verified: [],
  timestamp: 0,
};

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function getChangeClass(changeStr) {
  if (!changeStr) return 'neutral';
  const val = parseFloat(String(changeStr).replace(/[+,%]/g, ''));
  if (isNaN(val)) return 'neutral';
  return val >= 0 ? 'positive' : 'negative';
}

function getChangeSign(changeStr) {
  const val = parseFloat(String(changeStr).replace(/[+,%]/g, ''));
  if (isNaN(val) || val >= 0) return '+';
  return '';
}

function createTokenCard(token) {
  const changeClass = getChangeClass(token.price_change_24h);
  const changeSign = getChangeSign(token.price_change_24h);
  const aiBadge = token.ai_verified
    ? `<span class="ai-badge">✓ ${escapeHtml(token.ai_verdict || 'AI Verified')}</span>`
    : '';
  const image = token.image
    ? escapeHtml(token.image)
    : `https://api.dicebear.com/7.x/identicon/svg?seed=${escapeHtml(token.symbol || '???')}`;
  const chainDisplay = token.chain ? escapeHtml(token.chain.toUpperCase()) : '?';

  return `
    <div class="token-card">
      <div class="token-header">
        <img src="${image}" alt="${escapeHtml(token.symbol || 'token')}" class="token-icon"
             onerror="this.src='https://api.dicebear.com/7.x/identicon/svg?seed=fallback'">
        <div class="token-meta">
          <div class="token-symbol">
            ${escapeHtml(token.symbol || '???')}
            <span class="chain-tag">${chainDisplay}</span>
          </div>
          <div class="token-name">${escapeHtml(token.name || 'Unknown Token')}</div>
        </div>
        ${aiBadge}
      </div>
      <div class="token-price">${escapeHtml(token.price || '$0.00')}</div>
      <div class="token-change ${changeClass}">${changeSign}${escapeHtml(token.price_change_24h || '0.00%')}</div>
      <div class="token-stats">
        <div><span>MCap</span>${escapeHtml(token.market_cap || '$0')}</div>
        <div><span>Vol</span>${escapeHtml(token.volume_24h || '$0')}</div>
        <div><span>Liq</span>${escapeHtml(token.liquidity || '$0')}</div>
      </div>
    </div>
  `;
}

function renderSection(container, tokens, emptyMessage = 'No data available') {
  if (!container) return;
  if (!tokens || tokens.length === 0) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    return;
  }
  container.innerHTML = tokens.map(createTokenCard).join('');
}

function renderAll(data) {
  // Cache current data for SIGNAL patch-updates
  currentMarketData = {
    trending: data.trending || [],
    gainers: data.gainers || [],
    losers: data.losers || [],
    ai_verified: data.ai_verified || [],
    timestamp: data.timestamp || Date.now() / 1000,
  };

  renderSection(els.trending, currentMarketData.trending, 'No trending tokens found');
  renderSection(els.gainers, currentMarketData.gainers, 'No gainers found');
  renderSection(els.losers, currentMarketData.losers, 'No losers found');
  renderSection(els.aiVerified, currentMarketData.ai_verified, 'No AI-verified tokens yet');

  const ts = currentMarketData.timestamp
    ? new Date(currentMarketData.timestamp * 1000).toLocaleTimeString()
    : 'Just now';
  if (els.lastUpdated) els.lastUpdated.textContent = `Last updated: ${ts}`;
  if (els.loading) els.loading.style.display = 'none';
}

// ─────────────────────────────────────────────────────────────
// REST API
// ─────────────────────────────────────────────────────────────

async function fetchMarkets() {
  try {
    const res = await fetch('/api/markets');
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();

    if (data.error) {
      console.error('[Markets] API error:', data.error);
      if (els.loading) els.loading.innerHTML = `Error: ${escapeHtml(data.error)}`;
      return;
    }

    renderAll(data);
  } catch (e) {
    console.error('[Markets] REST fetch failed:', e);
    if (els.loading) {
      els.loading.innerHTML = 'Failed to load markets. Retrying...';
    }
  }
}

// ─────────────────────────────────────────────────────────────
// WebSocket
// ─────────────────────────────────────────────────────────────

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[Markets] WS connected');
      reconnectDelay = 1000;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'MARKET_UPDATE') {
          console.log('[Markets] Live MARKET_UPDATE received');
          renderAll(data.payload);
        }
        else if (data.type === 'SIGNAL') {
          // Live SIGNAL: Orion rendered a verdict. If SAFE, inject into
          // AI-verified section immediately without waiting for next MARKET_UPDATE.
          console.log('[Markets] Live SIGNAL received:', data.payload.verdict);
          handleLiveSignal(data.payload);
        }
        else if (data.type === 'SYSTEM') {
          console.log('[Markets] System:', data.payload?.message);
        }
      } catch (e) {
        console.error('[Markets] WS parse error:', e);
      }
    };

    ws.onclose = (event) => {
      console.log(`[Markets] WS disconnected (code: ${event.code}), reconnecting in ${reconnectDelay}ms...`);
      reconnectTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
        connectWebSocket();
      }, reconnectDelay);
    };

    ws.onerror = (err) => {
      console.error('[Markets] WS error:', err);
    };
  } catch (e) {
    console.error('[Markets] WS connection failed:', e);
    reconnectTimer = setTimeout(connectWebSocket, reconnectDelay);
  }
}
e
function handleLiveSignal(payload) {
  if (payload.verdict !== 'SAFE') return;

  const tokenId = `${payload.chain}:${payload.token}`;

  // Check if already in ai_verified
  const exists = currentMarketData.ai_verified.some(t => t.id === tokenId);
  if (exists) return;

  // Build a minimal token card for the AI-verified section
  const newToken = {
    id: tokenId,
    symbol: payload.symbol || '???',
    name: 'AI Verified Token',
    chain: payload.chain || 'unknown',
    price: '$0.00',
    price_change_24h: '0.00%',
    price_change_7d: '0.00%',
    market_cap: '$0',
    volume_24h: '$0',
    liquidity: '$0',
    image: null,
    rank: 0,
    ai_verified: true,
    ai_verdict: 'SAFE',
    ai_confidence: payload.confidence ? `${(payload.confidence * 100).toFixed(0)}%` : 'N/A',
    last_updated: 'Just now',
    source: 'ai_verified:live_signal',
    timestamp: payload.timestamp || Date.now() / 1000,
  };

  // Prepend to ai_verified and re-render
  currentMarketData.ai_verified.unshift(newToken);
  if (currentMarketData.ai_verified.length > 20) {
    currentMarketData.ai_verified.pop();
  }

  renderSection(els.aiVerified, currentMarketData.ai_verified, 'No AI-verified tokens yet');
  console.log('[Markets] Injected live AI-verified token:', payload.symbol);
}

// ─────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────

function init() {
  console.log('[Markets] Initializing market dashboard...');

  if (els.loading) els.loading.style.display = 'block';

  // Fetch initial data immediately
  fetchMarkets();

  // Connect WebSocket for live updates
  connectWebSocket();

  setInterval(fetchMarkets, 30000);
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
