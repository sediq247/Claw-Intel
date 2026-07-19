/**
 * 📊 frontend/markets.js
 * ClawIntel — Market Data Wall
 * Live tabs: Trending, Top Gainers, Top Losers, AI Verified
 */

const CONFIG = {
  WS_URL: `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`,
  API_BASE: '',
  REFRESH_INTERVAL: 30000,
  RECONNECT_INTERVAL: 3000,
};

class MarketsApp {
  constructor() {
    this.ws = null;
    this.currentTab = 'trending';
    this.data = {
      trending: [],
      gainers: [],
      losers: [],
      'ai-verified': [],
    };
    this.loading = true;
    this.lastUpdated = null;

    this.init();
  }

  init() {
    this.connectWebSocket();
    this.fetchInitialData();
    this.setupTabListeners();

    // Auto-refresh every 30s
    setInterval(() => this.fetchInitialData(), CONFIG.REFRESH_INTERVAL);
  }

  // ── Tab Listeners ──
  setupTabListeners() {
    document.querySelectorAll('.tab-bton').forEach(bton => {
      bton.addEventListener('click', () => {
        const tab = bton.dataset.tab;
        if (tab) this.switchTab(tab);
      });
    });
  }

  // ── WebSocket ──
  connectWebSocket() {
    try {
      this.ws = new WebSocket(CONFIG.WS_URL);

      this.ws.onopen = () => {
        console.log('[Markets] WS connected');
        this.setConnectionStatus(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const { type, payload } = JSON.parse(event.data);
          if (type === 'MARKET_UPDATE') {
            this.handleMarketUpdate(payload);
          }
          if (type === 'AI_VERDICT') {
            this.addAiVerifiedToken(payload);
          }
        } catch (e) {
          console.error('[Markets] Parse error:', e);
        }
      };

      this.ws.onclose = () => {
        this.setConnectionStatus(false);
        setTimeout(() => this.connectWebSocket(), CONFIG.RECONNECT_INTERVAL);
      };

      this.ws.onerror = () => {
        this.setConnectionStatus(false);
      };
    } catch (e) {
      console.error('[Markets] WS error:', e);
    }
  }

  setConnectionStatus(online) {
    const indicator = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');
    if (indicator && text) {
      indicator.className = 'live-indicator ' + (online ? '' : 'offline');
      text.textContent = online ? 'Live' : 'Offline';
    }
  }

  // ── Data Fetching ──
  async fetchInitialData() {
    const tabs = ['trending', 'gainers', 'losers'];

    for (const tab of tabs) {
      try {
        const res = await fetch(`/api/markets/${tab}`);
        if (res.ok) {
          const data = await res.json();
          // Store the fetched data
          if (Array.isArray(data)) {
            this.data[tab] = data;
          } else if (data && typeof data === 'object') {
            // Handle nested response structures
            this.data[tab] = data.trending || data.gainers || data.losers || data['ai-verified'] || [];
          }
          this.loading = false;
        }
      } catch (e) {
        console.error(`[Markets] Failed to fetch ${tab}:`, e);
      }
    }

    this.updateBadgeCounts();
    this.render();
  }

  handleMarketUpdate(payload) {
    this.loading = false;
    this.lastUpdated = new Date();

    if (payload.trending) this.data.trending = payload.trending;
    if (payload.gainers) this.data.gainers = payload.gainers;
    if (payload.losers) this.data.losers = payload.losers;
    if (payload.ai_verified) this.data['ai-verified'] = payload.ai_verified;

    this.updateBadgeCounts();
    this.render();
    this.updateLastUpdated();
  }

  addAiVerifiedToken(payload) {
    const token = {
      id: payload.token,
      symbol: payload.symbol || '???',
      name: 'AI Verified Token',
      chain: payload.chain,
      price: 0,
      price_change_24h: 0,
      market_cap: 0,
      volume_24h: 0,
      liquidity: 0,
      ai_verified: true,
      ai_verdict: payload.verdict,
      ai_confidence: payload.confidence,
      last_updated: payload.timestamp,
    };

    // Add to beginning, avoid duplicates
    this.data['ai-verified'] = this.data['ai-verified'].filter(t => t.id !== token.id);
    this.data['ai-verified'].unshift(token);

    this.updateBadgeCounts();
    if (this.currentTab === 'ai-verified') {
      this.render();
    }
  }

  // ── Tab Switching ──
  switchTab(tab) {
    this.currentTab = tab;

    // Update tab buttons
    document.querySelectorAll('.tab-bton').forEach(bton => {
      bton.classList.toggle('active', bton.dataset.tab === tab);
    });

    this.render();
  }

  // ── Rendering ──
  render() {
    const data = this.data[this.currentTab] || [];
    const loadingEl = document.getElementById('loading-state');
    const emptyEl = document.getElementById('empty-state');
    const tableView = document.getElementById('table-view');
    const cardView = document.getElementById('card-view');

    if (!loadingEl || !emptyEl || !tableView || !cardView) return;

    if (this.loading) {
      loadingEl.style.display = 'flex';
      emptyEl.style.display = 'none';
      tableView.style.display = 'none';
      cardView.style.display = 'none';
      return;
    }

    loadingEl.style.display = 'none';

    if (data.length === 0) {
      emptyEl.style.display = 'flex';
      tableView.style.display = 'none';
      cardView.style.display = 'none';
      return;
    }

    emptyEl.style.display = 'none';

    if (this.currentTab === 'ai-verified') {
      tableView.style.display = 'none';
      cardView.style.display = 'grid';
      this.renderCards(data);
    } else {
      tableView.style.display = 'block';
      cardView.style.display = 'none';
      this.renderTable(data);
    }
  }

