/**
 * 📜 frontend/history.js
 * ClawIntel v4.0 — Investigation History Browser
 * Fetches from DB via REST API. No localStorage.
 */

const CONFIG = {
  API_BASE: '',
  REFRESH_INTERVAL: 30000,
};

class HistoryApp {
  constructor() {
    this.investigations = [];
    this.chatHistory = [];
    this.filtered = [];
    this.stats = { total: 0, safe: 0, warning: 0, high_risk: 0 };

    this.listEl = document.getElementById('investigation-list');
    this.chatSection = document.getElementById('chat-log-section');
    this.chatListEl = document.getElementById('chat-history-list');
    this.statsEls = {
      total: document.getElementById('stat-total'),
      safe: document.getElementById('stat-safe'),
      warning: document.getElementById('stat-warning'),
      risk: document.getElementById('stat-risk'),
    };
    this.filterVerdict = document.getElementById('filter-verdict');
    this.filterChain = document.getElementById('filter-chain');
    this.searchInput = document.getElementById('search-token');

    this.init();
  }

  init() {
    this.fetchData();
    this.setupFilters();
    setInterval(() => this.fetchData(), CONFIG.REFRESH_INTERVAL);
  }

  setupFilters() {
    this.filterVerdict?.addEventListener('change', () => this.applyFilters());
    this.filterChain?.addEventListener('change', () => this.applyFilters());
    this.searchInput?.addEventListener('input', () => this.applyFilters());
  }

  async fetchData() {
    try {
      const [invRes, chatRes] = await Promise.all([
        fetch('/api/investigations?limit=100'),
        fetch('/api/chat/history?limit=50').catch(() => null)
      ]);

      if (!invRes.ok) throw new Error(`Investigations API error: ${invRes.status}`);
      const invData = await invRes.json();
      this.investigations = invData.investigations || [];

      if (chatRes?.ok) {
        const chatData = await chatRes.json();
        this.chatHistory = chatData.messages || [];
        this.renderChatHistory();
      }

      this.calculateStats();
      this.applyFilters();
    } catch (e) {
      console.error('[History] Fetch failed:', e);
      this.listEl.innerHTML = '<div class="empty-state">Failed to load history from server. Is the backend running?</div>';
    }
  }

  calculateStats() {
    this.stats = {
      total: this.investigations.length,
      safe: this.investigations.filter(i => i.verdict === 'SAFE').length,
      warning: this.investigations.filter(i => i.verdict === 'WARNING').length,
      high_risk: this.investigations.filter(i => i.verdict === 'HIGH_RISK').length,
    };
    this.updateStatsUI();
  }

  updateStatsUI() {
    if (this.statsEls.total) this.statsEls.total.textContent = this.stats.total;
    if (this.statsEls.safe) this.statsEls.safe.textContent = this.stats.safe;
    if (this.statsEls.warning) this.statsEls.warning.textContent = this.stats.warning;
    if (this.statsEls.risk) this.statsEls.risk.textContent = this.stats.high_risk;
  }

  applyFilters() {
    const verdict = this.filterVerdict?.value || 'all';
    const chain = this.filterChain?.value || 'all';
    const query = (this.searchInput?.value || '').toLowerCase().trim();

    this.filtered = this.investigations.filter(inv => {
      if (verdict !== 'all' && inv.verdict !== verdict) return false;
      if (chain !== 'all' && inv.chain !== chain) return false;
      if (query) {
        const symbol = (inv.symbol || '').toLowerCase();
        const address = (inv.token_address || '').toLowerCase();
        const name = (inv.name || '').toLowerCase();
        const creator = (inv.creator || '').toLowerCase();
        if (!symbol.includes(query) && !address.includes(query) && !name.includes(query) && !creator.includes(query)) {
          return false;
        }
      }
      return true;
    });

    this.renderList();
  }

