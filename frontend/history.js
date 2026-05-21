/**
 * 📜 frontend/history.js
 * ClawIntel — Investigation History Browser
 */

const CONFIG = {
  API_BASE: '',
  REFRESH_INTERVAL: 30000,
};

class HistoryApp {
  constructor() {
    this.investigations = [];
    this.filtered = [];
    this.stats = { total: 0, safe: 0, warning: 0, high_risk: 0 };

    this.listEl = document.getElementById('investigation-list');
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

    // Auto-refresh
    setInterval(() => this.fetchData(), CONFIG.REFRESH_INTERVAL);
  }

  setupFilters() {
    this.filterVerdict?.addEventListener('change', () => this.applyFilters());
    this.filterChain?.addEventListener('change', () => this.applyFilters());
    this.searchInput?.addEventListener('input', () => this.applyFilters());
  }

  async fetchData() {
    try {
      // Fetch investigations from API
      const res = await fetch('/api/investigations?limit=100');
      if (!res.ok) throw new Error('API error');
      const data = await res.json();

      this.investigations = data.investigations || [];
      this.calculateStats();
      this.applyFilters();
    } catch (e) {
      console.error('[History] Fetch failed:', e);
      this.listEl.innerHTML = '<div class="empty-state">Failed to load past analysis</div>';
    }
  }

  calculateStats() {
    this.stats = {
      total: this.investigations.length,
      safe: this.investigations.filter(i => i.verdict === 'SAFE').length,
      warning: this.investigations.filter(i => i.verdict === 'WARNING').length,
      high_risk: this.investigations.filter(i => i.verdict === 'HIGH_RISK').length,
    };

    if (this.statsEls.total) this.statsEls.total.textContent = this.stats.total;
    if (this.statsEls.safe) this.statsEls.safe.textContent = this.stats.safe;
    if (this.statsEls.warning) this.statsEls.warning.textContent = this.stats.warning;
    if (this.statsEls.risk) this.statsEls.risk.textContent = this.stats.high_risk;
  }

  applyFilters() {
    const verdict = this.filterVerdict?.value || '';
    const chain = this.filterChain?.value || '';
    const search = this.searchInput?.value.toLowerCase() || '';

    this.filtered = this.investigations.filter(inv => {
      if (verdict && inv.verdict !== verdict) return false;
      if (chain && inv.chain !== chain) return false;
      if (search) {
        const match = (inv.symbol || '').toLowerCase().includes(search) ||
                      (inv.token_address || '').toLowerCase().includes(search);
        if (!match) return false;
      }
      return true;
    });

    this.render();
  }

  render() {
    if (!this.listEl) return;

    if (this.filtered.length === 0) {
      this.listEl.innerHTML = '<div class="empty-state">No analysis match your filters.</div>';
      return;
    }

    this.listEl.innerHTML = this.filtered.map(inv => this.renderCard(inv)).join('');
  }

  renderCard(inv) {
    const verdictClass = inv.verdict?.toLowerCase() || 'warning';
    const icons = { safe: '✅', warning: '⚠️', high_risk: '🚨' };
    const icon = icons[verdictClass] || '❓';
    const time = inv.timestamp ? this.formatTime(inv.timestamp) : 'Unknown';
    const shortAddr = inv.token_address 
      ? inv.token_address.slice(0, 6) + '...' + inv.token_address.slice(-4)
      : 'Unknown';
    const confidence = typeof inv.confidence === 'number' 
      ? Math.round(inv.confidence * 100) + '%'
      : 'N/A';

    return `
      <div class="inv-card" onclick="historyApp.showDetail('${inv.token_address}')">
        <div class="inv-verdict ${verdictClass}">${icon}</div>
        <div class="inv-info">
          <div class="inv-symbol">${inv.symbol || '???'} <span style="color:var(--text-muted);font-weight:400;">(${inv.chain?.toUpperCase() || '?'})</span></div>
          <div class="inv-meta">${shortAddr} · Confidence: ${confidence}</div>
        </div>
        <div class="inv-time">${time}</div>
      </div>
    `;
  }

  formatTime(ts) {
    if (!ts) return 'Unknown';
    const date = new Date(ts * 1000);
    const now = new Date();
    const diff = (now - date) / 1000;

    if (diff < 60) return 'Just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return date.toLocaleDateString();
  }

  showDetail(tokenAddress) {
    // Navigate to analysis page with pre-filled token
    window.location.href = `analysis.html?token=${tokenAddress}`;
  }
}

const historyApp = new HistoryApp();
window.historyApp = historyApp;

export default historyApp;
