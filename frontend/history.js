const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;

class HistoryApp {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;

    this.allTokens = [];
    this.allInvestigations = [];
    this.combined = [];
    this.searchQuery = '';

    this.init();
  }

  init() {
    this.cacheElements();
    this.bindEvents();
    this.loadData();
    this.connectWebSocket();

    // Auto-refresh every 30s as fallback / sync
    setInterval(() => this.loadData(), 30000);
  }

  cacheElements() {
    this.els = {
      grid: document.getElementById('history-grid'),
      searchInput: document.getElementById('search-input'),
      searchBtn: document.getElementById('search-btn'),
      total: document.getElementById('stat-total'),
      safe: document.getElementById('stat-safe'),
      warning: document.getElementById('stat-warning'),
      risk: document.getElementById('stat-risk'),
      loading: document.getElementById('history-loading'),
      empty: document.getElementById('history-empty'),
    };
  }

  bindEvents() {
    if (this.els.searchBtn) {
      this.els.searchBtn.addEventListener('click', () => this.handleSearch());
    }
    if (this.els.searchInput) {
      this.els.searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.handleSearch();
      });
      // Live search as user types (debounced)
      let timer;
      this.els.searchInput.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => this.handleSearch(), 300);
      });
    }
  }

  // ─────────────────────────────────────────────────────────────
  // WebSocket — Live Streaming
  // ─────────────────────────────────────────────────────────────

  connectWebSocket() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      this.ws = new WebSocket(WS_URL);

      this.ws.onopen = () => {
        console.log('[History] WS connected');
        this.reconnectDelay = 1000;
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleLiveEvent(data);
        } catch (e) {
          console.error('[History] WS parse error:', e);
        }
      };

      this.ws.onclose = (event) => {
        console.log(`[History] WS disconnected (code: ${event.code}), reconnecting in ${this.reconnectDelay}ms...`);
        this.reconnectTimer = setTimeout(() => {
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
          this.connectWebSocket();
        }, this.reconnectDelay);
      };

      this.ws.onerror = (err) => {
        console.error('[History] WS error:', err);
      };
    } catch (e) {
      console.error('[History] WS connection failed:', e);
      this.reconnectTimer = setTimeout(() => this.connectWebSocket(), this.reconnectDelay);
    }
  }

  /**
   * Handle live WebSocket events.
   * NEW_TOKEN: Nova discovered a token — prepend to tokens list.
   * INVESTIGATION_COMPLETE: Orion finished — prepend to investigations list.
   * SIGNAL: Verdict rendered — update stats, may trigger re-filter.
   */
  handleLiveEvent(data) {
    const { type, payload } = data;

    if (type === 'NEW_TOKEN') {
      console.log('[History] Live NEW_TOKEN:', payload.symbol);
      // Build a minimal token record from the lightweight NEW_TOKEN payload
      const token = {
        address: payload.token,
        token_address: payload.token,
        chain: payload.chain,
        symbol: payload.symbol,
        name: payload.symbol || 'Unknown',
        status: 'pending',
        origin_source: 'live_ws',
        timestamp: payload.timestamp || Date.now() / 1000,
        discovered_at: payload.timestamp || Date.now() / 1000,
      };
      this.allTokens.unshift(token);
      this.updateStats();
      this.applyFilter();
    }
    else if (type === 'INVESTIGATION_COMPLETE') {
      console.log('[History] Live INVESTIGATION_COMPLETE:', payload.symbol);
      this.allInvestigations.unshift(payload);
      this.updateStats();
      this.applyFilter();
    }
    else if (type === 'SIGNAL') {
      console.log('[History] Live SIGNAL:', payload.verdict);
      // A signal may correspond to a token that was just investigated.
      // Full sync happens on next REST poll; for now just update stats.
      this.updateStats();
    }
    else if (type === 'SYSTEM') {
      console.log('[History] System:', payload?.message);
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Data Loading (REST fallback)
  // ─────────────────────────────────────────────────────────────

  async loadData() {
    this.showLoading(true);
    try {
      const [tokensRes, invRes] = await Promise.all([
        fetch('/api/tokens?limit=200').catch(() => null),
        fetch('/api/investigations?limit=100').catch(() => null),
      ]);

      let tokensChanged = false;
      let invChanged = false;

      if (tokensRes && tokensRes.ok) {
        const tData = await tokensRes.json();
        const newTokens = tData.tokens || [];
        // Only replace if count changed (avoid flicker on live updates)
        if (newTokens.length !== this.allTokens.length) {
          this.allTokens = newTokens;
          tokensChanged = true;
        }
      }

      if (invRes && invRes.ok) {
        const iData = await invRes.json();
        const newInv = iData.investigations || [];
        if (newInv.length !== this.allInvestigations.length) {
          this.allInvestigations = newInv;
          invChanged = true;
        }
      }

      if (tokensChanged || invChanged) {
        this.updateStats();
        this.applyFilter();
      }
    } catch (e) {
      console.error('[History] Load failed:', e);
      if (this.els.grid) {
        this.els.grid.innerHTML = `
          <div class="error-state">
            <p>Failed to load records.</p>
            <p class="error-detail">${this.escapeHtml(String(e))}</p>
          </div>`;
      }
    } finally {
      this.showLoading(false);
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Search / Filter
  // ─────────────────────────────────────────────────────────────

  handleSearch() {
    this.searchQuery = (this.els.searchInput?.value || '').trim().toLowerCase();
    this.applyFilter();
  }

  applyFilter() {
    const q = this.searchQuery;

    const filteredTokens = q
      ? this.allTokens.filter(t =>
          (t.symbol || '').toLowerCase().includes(q) ||
          (t.name || '').toLowerCase().includes(q) ||
          (t.address || '').toLowerCase().includes(q) ||
          (t.token_address || '').toLowerCase().includes(q)
        )
      : [...this.allTokens];

    const filteredInv = q
      ? this.allInvestigations.filter(i =>
          (i.token_symbol || '').toLowerCase().includes(q) ||
          (i.token_address || '').toLowerCase().includes(q) ||
          (i.name || '').toLowerCase().includes(q)
        )
      : [...this.allInvestigations];

    // Combine and sort by timestamp (newest first)
    this.combined = [
      ...filteredTokens.map(t => ({ ...t, _type: 'token', _ts: t.timestamp || t.discovered_at || 0 })),
      ...filteredInv.map(i => ({ ...i, _type: 'investigation', _ts: i.timestamp || 0 })),
    ].sort((a, b) => b._ts - a._ts);

    this.render();
  }

  // ─────────────────────────────────────────────────────────────
  // Stats
  // ─────────────────────────────────────────────────────────────

  updateStats() {
    const safe = this.allInvestigations.filter(i => i.verdict === 'SAFE').length;
    const warning = this.allInvestigations.filter(i => i.verdict === 'WARNING').length;
    const risk = this.allInvestigations.filter(i => i.verdict === 'HIGH_RISK').length;
    const total = this.allTokens.length;

    if (this.els.total) this.els.total.textContent = total.toLocaleString();
    if (this.els.safe) this.els.safe.textContent = safe.toLocaleString();
    if (this.els.warning) this.els.warning.textContent = warning.toLocaleString();
    if (this.els.risk) this.els.risk.textContent = risk.toLocaleString();
  }

  // ─────────────────────────────────────────────────────────────
  // Rendering
  // ─────────────────────────────────────────────────────────────

  render() {
    if (!this.els.grid) return;

    if (this.combined.length === 0) {
      this.els.grid.innerHTML = '';
      if (this.els.empty) this.els.empty.style.display = 'block';
      return;
    }

    if (this.els.empty) this.els.empty.style.display = 'none';
    this.els.grid.innerHTML = this.combined.map(item => {
      if (item._type === 'token') return this.renderTokenCard(item);
      return this.renderInvestigationCard(item);
    }).join('');
  }

  renderTokenCard(token) {
    const symbol = token.symbol || '???';
    const name = token.name || 'Unknown';
    const addr = token.address || token.token_address || 'unknown';
    const shortAddr = addr.length > 12 ? `${addr.slice(0, 8)}...${addr.slice(-4)}` : addr;
    const chain = (token.chain || '?').toUpperCase();
    const status = token.status || 'pending';
    const statusClass = status === 'completed' ? 'safe' : status === 'rejected' ? 'risk' : 'warning';
    const time = this.timeAgo(token.timestamp || token.discovered_at);
    const liq = this.formatCurrency(token.liquidity);
    const vol = this.formatCurrency(token.volume_24h);
    const price = this.formatPrice(token.price);

    return `
      <div class="record-card ${statusClass}">
        <div class="record-header">
          <span class="record-symbol">${this.escapeHtml(symbol)}</span>
          <span class="record-chain">${this.escapeHtml(chain)}</span>
          <span class="record-status ${statusClass}">${status.toUpperCase()}</span>
        </div>
        <div class="record-name">${this.escapeHtml(name)}</div>
        <div class="record-address" title="${this.escapeHtml(addr)}">Contract: ${this.escapeHtml(shortAddr)}</div>
        <div class="record-meta">
          <span>💧 Liq: ${liq}</span>
          <span>📊 Vol: ${vol}</span>
          <span>💰 Price: ${price}</span>
        </div>
        <div class="record-time">${time}</div>
        ${token.origin_source ? `<div class="record-source">Source: ${this.escapeHtml(token.origin_source)}</div>` : ''}
      </div>
    `;
  }

  renderInvestigationCard(inv) {
    const symbol = inv.token_symbol || '???';
    const name = inv.name || symbol;
    const addr = inv.token_address || 'unknown';
    const shortAddr = addr.length > 12 ? `${addr.slice(0, 8)}...${addr.slice(-4)}` : addr;
    const chain = (inv.chain || '?').toUpperCase();
    const verdict = inv.verdict || 'UNKNOWN';
    const vClass = verdict === 'SAFE' ? 'safe' : verdict === 'HIGH_RISK' ? 'risk' : 'warning';
    const confidence = inv.confidence !== undefined ? `${(inv.confidence * 100).toFixed(0)}%` : 'N/A';
    const score = inv.risk_score !== undefined ? `${inv.risk_score}/100` : 'N/A';
    const time = this.timeAgo(inv.timestamp);
    const action = inv.action || '';

    return `
      <div class="record-card ${vClass}">
        <div class="record-header">
          <span class="record-symbol">${this.escapeHtml(symbol)}</span>
          <span class="record-chain">${this.escapeHtml(chain)}</span>
          <span class="record-status ${vClass}">${verdict}</span>
        </div>
        <div class="record-name">${this.escapeHtml(name)}</div>
        <div class="record-address" title="${this.escapeHtml(addr)}">Contract: ${this.escapeHtml(shortAddr)}</div>
        <div class="record-meta">
          <span>🎯 Score: ${score}</span>
          <span>🎲 Conf: ${confidence}</span>
          ${action ? `<span>⚡ Action: ${this.escapeHtml(action)}</span>` : ''}
        </div>
        ${inv.reasoning ? `<div class="record-reasoning">${this.escapeHtml(inv.reasoning)}</div>` : ''}
        ${inv.nova_message ? `<div class="record-nova">🤖 <strong>Nova:</strong> ${this.escapeHtml(inv.nova_message)}</div>` : ''}
        <div class="record-time">${time}</div>
      </div>
    `;
  }

  // ─────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────

  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  timeAgo(ts) {
    if (!ts) return 'Unknown';
    const diff = (Date.now() / 1000) - ts;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  formatCurrency(val) {
    if (val === undefined || val === null) return '$0';
    const n = Number(val);
    if (isNaN(n)) return '$0';
    if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `$${(n / 1_000).toFixed(2)}K`;
    return `$${n.toLocaleString(undefined, {maximumFractionDigits: 2})}`;
  }

  formatPrice(val) {
    if (val === undefined || val === null) return '$0';
    const n = Number(val);
    if (isNaN(n)) return '$0';
    if (n >= 1) return `$${n.toLocaleString(undefined, {maximumFractionDigits: 4})}`;
    return `$${n.toFixed(8)}`;
  }

  showLoading(show) {
    if (this.els.loading) this.els.loading.style.display = show ? 'block' : 'none';
  }
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => new HistoryApp());
} else {
  new HistoryApp();
}