  renderList() {
    if (!this.filtered.length) {
      this.listEl.innerHTML = '<div class="empty-state">No investigations match your filters</div>';
      return;
    }
    this.listEl.innerHTML = this.filtered.map(inv => this.renderInvestigationCard(inv)).join('');
  }

  renderInvestigationCard(inv) {
    const verdictColors = {
      SAFE: 'var(--safe)',
      WARNING: 'var(--warning)',
      HIGH_RISK: 'var(--danger)',
    };
    const color = verdictColors[inv.verdict] || 'var(--text-secondary)';
    const time = inv.timestamp ? new Date(inv.timestamp * 1000).toLocaleString() : 'Unknown';
    const chain = (inv.chain || 'unknown').toUpperCase();
    const symbol = inv.symbol || '???';
    const address = inv.token_address || '';
    const addressShort = address ? `${address.slice(0, 8)}...${address.slice(-4)}` : 'N/A';
    const confidence = (inv.confidence !== undefined) ? `${(inv.confidence * 100).toFixed(0)}%` : 'N/A';
    const attention = (inv.attention_score !== undefined) ? inv.attention_score.toFixed(1) : null;

    return `
      <div class="investigation-card" data-verdict="${inv.verdict}" data-chain="${inv.chain}">
        <div class="card-header">
          <div class="token-info">
            <span class="token-symbol" style="color: ${color}">${this.escapeHtml(symbol)}</span>
            <span class="token-chain">${chain}</span>
          </div>
          <div class="verdict-badge" style="background: ${color}20; color: ${color}; border: 1px solid ${color}40;">
            ${inv.verdict || 'UNKNOWN'}
          </div>
        </div>
        <div class="card-body">
          <div class="detail-row">
            <span class="detail-label">Contract</span>
            <span class="detail-value mono">${addressShort}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Confidence</span>
            <span class="detail-value">${confidence}</span>
          </div>
          ${attention !== null ? `
          <div class="detail-row">
            <span class="detail-label">Attention</span>
            <span class="detail-value">${attention}/100</span>
          </div>
          ` : ''}
          <div class="detail-row">
            <span class="detail-label">Time</span>
            <span class="detail-value">${time}</span>
          </div>
          ${inv.action ? `
          <div class="detail-row">
            <span class="detail-label">Action</span>
            <span class="detail-value" style="text-transform: uppercase; font-weight: 600; color: ${color};">${inv.action}</span>
          </div>
          ` : ''}
          ${inv.creator && inv.creator !== 'unknown' ? `
          <div class="detail-row">
            <span class="detail-label">Creator</span>
            <span class="detail-value mono">${inv.creator.slice(0, 10)}...${inv.creator.slice(-4)}</span>
          </div>
          ` : ''}
        </div>
        ${inv.reasoning ? `
        <div class="card-reasoning">
          <p>${this.escapeHtml(inv.reasoning)}</p>
        </div>
        ` : ''}
        ${inv.nova_message ? `
        <div class="card-reasoning">
          <p style="color: var(--nova);"><strong>Nova:</strong> ${this.escapeHtml(inv.nova_message)}</p>
        </div>
        ` : ''}
      </div>
    `;
  }

  renderChatHistory() {
    if (!this.chatHistory.length) {
      if (this.chatSection) this.chatSection.style.display = 'none';
      return;
    }
    if (this.chatSection) this.chatSection.style.display = 'block';
    if (!this.chatListEl) return;

    this.chatListEl.innerHTML = this.chatHistory.map(msg => {
      const agent = msg.agent || 'system';
      const time = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleTimeString() : '';
      const text = msg.message || '';
      return `
        <div class="chat-message agent-${agent}">
          <span class="chat-agent" style="color: var(--${agent.toLowerCase()}, var(--text-secondary));">${agent}</span>
          <span class="chat-text">${this.escapeHtml(text)}</span>
          <span class="chat-time">${time}</span>
        </div>
      `;
    }).join('');
  }

  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

const app = new HistoryApp();
