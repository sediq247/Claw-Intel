/**
 * 🔬 frontend/analysis.js
 * ClawIntel — Forensic Lab
 * User pastes token → Agents investigate → Chat their findings → Final verdict
 * PURE BACKEND: All messages come from WebSocket. No demo simulation.
 */

const CONFIG = {
  WS_URL: `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`,
  RECONNECT_INTERVAL: 3000,
  TYPING_DURATION: 1500,
};

class ForensicLab {
  constructor() {
    this.ws = null;
    this.isInvestigating = false;
    this.currentInvestigation = null;
    this.messagesContainer = document.getElementById('investigation-messages');
    this.emptyState = document.getElementById('investigation-empty');
    this.scanBtn = document.getElementById('scan-btn');
    this.scanBtnText = document.getElementById('scan-btn-text');
    this.tokenInput = document.getElementById('token-address');
    this.chainSelect = document.getElementById('chain-select');
    this.progressContainer = document.getElementById('scan-progress');
    this.progressFill = document.getElementById('scan-progress-fill');
    this.progressStep = document.getElementById('scan-step');
    this.progressPercent = document.getElementById('scan-percent');
    this.tokenSummary = document.getElementById('token-summary');
    this.verdictContainer = document.getElementById('verdict-container');
    this.investigationStatus = document.getElementById('investigation-status');

    this.agentColors = {
      Nova: '#00e5ff', Atlas: '#00c853', Vega: '#d500f9',
      Echo: '#ffd600', Orion: '#ff1744', system: '#8a8a9a'
    };
    this.agentEmojis = {
      Nova: 'N', Atlas: 'V', Vega: 'V', Echo: 'E', Orion: 'O', system: '⚖️'
    };

    this.init();
  }

