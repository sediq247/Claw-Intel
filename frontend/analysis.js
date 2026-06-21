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
    this.investigationStatus = document.getElementById('investigation-status');
    this.scanForm = document.querySelector('.scan-form');
    this.verdictContainer = document.getElementById('verdict-container');

    // Internal DOM elements (created dynamically)
    this.progressContainer = null;
    this.progressFill = null;
    this.progressStep = null;
    this.progressPercent = null;
    this.tokenSummary = null;

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
    this.injectTypingStyles();
    this.connectWebSocket();

    // Enter key on input
    if (this.tokenInput) {
      this.tokenInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.startInvestigation();
      });
    }
  }

  injectTypingStyles() {
    if (document.getElementById('clawintel-typing-styles')) return;
    const style = document.createElement('style');
    style.id = 'clawintel-typing-styles';
    style.textContent = `
      @keyframes typingBounce {
        0%, 60%, 100% { transform: translateY(0); }
        30% { transform: translateY(-6px); }
      }
      @keyframes typingFadeIn {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes agentPulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(var(--agent-rgb), 0.4); }
        50% { box-shadow: 0 0 0 6px rgba(var(--agent-rgb), 0); }
      }
      .typing-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.6rem 0;
        opacity: 0;
        animation: typingFadeIn 0.35s ease forwards;
      }
      .typing-row-avatar {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        font-weight: 700;
        flex-shrink: 0;
        position: relative;
      }
      .typing-row-avatar.nova { --agent-rgb: 0,229,255; background: rgba(0,229,255,0.1); border: 1px solid rgba(0,229,255,0.25); color: #00e5ff; }
      .typing-row-avatar.atlas { --agent-rgb: 0,200,83; background: rgba(0,200,83,0.1); border: 1px solid rgba(0,200,83,0.25); color: #00c853; }
      .typing-row-avatar.vega { --agent-rgb: 213,0,249; background: rgba(213,0,249,0.1); border: 1px solid rgba(213,0,249,0.25); color: #d500f9; }
      .typing-row-avatar.echo { --agent-rgb: 255,214,0; background: rgba(255,214,0,0.1); border: 1px solid rgba(255,214,0,0.25); color: #ffd600; }
      .typing-row-avatar.orion { --agent-rgb: 255,23,68; background: rgba(255,23,68,0.1); border: 1px solid rgba(255,23,68,0.25); color: #ff1744; }
      .typing-row-avatar.system { --agent-rgb: 138,138,154; background: rgba(138,138,154,0.1); border: 1px solid rgba(138,138,154,0.25); color: #8a8a9a; }
      .typing-row-dots {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .typing-row-dots span {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--text-muted);
        animation: typingBounce 1.4s ease-in-out infinite;
      }
      .typing-row-dots span:nth-child(1) { animation-delay: 0s; }
      .typing-row-dots span:nth-child(2) { animation-delay: 0.2s; }
      .typing-row-dots span:nth-child(3) { animation-delay: 0.4s; }
      .typing-row.visible {
        opacity: 1;
      }
    `;
    document.head.appendChild(style);
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

  // ── Internal HTML Generators ──
  createProgressBar() {
    if (this.progressContainer) return;
    const container = document.createElement('div');
    container.className = 'scan-progress-container';
    container.id = 'scan-progress';
    container.style.cssText = `
      margin-top: 1.25rem;
      padding: 1rem 1.25rem;
      background: rgba(10, 10, 18, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 12px;
      backdrop-filter: blur(10px);
      opacity: 0;
      transform: translateY(-8px);
      transition: opacity 0.4s ease, transform 0.4s ease;
    `;
    container.innerHTML = `
      <div class="scan-progress-label" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
        <span id="scan-step" style="font-size:0.8rem;font-weight:500;color:var(--text-secondary);letter-spacing:0.02em;">Initializing...</span>
        <span id="scan-percent" style="font-size:0.85rem;font-weight:700;color:var(--accent);font-family:'JetBrains Mono',monospace;">0%</span>
      </div>
      <div class="scan-progress-bar-wrap" style="width:100%;height:6px;background:rgba(255,255,255,0.04);border-radius:3px;overflow:hidden;position:relative;">
        <div class="scan-progress-bar-fill" id="scan-progress-fill" style="width:0%;height:100%;background:linear-gradient(90deg,var(--accent),#00e5ff);border-radius:3px;transition:width 0.6s cubic-bezier(0.4,0,0.2,1);position:relative;">
          <div style="position:absolute;right:0;top:50%;transform:translateY(-50%);width:8px;height:8px;background:#00e5ff;border-radius:50%;box-shadow:0 0 12px rgba(0,229,255,0.5);"></div>
        </div>
      </div>
    `;
    if (this.scanForm) this.scanForm.appendChild(container);

    // Trigger animation
    requestAnimationFrame(() => {
      container.style.opacity = '1';
      container.style.transform = 'translateY(0)';
    });

    this.progressContainer = container;
    this.progressFill = document.getElementById('scan-progress-fill');
    this.progressStep = document.getElementById('scan-step');
    this.progressPercent = document.getElementById('scan-percent');
  }

  removeProgressBar() {
    if (this.progressContainer) {
      this.progressContainer.remove();
      this.progressContainer = null;
      this.progressFill = null;
      this.progressStep = null;
      this.progressPercent = null;
    }
  }

  createTokenSummary() {
    if (this.tokenSummary) return;
    const el = document.createElement('div');
    el.className = 'token-summary';
    el.id = 'token-summary';
    el.style.cssText = `
      margin-top: 1.25rem;
      padding: 1.25rem;
      background: rgba(10, 10, 18, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 12px;
      backdrop-filter: blur(10px);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 0.75rem 1.5rem;
      opacity: 0;
      transform: translateY(-8px);
      transition: opacity 0.4s ease, transform 0.4s ease;
    `;
    el.innerHTML = `
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Name</span>
        <span class="token-summary-value" id="sum-name" style="font-size:0.85rem;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Symbol</span>
        <span class="token-summary-value" id="sum-symbol" style="font-size:0.85rem;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Chain</span>
        <span class="token-summary-value" id="sum-chain" style="font-size:0.85rem;font-weight:600;color:var(--accent);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Price</span>
        <span class="token-summary-value" id="sum-price" style="font-size:0.85rem;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Liquidity</span>
        <span class="token-summary-value" id="sum-liquidity" style="font-size:0.85rem;font-weight:600;color:var(--safe);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Market Cap</span>
        <span class="token-summary-value" id="sum-mcap" style="font-size:0.85rem;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
      <div class="token-summary-row" style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0;">
        <span class="token-summary-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;">Contract</span>
        <span class="token-summary-value" id="sum-contract" style="font-size:0.8rem;font-weight:500;color:var(--text-secondary);font-family:'JetBrains Mono',monospace;">—</span>
      </div>
    `;
    if (this.scanForm) this.scanForm.appendChild(el);

    // Trigger animation
    requestAnimationFrame(() => {
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    });

    this.tokenSummary = el;
  }

  removeTokenSummary() {
    if (this.tokenSummary) {
      this.tokenSummary.remove();
      this.tokenSummary = null;
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

    // Create and show progress bar (internal HTML)
    this.createProgressBar();
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
    this.removeTokenSummary();
    this.removeProgressBar();
    this.updateProgress(0, '');
    this.currentInvestigation = { messages: [] };
  }

  endInvestigation() {
    this.isInvestigating = false;
    if (this.scanBtn) this.scanBtn.disabled = false;
    if (this.scanBtnText) this.scanBtnText.textContent = '🔍 Scan';
    this.removeProgressBar();
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
        this.createTokenSummary();
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
    el.className = 'typing-row';

    const color = this.agentColors[agent] || '#8a8a9a';
    const emoji = this.agentEmojis[agent] || '🤖';
    const agentLower = agent.toLowerCase();

    el.innerHTML = `
      <div class="typing-row-avatar ${agentLower}">
        ${emoji}
      </div>
      <div class="typing-row-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <span style="font-size:0.75rem;color:var(--text-muted);font-style:italic;letter-spacing:0.02em;">${agent} is investigating...</span>
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
    safe = safe.replace(/
/g, '<br>');

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
    const icons = { SAFE: '✅', WARNING: '⚠️', HIGH_RISK: '⚠️' };
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
