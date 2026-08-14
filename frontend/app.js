/**
 * 🧠 frontend/app.js
 * ClawIntel — Detectives Room Frontend Brain
 * WebSocket-connected live chat with agent swarm conversation
 * World-class features: particles, sound FX, command palette, typing indicators
 */

const CONFIG = {
  WS_URL: `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`,
  RECONNECT_INTERVAL: 3000,
  MAX_RECONNECT_ATTEMPTS: 10,
  TYPING_TIMEOUT: 5000,
  MESSAGE_BATCH_SIZE: 20,
  SOUND_ENABLED: true,
  PARTICLE_COUNT: 60,
  SCROLL_THRESHOLD: 100,
};

// ═══════════════════════════════════════════════════
// AUDIO ENGINE
// ═══════════════════════════════════════════════════

class AudioEngine {
  constructor() {
    this.ctx = null;
    this.enabled = localStorage.getItem('clawintel_sound') !== 'false';
    this.initialized = false;
  }

  init() {
    if (this.initialized) return;
    try {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.initialized = true;
    } catch (e) {
      console.warn('[Audio] Web Audio API not supported');
    }
  }

  play(type) {
    if (!this.enabled || !this.ctx) return;
    if (this.ctx.state === 'suspended') this.ctx.resume();

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.connect(gain);
    gain.connect(this.ctx.destination);

    switch (type) {
      case 'message':
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, now);
        osc.frequency.exponentialRampToValueAtTime(440, now + 0.1);
        gain.gain.setValueAtTime(0.03, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
        osc.start(now);
        osc.stop(now + 0.15);
        break;
      case 'connect':
        osc.type = 'sine';
        osc.frequency.setValueAtTime(523, now);
        osc.frequency.setValueAtTime(659, now + 0.1);
        osc.frequency.setValueAtTime(784, now + 0.2);
        gain.gain.setValueAtTime(0.04, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
        osc.start(now);
        osc.stop(now + 0.4);
        break;
      case 'verdict':
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(440, now);
        osc.frequency.setValueAtTime(554, now + 0.15);
        osc.frequency.setValueAtTime(659, now + 0.3);
        gain.gain.setValueAtTime(0.05, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
        osc.start(now);
        osc.stop(now + 0.5);
        break;
      case 'alert':
        osc.type = 'square';
        osc.frequency.setValueAtTime(200, now);
        osc.frequency.setValueAtTime(150, now + 0.1);
        gain.gain.setValueAtTime(0.03, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
        osc.start(now);
        osc.stop(now + 0.2);
        break;
    }
  }

  toggle() {
    this.enabled = !this.enabled;
    localStorage.setItem('clawintel_sound', this.enabled);
    return this.enabled;
  }
}

// ═══════════════════════════════════════════════════
// PARTICLE BACKGROUND
// ═══════════════════════════════════════════════════

class ParticleSystem {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.mouse = { x: null, y: null };
    this.running = false;
    this.resize();
    this.init();
    window.addEventListener('resize', () => this.resize());
    window.addEventListener('mousemove', (e) => {
      this.mouse.x = e.clientX;
      this.mouse.y = e.clientY;
    });
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  init() {
    this.particles = [];
    for (let i = 0; i < CONFIG.PARTICLE_COUNT; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        size: Math.random() * 2 + 0.5,
        opacity: Math.random() * 0.3 + 0.1,
        color: this.randomColor(),
      });
    }
  }

  randomColor() {
    const colors = ['#00e5ff', '#00c853', '#d500f9', '#ffd600', '#ff1744'];
    return colors[Math.floor(Math.random() * colors.length)];
  }

  start() {
    this.running = true;
    this.animate();
  }

  stop() {
    this.running = false;
  }

  animate() {
    if (!this.running) return;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    for (const p of this.particles) {
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

      // Mouse interaction
      if (this.mouse.x !== null) {
        const dx = this.mouse.x - p.x;
        const dy = this.mouse.y - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 150) {
          p.vx += dx * 0.0001;
          p.vy += dy * 0.0001;
        }
      }

      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      this.ctx.fillStyle = p.color;
      this.ctx.globalAlpha = p.opacity;
      this.ctx.fill();
    }

    // Draw connections
    this.ctx.globalAlpha = 0.05;
    this.ctx.strokeStyle = '#00e5ff';
    this.ctx.lineWidth = 0.5;
    for (let i = 0; i < this.particles.length; i++) {
      for (let j = i + 1; j < this.particles.length; j++) {
        const dx = this.particles[i].x - this.particles[j].x;
        const dy = this.particles[i].y - this.particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          this.ctx.beginPath();
          this.ctx.moveTo(this.particles[i].x, this.particles[i].y);
          this.ctx.lineTo(this.particles[j].x, this.particles[j].y);
          this.ctx.stroke();
        }
      }
    }
    this.ctx.globalAlpha = 1;

