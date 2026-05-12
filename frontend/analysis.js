/**
 * 🔬 frontend/analysis.js
 * ClawIntel — Forensic Lab
 * User pastes token → Agents investigate → Chat their findings → Final verdict
 */

const CONFIG = {
  WS_URL: `ws://${window.location.host}`,
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
      Nova: '👁', Atlas: '🧪', Vega: '⚖️', Echo: '🧠', Orion: '🎯', system: '🔧'
    };

    this.init();
  }

  init() {
    this.connectWebSocket();

    // Enter key on input
    this.tokenInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.startInvestigation();
    });
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
    const chain = this.chainSelect.value;

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
    this.emptyState.style.display = 'none';

    // Update button
    this.scanBtn.disabled = true;
    this.scanBtnText.innerHTML = '<span class="spinner spinner-sm" style="display:inline-block;vertical-align:middle;margin-right:0.4rem;"></span> Scanning...';

    // Show progress
    this.progressContainer.classList.add('active');
    this.updateProgress(5, 'Initializing investigation...');
    this.investigationStatus.innerHTML = '<span class="spinner spinner-sm" style="display:inline-block;vertical-align:middle;margin-right:0.4rem;"></span> Investigating...';

    // Send to backend
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'MANUAL_INVESTIGATE',
        payload: { tokenAddress: address, chain: chain }
      }));
    } else {
      // Fallback: POST to API
      try {
        const res = await fetch('/api/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokenAddress: address, chain: chain })
        });
        if (!res.ok) throw new Error('API error');
      } catch (e) {
        console.error('[Lab] API error:', e);
        this.addSystemMessage('Failed to start investigation. Please check your connection.');
        this.endInvestigation();
        return;
      }
    }

    // Also simulate the agent conversation for demo/development
    // In production, this comes from the backend via WebSocket
    this.simulateInvestigation(address, chain);
  }

  resetInvestigation() {
    this.messagesContainer.innerHTML = '';
    this.tokenSummary.classList.remove('visible');
    this.verdictContainer.innerHTML = '';
    this.updateProgress(0, '');
    this.currentInvestigation = { messages: [] };
  }

  endInvestigation() {
    this.isInvestigating = false;
    this.scanBtn.disabled = false;
    this.scanBtnText.textContent = '🔍 Scan';
    this.progressContainer.classList.remove('active');
    this.investigationStatus.innerHTML = '<span>Investigation complete</span>';
  }

  updateProgress(percent, step) {
    this.progressFill.style.width = percent + '%';
    this.progressPercent.textContent = percent + '%';
    if (step) this.progressStep.textContent = step;
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
        // Nova found the token data
        this.updateTokenSummary(payload);
        this.updateProgress(20, 'Token data retrieved');
        break;
    }
  }

  // ── Agent Messages ──
  addAgentMessage(payload) {
    const agent = payload.agent || 'system';
    const message = payload.message || '';
    const msgType = payload.type || 'chat';

    // Hide empty state
    this.emptyState.style.display = 'none';

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

      // Process message text
      const processed = this.processMessageText(message);

      el.innerHTML = `
        <div class="agent-msg-avatar ${agent.toLowerCase()}">${emoji}</div>
        <div class="agent-msg-content">
          <div class="agent-msg-name ${agent.toLowerCase()}">${agent}</div>
          <div class="agent-msg-text">${processed}</div>
          <div class="agent-msg-time">${time}</div>
        </div>
      `;

      this.messagesContainer.appendChild(el);
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;

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

    this.messagesContainer.appendChild(el);
    this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
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

    this.tokenSummary.classList.add('visible');
  }

  // ── Verdict ──
  showVerdict(data) {
    const verdict = data.verdict || 'WARNING';
    const confidence = data.confidence || 0;
    const reasoning = data.reasoning || '';
    const factors = data.factors || {};

    const verdictClass = verdict.toLowerCase();
    const icons = { SAFE: '✅', WARNING: '⚠️', HIGH_RISK: '🚨' };
    const titles = { SAFE: 'SAFE — Approved by the Swarm', WARNING: 'WARNING — Proceed with Caution', HIGH_RISK: 'HIGH RISK — Avoid at All Costs' };

    const confidencePct = typeof confidence === 'number' ? Math.round(confidence * 100) : confidence;

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

  // ── Simulated Investigation (for demo/development) ──
  // In production, all messages come from backend agents via WebSocket
  simulateInvestigation(address, chain) {
    const shortAddr = address.slice(0, 6) + '...' + address.slice(-4);
    const chainName = chain.toUpperCase();

    // Step 1: Nova searches (2s delay)
    setTimeout(() => {
      this.updateProgress(15, 'Nova searching DexScreener...');
      this.addAgentMessage({
        agent: 'Nova',
        message: `Alright, I've got the address — ${shortAddr} on ${chainName}. Let me run this through DexScreener and see what pops up...`,
        type: 'response'
      });
    }, 800);

    setTimeout(() => {
      this.addAgentMessage({
        agent: 'Nova',
        message: `Found it. Token name is **MOONROCKET**, symbol **MOON**, deployed on ${chainName}. Liquidity sitting at around $12,500. Market cap roughly $45K. Creator wallet is 0x7a2f...9b4c — fresh address, only 2 days old. That's already a yellow flag for me.`,
        type: 'discovery'
      });
      this.updateTokenSummary({
        token_name: 'MOONROCKET',
        token_symbol: 'MOON',
        chain: chain,
        token_address: address,
        liquidity_usd: 12500,
        market_cap: 45000
      });
      this.updateProgress(25, 'Token data retrieved');
    }, 2500);

    // Step 2: Atlas simulates (4s delay)
    setTimeout(() => {
      this.updateProgress(35, 'Atlas running trade simulation...');
      this.addAgentMessage({
        agent: 'Atlas',
        message: `Copy that, Nova. Firing up the simulation on MOON now...`,
        type: 'response'
      });
    }, 3500);

    setTimeout(() => {
      this.addAgentMessage({
        agent: 'Atlas',
        message: `Okay, here's what I found. I tried to buy this token and the buy path works — no issues there. But then I tried to sell and... that's where it gets weird. The sell tax is 15%. That's highway robbery. Also, the contract has a MINT function. The dev can print more tokens anytime they want. And there's a blacklist too — they can freeze wallets at will. Liquidity is only $12.5K, which is thin. Not great, Nova.`,
        type: 'simulation_report'
      });
      this.updateProgress(50, 'Simulation complete');
    }, 5500);

    // Step 3: Vega analyzes (6s delay)
    setTimeout(() => {
      this.updateProgress(60, 'Vega conducting risk analysis...');
      this.addAgentMessage({
        agent: 'Vega',
        message: `Atlas found the mint and blacklist — good catches. Let me dig deeper into the contract...`,
        type: 'response'
      });
    }, 6500);

    setTimeout(() => {
      this.addAgentMessage({
        agent: 'Vega',
        message: `My risk score for MOON: **68/100** — that's **WARNING** level, borderline HIGH RISK. Here's why: the contract is unverified, so I can't even read the source code. The owner wallet is brand new — classic burner pattern. Top holder owns 62% of the supply. One dump and everyone's rekt. The 15% sell tax is exploitative. And that mint function? That's an inflation attack vector waiting to happen. Red flags everywhere. Echo, what do your archives say about this creator?`,
        type: 'analysis_report'
      });
      this.updateProgress(75, 'Risk analysis complete');
    }, 8500);

    // Step 4: Echo checks history (8s delay)
    setTimeout(() => {
      this.updateProgress(80, 'Echo checking creator history...');
      this.addAgentMessage({
        agent: 'Echo',
        message: `Let me pull up the historical data on this creator...`,
        type: 'response'
      });
    }, 9500);

    setTimeout(() => {
      this.addAgentMessage({
        agent: 'Echo',
        message: `Never seen this creator before — 0x7a2f...9b4c is a fresh wallet in my database. No history, no pattern, no reputation score. Could be a first-timer with big dreams, could be a burner account. Time will tell, and I'll be watching. But the fact that it's only 2 days old and already launching tokens? That's suspicious. I've started their file from scratch.`,
        type: 'memory_report'
      });
      this.updateProgress(90, 'History check complete');

      // Step 5: Orion delivers verdict (10s delay)
      setTimeout(() => {
        this.updateProgress(95, 'Orion synthesizing verdict...');
        this.addAgentMessage({
          agent: 'Orion',
          message: `I've been listening to Atlas, Vega, and Echo. Let me synthesize this...`,
          type: 'response'
        });
      }, 11000);

      setTimeout(() => {
        this.addAgentMessage({
          agent: 'Orion',
          message: `I've reviewed everything — simulation, risk analysis, creator history. My verdict is **WARNING**. The evidence is concerning at 72% confidence. Atlas found a 15% sell tax and mint functionality. Vega scored it 68/100 with multiple red flags — unverified contract, new wallet, whale-dominated supply. Echo has no historical data on the creator, which adds uncertainty. This isn't an outright scam, but enough concerns to proceed carefully. Small size, tight stops. But do your own research as well.`,
          type: 'decision'
        });

        this.showVerdict({
          verdict: 'WARNING',
          confidence: 0.72,
          reasoning: 'Atlas found 15% sell tax and mint functionality. Vega scored 68/100 with red flags: unverified contract, new wallet, whale-dominated supply. Echo has no historical data on creator. Not an outright scam, but concerning.',
          factors: {
            simulation_score: 45,
            analysis_risk: 68,
            creator_reputation: 50,
            liquidity_usd: 12500,
            honeypot: false,
            can_sell: true
          }
        });

        this.updateProgress(100, 'Investigation complete');
        this.endInvestigation();
      }, 13000);

    }, 11500);
  }

  formatNumber(num) {
    if (num >= 1_000_000_000) return (num / 1_000_000_000).toFixed(2) + 'B';
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(2) + 'K';
    return num.toString();
  }
}

const analysis = new ForensicLab();
window.analysis = analysis;

export default analysis;