  renderTable(data) {
    const tbody = document.getElementById('market-table-body');
    if (!tbody) return;

    tbody.innerHTML = data.map((token, i) => {
      const changeClass = this.getChangeClass(token.price_change_24h);
      const changeSign = (typeof token.price_change_24h === 'number' && token.price_change_24h > 0) ? '+' : '';
      const changeVal = token.price_change_24h || '0.00';
      const aiBadge = token.ai_verified
        ? `<span class="badge badge-ai">🤖 ${token.ai_verdict}</span>`
        : '';

      return `
        <tr style="animation-delay:${i * 0.03}s">
          <td class="col-rank">${token.rank || i + 1}</td>
          <td>
            <div class="col-token">
              <div class="col-token-img">
                ${token.image ? `<img src="${token.image}" alt="" onerror="this.style.display='none';this.parentElement.textContent='💎'">` : '💎'}
              </div>
              <div>
                <div class="col-token-name">${token.name || 'Unknown'}</div>
                <div class="col-token-symbol">${token.symbol || '???'} · ${token.chain || 'Multi'}</div>
              </div>
            </div>
          </td>
          <td class="col-price">${token.price || '$0.00'}</td>
          <td class="col-change ${changeClass}">${changeSign}${changeVal}%</td>
          <td class="col-mcap">${token.market_cap || '$0'}</td>
          <td class="col-volume">${token.volume_24h || '$0'}</td>
          <td class="col-liquidity">${token.liquidity || '$0'}</td>
          <td>${aiBadge}</td>
        </tr>
      `;
    }).join('');
  }

  renderCards(data) {
    const container = document.getElementById('card-view');
    if (!container) return;

    container.innerHTML = data.map((token, i) => {
      const verdictClass = token.ai_verdict?.toLowerCase() || 'neutral';
      const confidence = token.ai_confidence
        ? (typeof token.ai_confidence === 'string' ? token.ai_confidence : `${(token.ai_confidence * 100).toFixed(0)}%`)
        : 'N/A';

      return `
        <div class="token-card" style="animation-delay:${i * 0.05}s">
          <div class="token-card-ai ${verdictClass}">
             ${token.ai_verdict || 'SAFE'}
          </div>
          <div class="token-card-header">
            <div class="token-card-img">
              ${token.image ? `<img src="${token.image}" alt="" onerror="this.style.display='none';this.parentElement.textContent='💎'">` : '💎'}
            </div>
            <div class="token-card-info">
              <div class="token-card-symbol">
                ${token.symbol || '???'}
                <span class="token-card-chain">${token.chain || 'Multi'}</span>
              </div>
              <div class="token-card-name">${token.name || 'Unknown'}</div>
            </div>
          </div>
          <div class="token-card-price">${token.price || '$0.00'}</div>
          <div class="token-card-stats">
            <div class="token-card-stat">
              <span class="token-card-stat-label">24h Change</span>
              <span class="token-card-stat-value ${this.getChangeClass(token.price_change_24h)}">
                ${(typeof token.price_change_24h === 'number' && token.price_change_24h > 0) ? '+' : ''}${token.price_change_24h || '0.00'}%
              </span>
            </div>
            <div class="token-card-stat">
              <span class="token-card-stat-label">Market Cap</span>
              <span class="token-card-stat-value">${token.market_cap || '$0'}</span>
            </div>
            <div class="token-card-stat">
              <span class="token-card-stat-label">Volume</span>
              <span class="token-card-stat-value">${token.volume_24h || '$0'}</span>
            </div>
            <div class="token-card-stat">
              <span class="token-card-stat-label">Confidence</span>
              <span class="token-card-stat-value" style="color:var(--nova);">${confidence}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  getChangeClass(value) {
    if (!value || value === 0 || value === '0.00') return '';
    const num = parseFloat(value);
    if (num > 0) return 'positive';
    if (num < 0) return 'negative';
    return '';
  }

  updateBadgeCounts() {
    const badgeTrending = document.getElementById('badge-trending');
    const badgeGainers = document.getElementById('badge-gainers');
    const badgeLosers = document.getElementById('badge-losers');
    const badgeAi = document.getElementById('badge-ai');

    if (badgeTrending) badgeTrending.textContent = this.data.trending.length || '—';
    if (badgeGainers) badgeGainers.textContent = this.data.gainers.length || '—';
    if (badgeLosers) badgeLosers.textContent = this.data.losers.length || '—';
    if (badgeAi) badgeAi.textContent = this.data['ai-verified'].length || '—';
  }

  updateLastUpdated() {
    const el = document.getElementById('last-updated');
    if (el && this.lastUpdated) {
      el.textContent = this.lastUpdated.toLocaleTimeString();
    }
  }
}

const markets = new MarketsApp();
window.markets = markets;

export default markets;