    requestAnimationFrame(() => this.animate());
  }
}

// ═══════════════════════════════════════════════════
// TOAST SYSTEM
// ═══════════════════════════════════════════════════

class ToastSystem {
  constructor(container) {
    this.container = container;
  }

  show(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = 'toast';

    const icons = {
      info: 'ℹ️',
      success: '✅',
      warning: '⚠️',
      error: '❌',
      connect: '🔌',
    };

    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || icons.info}</span>
      <span>${message}</span>
    `;

    this.container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('out');
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }
}

// ═══════════════════════════════════════════════════
// COMMAND PALETTE
// ═══════════════════════════════════════════════════

class CommandPalette {
  constructor() {
    this.overlay = document.getElementById('palette-overlay');
    this.palette = document.getElementById('command-palette');
    this.input = document.getElementById('palette-input');
    this.results = document.getElementById('palette-results');
    this.isOpen = false;
    this.commands = [
      { id: 'goto-markets', label: '📊 Go to Markets', action: () => window.location.href = 'frontend/markets.html' },
      { id: 'goto-analysis', label: '🔬 Go to Analysis', action: () => window.location.href = 'frontend/analysis.html' },
      { id: 'clear-chat', label: '🗑️ Clear Chat', action: () => app.clearChat() },
      { id: 'toggle-sound', label: '🔊 Toggle Sound', action: () => app.toggleSound() },
      { id: 'scroll-bottom', label: '⬇️ Scroll to Bottom', action: () => app.scrollToBottom(true) },
      { id: 'copy-last', label: '📋 Copy Last Message', action: () => app.copyLastMessage() },
    ];

    this.input.addEventListener('input', () => this.filter());
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.close();
      if (e.key === 'Enter') this.executeFirst();
    });
    this.overlay.addEventListener('click', () => this.close());
  }

  open() {
    this.isOpen = true;
    this.overlay.classList.add('open');
    this.palette.classList.add('open');
    this.input.value = '';
    this.input.focus();
    this.render(this.commands);
  }

  close() {
    this.isOpen = false;
    this.overlay.classList.remove('open');
    this.palette.classList.remove('open');
    this.input.blur();
  }

  filter() {
    const query = this.input.value.toLowerCase();
    const filtered = this.commands.filter(c => c.label.toLowerCase().includes(query));
    this.render(filtered);
  }

  render(items) {
    this.results.innerHTML = items.map((cmd, i) => `
      <div class="palette-item" data-index="${i}" onclick="app.palette.execute('${cmd.id}')"
           style="padding:0.75rem 1.25rem; cursor:pointer; display:flex; align-items:center; gap:0.75rem;
                  font-size:0.9rem; color:var(--text-primary); transition:background 0.15s;
                  ${i === 0 ? 'background:rgba(0,229,255,0.05);' : ''}"
           onmouseover="this.style.background='rgba(0,229,255,0.05)'"
           onmouseout="this.style.background='${i === 0 ? 'rgba(0,229,255,0.05)' : 'transparent'}'">
        <span style="font-size:1.1rem;">${cmd.label.split(' ')[0]}</span>
        <span>${cmd.label.substring(cmd.label.indexOf(' ') + 1)}</span>
      </div>
    `).join('');

    if (items.length === 0) {
      this.results.innerHTML = '<div style="padding:1rem; text-align:center; color:var(--text-muted); font-size:0.85rem;">No commands found</div>';
    }
  }

  execute(id) {
    const cmd = this.commands.find(c => c.id === id);
    if (cmd) {
      cmd.action();
      this.close();
    }
  }

  executeFirst() {
    const first = this.results.querySelector('.palette-item');
    if (first) {
      const id = this.commands.find(c => 
        first.textContent.includes(c.label.substring(c.label.indexOf(' ') + 1))
      )?.id;
      if (id) this.execute(id);
    }
  }
}

// ═══════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════

class ClawIntelApp {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.reconnectTimer = null;
    this.audio = new AudioEngine();
    this.toast = new ToastSystem(document.getElementById('toast-container'));
    this.palette = new CommandPalette();
    this.particles = new ParticleSystem(document.getElementById('particle-canvas'));
    this.chatContainer = document.getElementById('chat-container');
    this.messageInput = document.getElementById('message-input');
    this.emptyState = document.getElementById('empty-state');
    this.scrollBtn = document.getElementById('scroll-bottom');
    this.unreadCount = document.getElementById('unread-count');
    this.connectionStatus = document.getElementById('connection-status');
    this.connectionText = document.getElementById('connection-text');

    this.typingTimers = {};
    this.unreadMessages = 0;
    this.isScrolledToBottom = true;
    this.messages = [];
    this.stats = { tokens: 0, scanned: 0, safe: 0, risk: 0 };

    this.agentColors = {
      Nova: '#00e5ff',
      Atlas: '#00c853',
      Vega: '#d500f9',
      Echo: '#ffd600',
      Orion: '#ff1744',
      system: '#8a8a9a',
    };

    this.agentEmojis = {
      Nova: 'N',
      Atlas: 'A',
      Vega: 'V',
      Echo: 'E',
      Orion: 'O',
      system: 'S',
    };

    this.init();
  }

  init() {
    // Boot sequence
    this.runBootSequence();

    // Start particle background
    this.particles.start();

    // Setup WebSocket
    this.connectWebSocket();

    // Setup event listeners
    this.setupEventListeners();

    // Setup scroll tracking
    this.chatContainer.addEventListener('scroll', () => this.onScroll());

    // Update sound UI
    this.updateSoundUI();

    // Fetch chat history
    this.fetchHistory();
  }

  // ── Boot Sequence ──
  runBootSequence() {
    const bootScreen = document.getElementById('boot-screen');
    const app = document.getElementById('app');

    setTimeout(() => {
      bootScreen.classList.add('done');
      app.classList.add('ready');
      this.audio.init();
      this.audio.play('connect');
    }, 2500);
  }

  // ── WebSocket ──
  connectWebSocket() {
    this.setConnectionStatus('connecting');

    try {
      this.ws = new WebSocket(CONFIG.WS_URL);

      this.ws.onopen = () => {
        console.log('[WS] Connected');
        this.reconnectAttempts = 0;
        this.setConnectionStatus('online');
        this.toast.show('Connected to ClawIntel', 'connect');
        this.audio.play('connect');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };

      this.ws.onclose = () => {
        console.log('[WS] Disconnected');
        this.setConnectionStatus('offline');
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        this.setConnectionStatus('offline');
      };
    } catch (e) {
      console.error('[WS] Connection failed:', e);
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectAttempts >= CONFIG.MAX_RECONNECT_ATTEMPTS) {
      this.toast.show('Connection lost. Please refresh the page.', 'error', 8000);
      return;
    }

    this.reconnectAttempts++;
    const delay = Math.min(CONFIG.RECONNECT_INTERVAL * this.reconnectAttempts, 30000);

    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    this.reconnectTimer = setTimeout(() => {
      this.connectWebSocket();
    }, delay);
  }

  setConnectionStatus(status) {
    this.connectionStatus.className = 'live-indicator ' + status;
    const texts = { online: 'Live', offline: 'Offline', connecting: 'Connecting...' };
    this.connectionText.textContent = texts[status] || status;
  }

  // ── Message Handling ──
  handleMessage(data) {
    const { type, payload } = data;

    switch (type) {
      case 'AGENT_MESSAGE':
        this.renderAgentMessage(payload);
        this.audio.play('message');
        break;
      case 'CHAT_HISTORY':
        this.renderHistory(payload);
        break;
      case 'SYSTEM':
        this.renderSystemMessage(payload.message);
        break;
      case 'NEW_TOKEN':
        this.stats.tokens++;
        this.stats.scanned++;
        this.updateStats();
        break;
      case 'SIGNAL':
        this.handleSignal(payload);
        break;
      case 'TOKEN_VERIFIED':
        this.stats.safe++;
        this.updateStats();
        this.audio.play('verdict');
        break;
      case 'MARKET_UPDATE':
        // Handled by markets.html
        break;
      case 'PONG':
        // Heartbeat response
        break;
      // v4.0: Agent working spinners
      case 'AGENT_WORKING':
        this.renderAgentWorking(payload);
        break;
      case 'SIMULATION_COMPLETE':
        this.hideAgentWorking('Atlas');
        break;
      case 'ANALYSIS_COMPLETE':
        this.hideAgentWorking('Vega');
        break;
      case 'MEMORY_INTELLIGENCE':
        this.hideAgentWorking('Echo');
        break;
      case 'DECISION_COMPLETE':
        this.hideAgentWorking('Orion');
        break;
      default:
        console.log('[WS] Unknown type:', type);
    }
  }

  handleSignal(payload) {
    if (payload.verdict === 'HIGH_RISK') {
      this.stats.risk++;
      this.updateStats();
      this.audio.play('alert');
    }
  }

  // ── Rendering ──
  renderAgentMessage(payload) {
    if (this.emptyState) {
      this.emptyState.style.display = 'none';
    }

    const agent = payload.agent || 'system';
    const message = payload.message || '';
    const msgType = payload.type || 'chat';
    const timestamp = payload.timestamp || Date.now() / 1000;

    // Track unread
    if (!this.isScrolledToBottom) {
      this.unreadMessages++;
      this.updateUnreadBadge();
    }

    // Show typing indicator before message (simulated)
    this.showTyping(agent);

    // Delay message render slightly for natural feel
    const delay = msgType === 'response' ? 800 : 200;

    setTimeout(() => {
      this.hideTyping(agent);

      const el = document.createElement('div');
      el.className = 'message';
      el.dataset.agent = agent;
      el.dataset.type = msgType;

      const timeStr = this.formatTime(timestamp);
      const color = this.agentColors[agent] || '#8a8a9a';
      const emoji = this.agentEmojis[agent] || '🤖';

      // Process message text (highlight verdicts, token addresses)
      const processedMessage = this.processMessageText(message);

      el.innerHTML = `
        <div class="message-avatar ${agent.toLowerCase()}">${emoji}</div>
        <div class="message-content">
          <div class="message-header">
            <span class="message-author ${agent.toLowerCase()}" style="color:${color}">${agent}</span>
            <span class="message-time">${timeStr}</span>
          </div>
          <div class="message-body">${processedMessage}</div>
        </div>
      `;

      this.chatContainer.appendChild(el);
      this.messages.push(payload);

      // Auto-scroll if at bottom
      if (this.isScrolledToBottom) {
        this.scrollToBottom();
      }

      // Animate in
      requestAnimationFrame(() => {
        el.style.animationDelay = '0s';
      });

    }, delay);
  }

  renderSystemMessage(message) {
    if (this.emptyState) this.emptyState.style.display = 'none';

    const el = document.createElement('div');
    el.className = 'message';
    el.innerHTML = `
      <div class="message-avatar system">🔧</div>
      <div class="message-content">
        <div class="message-header">
          <span class="message-author" style="color:var(--text-muted)">System</span>
          <span class="message-time">${this.formatTime(Date.now() / 1000)}</span>
        </div>
        <div class="message-body" style="color:var(--text-secondary); font-style:italic;">${message}</div>
      </div>
    `;
    this.chatContainer.appendChild(el);
    if (this.isScrolledToBottom) this.scrollToBottom();
  }

  renderHistory(history) {
    if (!history || history.length === 0) return;

    // Clear existing
    this.chatContainer.innerHTML = '';
    this.messages = [];

    // Add date divider
    this.addDateDivider('Earlier today');

    history.forEach(msg => {
      this.renderAgentMessage(msg);
    });

    this.scrollToBottom(true);
  }

  addDateDivider(label) {
    const div = document.createElement('div');
    div.className = 'chat-date-divider';
    div.textContent = label;
    this.chatContainer.appendChild(div);
  }

  processMessageText(text) {
    if (!text) return '';

    // Escape HTML
    let safe = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Highlight verdicts
    safe = safe.replace(/\*\*SAFE\*\*/g, '<span class="verdict-badge safe">✅ SAFE</span>');
    safe = safe.replace(/\*\*WARNING\*\*/g, '<span class="verdict-badge warning">⚠️ WARNING</span>');
    safe = safe.replace(/\*\*HIGH RISK\*\*/g, '<span class="verdict-badge danger">🚨 HIGH RISK</span>');
    safe = safe.replace(/\*\*AVOID\*\*/g, '<span class="verdict-badge danger">⛔ AVOID</span>');

    // Highlight token addresses
    safe = safe.replace(/(0x[a-fA-F0-9]{40})/g, '<code style="background:rgba(0,229,255,0.1); color:var(--nova); padding:0.1rem 0.3rem; border-radius:3px; font-family:var(--font-mono); font-size:0.8rem; cursor:pointer;" onclick="app.showTokenPopup(\'$1\', event)">$1</code>');

    // Convert newlines to <br>
    safe = safe.replace(/\n/g, '<br>');

    return safe;
  }

  // ── Typing Indicators ──
  showTyping(agent) {
    const card = document.getElementById(`agent-${agent.toLowerCase()}`);
    if (card) {
      card.classList.add('typing');
      const status = card.querySelector('.agent-status');
      if (status) status.classList.add('typing');
    }

    // Clear existing timer
    if (this.typingTimers[agent]) {
      clearTimeout(this.typingTimers[agent]);
    }

    // Auto-hide after timeout
    this.typingTimers[agent] = setTimeout(() => {
      this.hideTyping(agent);
    }, CONFIG.TYPING_TIMEOUT);
  }

  hideTyping(agent) {
    const card = document.getElementById(`agent-${agent.toLowerCase()}`);
    if (card) {
      card.classList.remove('typing');
      const status = card.querySelector('.agent-status');
      if (status) status.classList.remove('typing');
    }
    if (this.typingTimers[agent]) {
      clearTimeout(this.typingTimers[agent]);
      delete this.typingTimers[agent];
    }
  }

  // ── v4.0: Agent Working Spinner Cards ──
  renderAgentWorking(payload) {
    const agent = payload.agent || 'system';
    const token = payload.token || '???';
    const action = payload.action || 'working...';
    const chain = payload.chain || '';

    // Remove existing working card for this agent
    this.hideAgentWorking(agent);

    if (this.emptyState) {
      this.emptyState.style.display = 'none';
    }

    const el = document.createElement('div');
    el.className = 'agent-working-card';
    el.dataset.workingAgent = agent;

    const color = this.agentColors[agent] || '#8a8a9a';
    const emoji = this.agentEmojis[agent] || '🤖';
    const chainLabel = chain ? ` on ${chain.toUpperCase()}` : '';

    el.innerHTML = `
      <div class="working-avatar" style="background: ${color};">${emoji}</div>
      <div class="working-text">
        <div class="working-agent">${agent}${chainLabel}</div>
        <div class="working-action">${action} ${token}...</div>
      </div>
      <div class="working-spinner"></div>
    `;

    this.chatContainer.appendChild(el);

    if (this.isScrolledToBottom) {
      this.scrollToBottom();
    }
  }

  hideAgentWorking(agent) {
    const cards = this.chatContainer.querySelectorAll(`[data-working-agent="${agent}"]`);
    cards.forEach(card => {
      card.classList.add('fade-out');
      setTimeout(() => card.remove(), 400);
    });
  }

  // ── Scroll Management ──
  onScroll() {
    const { scrollTop, scrollHeight, clientHeight } = this.chatContainer;
    this.isScrolledToBottom = scrollHeight - scrollTop - clientHeight < CONFIG.SCROLL_THRESHOLD;

    if (this.isScrolledToBottom) {
      this.unreadMessages = 0;
      this.updateUnreadBadge();
      this.scrollBtn.classList.remove('visible');
    } else {
      this.scrollBtn.classList.add('visible');
    }
  }

  scrollToBottom(instant = false) {
    if (instant) {
      this.chatContainer.scrollTop = this.chatContainer.scrollHeight;
    } else {
      this.chatContainer.scrollTo({
        top: this.chatContainer.scrollHeight,
        behavior: 'smooth'
      });
    }
    this.unreadMessages = 0;
    this.updateUnreadBadge();
    this.scrollBtn.classList.remove('visible');
  }

  updateUnreadBadge() {
    if (this.unreadMessages > 0) {
      this.unreadCount.style.display = 'flex';
      this.unreadCount.textContent = this.unreadMessages > 99 ? '99+' : this.unreadMessages;
    } else {
      this.unreadCount.style.display = 'none';
    }
  }

  // ── Stats ──
  updateStats() {
    document.getElementById('stat-tokens').textContent = this.stats.tokens;
    document.getElementById('stat-scanned').textContent = this.stats.scanned;
    document.getElementById('stat-safe').textContent = this.stats.safe;
    document.getElementById('stat-risk').textContent = this.stats.risk;
  }

  // v4.0: Fetch live stats from server
  async fetchStats() {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) {
        const data = await res.json();
        if (data.tokens_scanned !== undefined) {
          this.stats.tokens = data.tokens_scanned;
        }
        if (data.investigations_completed !== undefined) {
          this.stats.scanned = data.investigations_completed;
        }
        if (data.safe_count !== undefined) {
          this.stats.safe = data.safe_count;
        }
        if (data.risk_count !== undefined) {
          this.stats.risk = data.risk_count;
        }
        this.updateStats();
      }
    } catch (e) {
      // Silently fail — stats are decorative
    }
  }

  // ── Token Popup ──
  showTokenPopup(address, event) {
    event.stopPropagation();
    const popup = document.getElementById('token-popup');
    popup.innerHTML = `
      <div style="font-family:var(--font-mono); font-size:0.75rem; color:var(--text-muted); margin-bottom:0.5rem;">Token Address</div>
      <div style="font-family:var(--font-mono); font-size:0.8rem; color:var(--nova); word-break:break-all; margin-bottom:0.75rem;">${address}</div>
      <div style="display:flex; gap:0.5rem;">
        <button onclick="window.open('https://dexscreener.com/search?q=${address}', '_blank')"
                style="flex:1; padding:0.4rem; background:rgba(0,229,255,0.1); border:1px solid rgba(0,229,255,0.2); border-radius:4px; color:var(--nova); font-size:0.75rem; cursor:pointer;">DexScreener</button>
        <button onclick="navigator.clipboard.writeText('${address}')"
                style="flex:1; padding:0.4rem; background:var(--bg-tertiary); border:1px solid var(--border-color); border-radius:4px; color:var(--text-secondary); font-size:0.75rem; cursor:pointer;">Copy</button>
      </div>
    `;
    popup.classList.add('open');
    popup.style.left = `${Math.min(event.clientX, window.innerWidth - 260)}px`;
    popup.style.top = `${Math.min(event.clientY + 20, window.innerHeight - 150)}px`;

    const closePopup = () => {
      popup.classList.remove('open');
      document.removeEventListener('click', closePopup);
    };
    setTimeout(() => document.addEventListener('click', closePopup), 10);
  }

  // ── User Input ──
  sendMessage() {
    const text = this.messageInput.value.trim();
    if (!text) return;

    if (text.startsWith('/')) {
      this.handleCommand(text);
    } else {
      // Send to server (for manual investigation or chat)
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'CHAT_MESSAGE',
          payload: { message: text, timestamp: Date.now() }
        }));
      }

      // Show locally
      this.renderSystemMessage(`You: ${text}`);
    }

    this.messageInput.value = '';
  }

  handleCommand(text) {
    const cmd = text.slice(1).trim().toLowerCase();

    switch (cmd) {
      case 'clear':
        this.clearChat();
        break;
      case 'sound':
        this.toggleSound();
        break;
      case 'help':
        this.renderSystemMessage('Commands: /clear, /sound, /help');
        break;
      default:
        this.renderSystemMessage(`Unknown command: /${cmd}. Type /help for available commands.`);
    }
  }

  // ── Actions ──
  clearChat() {
    this.chatContainer.innerHTML = '';
    this.messages = [];
    this.emptyState.style.display = 'flex';
    this.toast.show('Chat cleared', 'info');
  }

  toggleSound() {
    const enabled = this.audio.toggle();
    this.updateSoundUI();
    this.toast.show(`Sound FX ${enabled ? 'enabled' : 'disabled'}`, 'info');
  }

  updateSoundUI() {
    const icon = document.getElementById('sound-icon');
    const status = document.getElementById('sound-status');
    if (icon && status) {
      icon.textContent = this.audio.enabled ? '🔊' : '🔇';
      status.textContent = this.audio.enabled ? 'Enabled' : 'Muted';
    }
  }

  copyLastMessage() {
    if (this.messages.length === 0) return;
    const last = this.messages[this.messages.length - 1];
    const text = `${last.agent}: ${last.message}`;
    navigator.clipboard.writeText(text).then(() => {
      this.toast.show('Copied to clipboard', 'success');
    });
  }

  // ── Event Listeners ──
  setupEventListeners() {
    // Input
    this.messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
      if (e.key === 'Escape') {
        this.palette.close();
      }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Ctrl+K or Cmd+K
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        this.palette.open();
      }
      // / to focus input
      if (e.key === '/' && document.activeElement !== this.messageInput && !this.palette.isOpen) {
        e.preventDefault();
        this.messageInput.focus();
      }
      // Escape
      if (e.key === 'Escape') {
        this.palette.close();
        this.messageInput.blur();
      }
    });

    // Heartbeat
    setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'PING', payload: {} }));
      }
    }, 30000);

    // v4.0: Periodic stats refresh
    setInterval(() => {
      this.fetchStats();
    }, 10000);

    // Visibility change
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && this.ws && this.ws.readyState === WebSocket.CLOSED) {
        this.connectWebSocket();
      }
    });
  }

  // ── Utilities ──
  formatTime(timestamp) {
    const now = Date.now() / 1000;
    const diff = now - timestamp;

    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;

    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  async fetchHistory() {
    try {
      const res = await fetch('/api/chat/history?limit=50');
      if (res.ok) {
        const data = await res.json();
        if (data.history && data.history.length > 0) {
          this.renderHistory(data.history);
        }
      }
    } catch (e) {
      console.warn('[App] Failed to fetch history:', e);
    }
  }
}

// ═══════════════════════════════════════════════════
// INITIALIZE
// ═══════════════════════════════════════════════════

const app = new ClawIntelApp();
window.app = app; // Expose for onclick handlers

export default app;
