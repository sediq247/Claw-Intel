const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
let ws = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;

let currentView = 'card';
let currentTab = 'trending';

let currentMarketData = {
  trending: [],
  gainers: [],
  losers: [],
  ai_verified: [],
  timestamp: 0,
};


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

function formatNumber(num) {
  if (!num) return '$0';
  const n = parseFloat(String(num).replace(/[$,]/g, ''));
  if (isNaN(n)) return num;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return `$${n.toFixed(2)}`;
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

// ─────────────────────────────────────────────────────────────
// Table View
// ─────────────────────────────────────────────────────────────

function createTableRow(token, index) {
  const changeClass = getChangeClass(token.price_change_24h);
  const changeSign = getChangeSign(token.price_change_24h);
  const aiBadge = token.ai_verified
    ? `<span class="ai-badge-sm">✓ AI</span>`
    : '';
  const image = token.image
    ? escapeHtml(token.image)
    : `https://api.dicebear.com/7.x/identicon/svg?seed=${escapeHtml(token.symbol || '???')}`;
  const chainDisplay = token.chain ? escapeHtml(token.chain.toUpperCase()) : '?';
  const statusClass = token.ai_verified ? 'status-safe' : 'status-unknown';
  const statusText = token.ai_verified ? 'AI Verified' : 'Unverified';

  return `
    <tr>
      <td class="col-rank">${index + 1}</td>
      <td>
        <div class="token-cell">
          <img src="${image}" alt="${escapeHtml(token.symbol || '')}" class="token-icon-sm"
               onerror="this.src='https://api.dicebear.com/7.x/identicon/svg?seed=fallback'">
          <div>
            <div class="token-symbol-td">${escapeHtml(token.symbol || '???')} <span class="chain-tag-sm">${chainDisplay}</span> ${aiBadge}</div>
            <div class="token-name-td">${escapeHtml(token.name || 'Unknown')}</div>
          </div>
        </div>
      </td>
      <td>${escapeHtml(token.price || '$0.00')}</td>
      <td class="${changeClass}">${changeSign}${escapeHtml(token.price_change_24h || '0.00%')}</td>
      <td>${escapeHtml(token.market_cap || '$0')}</td>
      <td class="col-volume">${escapeHtml(token.volume_24h || '$0')}</td>
      <td class="col-liquidity">${escapeHtml(token.liquidity || '$0')}</td>
      <td><span class="status-badge ${statusClass}">${statusText}</span></td>
    </tr>
  `;
}

// ─────────────────────────────────────────────────────────────
// Rendering
// ─────────────────────────────────────────────────────────────

function renderCards(container, tokens, emptyMessage) {
  if (!container) return;
  if (!tokens || tokens.length === 0) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    return;
  }
  container.innerHTML = tokens.map(createTokenCard).join('');
}

function renderTable(tbody, tokens, emptyMessage) {
  if (!tbody) return;
  if (!tokens || tokens.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state-td">${escapeHtml(emptyMessage)}</td></tr>`;
    return;
  }
  tbody.innerHTML = tokens.map((t, i) => createTableRow(t, i)).join('');
}

function updateBadges() {
  const badgeTrending = document.getElementById('badge-trending');
  const badgeGainers = document.getElementById('badge-gainers');
  const badgeLosers = document.getElementById('badge-losers');
  const badgeAi = document.getElementById('badge-ai');

  if (badgeTrending) badgeTrending.textContent = currentMarketData.trending.length || '—';
  if (badgeGainers) badgeGainers.textContent = currentMarketData.gainers.length || '—';
  if (badgeLosers) badgeLosers.textContent = currentMarketData.losers.length || '—';
  if (badgeAi) badgeAi.textContent = currentMarketData.ai_verified.length || '—';
}