  init() {
    this.connectWebSocket();

    // Enter key on input
    if (this.tokenInput) {
      this.tokenInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.startInvestigation();
      });
    }
  }

  connectWebSocket() {
    try {
      this.ws = new WebSocket(CONFIG.WS_URL);

      this.ws.onopen = () => {
        this.setConnectionStatus(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const { type, payload } = JSON.parse(event.data);
          this.handleMessage(type, payload);
        } catch (e) {
          console.error('[Lab] Parse error:', e);
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
      console.error('[Lab] WS error:', e);
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

  // ── Start Investigation ──
  async startInvestigation() {
    const address = this.tokenInput.value.trim();
    const chain = this.chainSelect ? this.chainSelect.value : 'bsc';

    if (!address) {
      this.tokenInput.focus();
      this.tokenInput.style.borderColor = 'var(--danger)';
      setTimeout(() => this.tokenInput.style.borderColor = '', 1000);
      return;
    }

    if (this.isInvestigating) return;
    this.isInvestigating = true;

    // Reset UI
    this.resetInvestigation();
    if (this.emptyState) this.emptyState.style.display = 'none';

    // Update button
    if (this.scanBtn) this.scanBtn.disabled = true;
    if (this.scanBtnText) {
      this.scanBtnText.innerHTML = '<span class="spinner spinner-sm" style="display:inline-block;vertical-align:middle;margin-right:0.4rem;"></span> Scanning...';
    }

    // Show progress
    if (this.progressContainer) this.progressContainer.classList.add('active');
    this.updateProgress(5, 'Initializing investigation...');
    if (this.investigationStatus) {
      this.investigationStatus.innerHTML = '<span class="spinner spinner-sm" style="display:inline-block;vertical-align:middle;margin-right:0.4rem;"></span> Investigating...';
    }

    // Send to backend via WebSocket (preferred) or HTTP fallback
    let sent = false;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'MANUAL_INVESTIGATE',
        payload: { tokenAddress: address, chain: chain }
      }));
      sent = true;
    }

    // Always also POST to API for reliability
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tokenAddress: address, chain: chain })
      });
      if (!res.ok) throw new Error('API error');
      sent = true;
    } catch (e) {
      console.error('[Lab] API error:', e);
      if (!sent) {
        this.addSystemMessage('Failed to start investigation. Please check your connection.');
        this.endInvestigation();
        return;
      }
    }

    // NO DEMO — we wait for real backend messages via WebSocket
    // Progress updates come from handleMessage as agents complete
  }

  resetInvestigation() {
    if (this.messagesContainer) this.messagesContainer.innerHTML = '';
    if (this.tokenSummary) this.tokenSummary.classList.remove('visible');
    if (this.verdictContainer) this.verdictContainer.innerHTML = '';
    this.updateProgress(0, '');
    this.currentInvestigation = { messages: [] };
  }

  endInvestigation() {
    this.isInvestigating = false;
    if (this.scanBtn) this.scanBtn.disabled = false;
    if (this.scanBtnText) this.scanBtnText.textContent = '🔍 Scan';
    if (this.progressContainer) this.progressContainer.classList.remove('active');
    if (this.investigationStatus) {
      this.investigationStatus.innerHTML = '<span>Investigation complete</span>';
    }
  }

  updateProgress(percent, step) {
    if (this.progressFill) this.progressFill.style.width = percent + '%';
    if (this.progressPercent) this.progressPercent.textContent = percent + '%';
    if (step && this.progressStep) this.progressStep.textContent = step;
  }

  // ── Message Handling ──
  handleMessage(type, payload) {
    switch (type) {
      case 'AGENT_MESSAGE':
        this.addAgentMessage(payload);
        break;
      case 'SIMULATION_COMPLETE':
        this.updateProgress(50, 'Simulation complete');
        break;
      case 'ANALYSIS_COMPLETE':
        this.updateProgress(70, 'Risk analysis complete');
        break;
      case 'CREATOR_INTELLIGENCE':
        this.updateProgress(85, 'History check complete');
        break;
      case 'DECISION_COMPLETE':
        this.updateProgress(100, 'Verdict delivered');
        this.showVerdict(payload);
        this.endInvestigation();
        break;
      case 'NEW_TOKEN':
        this.updateTokenSummary(payload);
        this.updateProgress(20, 'Token data retrieved');
        break;
      case 'SYSTEM':
        if (payload.message) this.addSystemMessage(payload.message);
        break;
    }
  }

  // ── Agent Messages ──
  addAgentMessage(payload) {
    const agent = payload.agent || 'system';
    const message = payload.message || '';
    const msgType = payload.type || 'chat';

    if (this.emptyState) this.emptyState.style.display = 'none';

    // Show typing first, then message
    this.showTyping(agent);

    const delay = msgType === 'response' ? 1200 : 400;

    setTimeout(() => {
      this.hideTyping(agent);

      const el = document.createElement('div');
      el.className = 'agent-msg';
      el.style.animationDelay = '0s';

      const color = this.agentColors[agent] || '#8a8a9a';
      const emoji = this.agentEmojis[agent] || '🤖';
      const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      const processed = this.processMessageText(message);

      el.innerHTML = `
        <div class="agent-msg-avatar ${agent.toLowerCase()}">${emoji}</div>
        <div class="agent-msg-content">
          <div class="agent-msg-name ${agent.toLowerCase()}">${agent}</div>
          <div class="agent-msg-text">${processed}</div>
          <div class="agent-msg-time">${time}</div>
        </div>
      `;

      if (this.messagesContainer) {
        this.messagesContainer.appendChild(el);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
      }

      if (this.currentInvestigation) {
        this.currentInvestigation.messages.push(payload);
      }
    }, delay);
  }

  addSystemMessage(text) {
    this.addAgentMessage({
      agent: 'system',
      message: text,
      type: 'system'
    });
  }

  showTyping(agent) {
    const id = `typing-${agent.toLowerCase()}`;
    if (document.getElementById(id)) return;

    const el = document.createElement('div');
    el.id = id;
    el.className = 'typing-row visible';
    el.innerHTML = `
      <div class="typing-row-avatar ${agent.toLowerCase()}" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);">
        ${this.agentEmojis[agent] || '🤖'}
      </div>
      <div class="typing-row-dots">
        <span></span><span></span><span></span>
      </div>
      <span style="font-size:0.7rem;color:var(--text-muted);font-style:italic;">${agent} is investigating...</span>
    `;

    if (this.messagesContainer) {
      this.messagesContainer.appendChild(el);
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
  }

  hideTyping(agent) {
    const id = `typing-${agent.toLowerCase()}`;
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  processMessageText(text) {
    if (!text) return '';

    let safe = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Highlight verdicts
    safe = safe.replace(/\*\*SAFE\*\*/g, '<span style="display:inline-flex;align-items:center;gap:0.25rem;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:rgba(0,200,83,0.15);color:var(--safe);border:1px solid rgba(0,200,83,0.3);">✅ SAFE</span>');
    safe = safe.replace(/\*\*WARNING\*\*/g, '<span style="display:inline-flex;align-items:center;gap:0.25rem;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:rgba(255,179,0,0.15);color:var(--warning);border:1px solid rgba(255,179,0,0.3);">⚠️ WARNING</span>');
    safe = safe.replace(/\*\*HIGH RISK\*\*/g, '<span style="display:inline-flex;align-items:center;gap:0.25rem;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:rgba(255,23,68,0.15);color:var(--danger);border:1px solid rgba(255,23,68,0.3);">🚨 HIGH RISK</span>');
    safe = safe.replace(/\*\*AVOID\*\*/g, '<span style="display:inline-flex;align-items:center;gap:0.25rem;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:rgba(255,23,68,0.15);color:var(--danger);border:1px solid rgba(255,23,68,0.3);">⛔ AVOID</span>');

    // Token addresses
    safe = safe.replace(/(0x[a-fA-F0-9]{40})/g, '<code>$1</code>');

    // Convert newlines
    safe = safe.replace(/\n/g, '<br>');

    return safe;
  }

  // ── Token Summary ──
  updateTokenSummary(data) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val || '—';
    };

    set('sum-name', data.token_name);
    set('sum-symbol', data.token_symbol);
    set('sum-chain', data.chain?.toUpperCase());
    set('sum-contract', data.token_address ? data.token_address.slice(0, 8) + '...' + data.token_address.slice(-4) : '—');

    if (data.liquidity_usd) set('sum-liquidity', '$' + this.formatNumber(data.liquidity_usd));
    if (data.market_cap) set('sum-mcap', '$' + this.formatNumber(data.market_cap));

    if (this.tokenSummary) this.tokenSummary.classList.add('visible');
  }

  formatNumber(num) {
    if (num >= 1_000_000_000) return (num / 1_000_000_000).toFixed(2) + 'B';
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(2) + 'K';
    return num.toLocaleString();
  }

  // ── Verdict ──
  showVerdict(data) {
    const verdict = data.verdict || 'WARNING';
    const confidence = data.confidence || 0;
    const reasoning = data.reasoning || '';
    const factors = data.factors || {};

    const verdictClass = verdict.toLowerCase();
    const icons = { SAFE: '✅', WARNING: '⚠️', HIGH_RISK: '🚨' };
    const titles = {
      SAFE: 'SAFE — Approved by the Swarm',
      WARNING: 'WARNING — Proceed with Caution',
      HIGH_RISK: 'HIGH RISK — Avoid at All Costs'
    };

    const confidencePct = typeof confidence === 'number' ? Math.round(confidence * 100) : confidence;

    if (this.verdictContainer) {
      this.verdictContainer.innerHTML = `
        <div class="verdict-panel ${verdictClass}">
          <div class="verdict-header">
            <div class="verdict-icon ${verdictClass}">${icons[verdict] || '❓'}</div>
            <div>
              <div class="verdict-title ${verdictClass}">${titles[verdict] || verdict}</div>
              <div class="verdict-confidence">Confidence: ${confidencePct}% · Swarm Consensus</div>
            </div>
          </div>
          <div class="verdict-body">${this.processMessageText(reasoning)}</div>
          <div class="verdict-factors">
            <div class="verdict-factor">
              <span class="verdict-factor-label">Simulation Score</span>
              <span class="verdict-factor-value" style="color:${factors.simulation_score > 30 ? 'var(--danger)' : 'var(--text-secondary)'}">${factors.simulation_score || 'N/A'}/100</span>
            </div>
            <div class="verdict-factor">
              <span class="verdict-factor-label">Risk Analysis</span>
              <span class="verdict-factor-value" style="color:${factors.analysis_risk > 50 ? 'var(--danger)' : factors.analysis_risk > 30 ? 'var(--warning)' : 'var(--safe)'}">${factors.analysis_risk || 'N/A'}/100</span>
            </div>
            <div class="verdict-factor">
              <span class="verdict-factor-label">Creator Rep</span>
              <span class="verdict-factor-value" style="color:${factors.creator_reputation < 30 ? 'var(--danger)' : factors.creator_reputation < 60 ? 'var(--warning)' : 'var(--safe)'}">${factors.creator_reputation || 'N/A'}/100</span>
            </div>
            <div class="verdict-factor">
              <span class="verdict-factor-label">Liquidity</span>
              <span class="verdict-factor-value">${factors.liquidity_usd ? '$' + this.formatNumber(factors.liquidity_usd) : 'N/A'}</span>
            </div>
            <div class="verdict-factor">
              <span class="verdict-factor-label">Honeypot</span>
              <span class="verdict-factor-value" style="color:${factors.honeypot ? 'var(--danger)' : 'var(--safe)'}">${factors.honeypot ? 'YES' : 'No'}</span>
            </div>
            <div class="verdict-factor">
              <span class="verdict-factor-label">Can Sell</span>
              <span class="verdict-factor-value" style="color:${factors.can_sell ? 'var(--safe)' : 'var(--danger)'}">${factors.can_sell ? 'Yes' : 'BLOCKED'}</span>
            </div>
          </div>
        </div>
      `;
    }
  }
}

const lab = new ForensicLab();
window.lab = lab;

export default lab;