function renderCurrentTab() {
  const loadingState = document.getElementById('loading-state');
  const emptyState = document.getElementById('empty-state');
  const tableView = document.getElementById('table-view');
  const cardView = document.getElementById('card-view');
  const marketTableBody = document.getElementById('market-table-body');
  const lastUpdated = document.getElementById('last-updated');

  if (loadingState) loadingState.style.display = 'none';

  let tokens = [];
  let emptyMsg = 'No data available';

  switch (currentTab) {
    case 'trending':
      tokens = currentMarketData.trending || [];
      emptyMsg = 'No trending tokens found';
      break;
    case 'gainers':
      tokens = currentMarketData.gainers || [];
      emptyMsg = 'No gainers found';
      break;
    case 'losers':
      tokens = currentMarketData.losers || [];
      emptyMsg = 'No losers found';
      break;
    case 'ai-verified':
      tokens = currentMarketData.ai_verified || [];
      emptyMsg = 'No AI-verified tokens yet';
      break;
    default:
      tokens = currentMarketData.trending || [];
  }

  if (!tokens || tokens.length === 0) {
    if (emptyState) emptyState.style.display = 'block';
    if (tableView) tableView.style.display = 'none';
    if (cardView) cardView.style.display = 'none';
    return;
  }

  if (emptyState) emptyState.style.display = 'none';

  if (currentView === 'table') {
    if (tableView) tableView.style.display = 'block';
    if (cardView) cardView.style.display = 'none';
    renderTable(marketTableBody, tokens, emptyMsg);
  } else {
    if (tableView) tableView.style.display = 'none';
    if (cardView) cardView.style.display = 'grid';
    renderCards(cardView, tokens, emptyMsg);
  }

  updateBadges();

  const ts = currentMarketData.timestamp
    ? new Date(currentMarketData.timestamp * 1000).toLocaleTimeString()
    : 'Just now';
  if (lastUpdated) lastUpdated.textContent = `Last updated: ${ts}`;
}

function renderAll(data) {
  currentMarketData = {
    trending: data.trending || [],
    gainers: data.gainers || [],
    losers: data.losers || [],
    ai_verified: data.ai_verified || [],
    timestamp: data.timestamp || Date.now() / 1000,
  };
  renderCurrentTab();
}

function initTabs() {
  const tabContainer = document.getElementById('market-tabs');
  if (!tabContainer) return;

  tabContainer.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab-btn');
    if (!btn) return;

    // Update active state
    tabContainer.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    // Update current tab
    currentTab = btn.dataset.tab;
    renderCurrentTab();
  });
}


async function fetchMarkets() {
  try {
    const res = await fetch('/api/markets');
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();

    if (data.error) {
      console.error('[Markets] API error:', data.error);
      const loadingState = document.getElementById('loading-state');
      if (loadingState) loadingState.innerHTML = `<div class="empty-state">Error: ${escapeHtml(data.error)}</div>`;
      return;
    }

    renderAll(data);
  } catch (e) {
    console.error('[Markets] REST fetch failed:', e);
    const loadingState = document.getElementById('loading-state');
    if (loadingState) {
      loadingState.innerHTML = '<div class="empty-state">Failed to load markets. Retrying...</div>';
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

function handleLiveSignal(payload) {
  if (payload.verdict !== 'SAFE') return;

  const tokenId = `${payload.chain}:${payload.token}`;

  const exists = currentMarketData.ai_verified.some(t => t.id === tokenId);
  if (exists) return;


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

  currentMarketData.ai_verified.unshift(newToken);
  if (currentMarketData.ai_verified.length > 20) {
    currentMarketData.ai_verified.pop();
  }

  if (currentTab === 'ai-verified') {
    renderCurrentTab();
  }
  updateBadges();
  console.log('[Markets] Injected live AI-verified token:', payload.symbol);
}

// ─────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────

function init() {
  console.log('[Markets] Initializing market dashboard...');

  initTabs();

  fetchMarkets();

  
  connectWebSocket();

  setInterval(fetchMarkets, 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
