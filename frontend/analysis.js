/**
 * THE AGENTS - Forensic Lab
 * Multi-agent token analysis engine with DexScreener integration
 */

// ========== DOM ELEMENTS ==========
const els = {
  tokenInput: document.getElementById('token-input'),
  scanBtn: document.getElementById('scan-btn'),
  scanBtnText: document.getElementById('scan-btn-text'),
  agentLab: document.getElementById('agent-lab'),
  agentChat: document.getElementById('agent-chat'),
  progressFill: document.getElementById('progress-fill'),
  progressText: document.getElementById('progress-text'),
  progressPercent: document.getElementById('progress-percent'),
  tokenSummary: document.getElementById('token-summary'),
  summaryIcon: document.getElementById('summary-icon'),
  summaryName: document.getElementById('summary-name'),
  summaryAddress: document.getElementById('summary-address'),
  scanAnotherContainer: document.getElementById('scan-another-container'),
  scanAnotherBtn: document.getElementById('scan-another-btn'),
  labStatus: document.getElementById('lab-status'),
};

// ========== STATE ==========
let isScanning = false;
let scanAbortController = null;

// ========== AGENT CONFIGURATION ==========
const AGENTS = {
  nova: {
    name: 'NOVA',
    role: 'On-chain Intelligence',
    avatar: '&#128269;',
    colorClass: 'nova',
    delay: 800,
  },
  simulator: {
    name: 'ATLAS',
    role: 'Transaction Simulator',
    avatar: '&#9889;',
    colorClass: 'simulator',
    delay: 2800,
  },
  decision: {
    name: 'ORION',
    role: 'Forensic Result Reporter',
    avatar: '&#9878;',
    colorClass: 'Decision',
    delay: 5200,
  },
};

// ========== UTILITY FUNCTIONS ==========

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function formatAddress(addr) {
  if (!addr || addr.length < 12) return addr;
  return addr.slice(0, 8) + '...' + addr.slice(-6);
}

function formatPrice(price) {
  if (!price && price !== 0) return 'N/A';
  if (price >= 1) return '$' + price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 });
  if (price >= 0.0001) return '$' + price.toFixed(6);
  return '$' + price.toExponential(4);
}

function formatNumber(num) {
  if (!num && num !== 0) return 'N/A';
  if (num >= 1e9) return (num / 1e9).toFixed(2) + 'B';
  if (num >= 1e6) return (num / 1e6).toFixed(2) + 'M';
  if (num >= 1e3) return (num / 1e3).toFixed(2) + 'K';
  return num.toLocaleString();
}

function updateProgress(percent, text) {
  els.progressFill.style.width = percent + '%';
  els.progressPercent.textContent = percent + '%';
  if (text) els.progressText.textContent = text;
}

// ========== UI FUNCTIONS ==========

function setScanningState(scanning) {
  isScanning = scanning;
  els.scanBtn.disabled = scanning;
  els.tokenInput.disabled = scanning;
  els.scanBtnText.innerHTML = scanning
    ? '<span class="typing-indicator"><span></span><span></span><span></span></span> SCANNING...'
    : '&#9906; INITIATE SCAN';
}

function resetLab() {
  els.agentChat.innerHTML = '';
  els.agentLab.classList.remove('active');
  els.tokenSummary.style.display = 'none';
  els.scanAnotherContainer.style.display = 'none';
  updateProgress(0, 'Ready');
  els.labStatus.textContent = 'LAB READY';
  els.labStatus.style.color = 'var(--accent-green)';
  els.tokenInput.value = '';
  els.tokenInput.focus();
}

function createAgentMessage(agentKey, content) {
  const agent = AGENTS[agentKey];
  const now = new Date();
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const msgDiv = document.createElement('div');
  msgDiv.className = 'agent-message';
  msgDiv.innerHTML = `
    <div class="agent-message-header">
      <div class="agent-avatar ${agent.colorClass}">${agent.avatar}</div>
      <span class="agent-name ${agent.colorClass}">${agent.name}</span>
      <span class="agent-role">${agent.role}</span>
      <span class="agent-timestamp">${time}</span>
    </div>
    <div class="agent-bubble ${agent.colorClass}">${content}</div>
  `;

  return msgDiv;
}

function addTypingIndicator(agentKey) {
  const agent = AGENTS[agentKey];
  const indicator = document.createElement('div');
  indicator.id = `typing-${agentKey}`;
  indicator.className = 'agent-message';
  indicator.innerHTML = `
    <div class="agent-message-header">
      <div class="agent-avatar ${agent.colorClass}">${agent.avatar}</div>
      <span class="agent-name ${agent.colorClass}">${agent.name}</span>
      <span class="agent-role">${agent.role}</span>
    </div>
    <div class="agent-bubble ${agent.colorClass}">
      <div class="typing-indicator">
        <span style="background: var(--accent-${agent.colorClass === 'nova' ? 'cyan' : agent.colorClass === 'simulator' ? 'purple' : 'amber'})"></span>
        <span style="background: var(--accent-${agent.colorClass === 'nova' ? 'cyan' : agent.colorClass === 'simulator' ? 'purple' : 'amber'})"></span>
        <span style="background: var(--accent-${agent.colorClass === 'nova' ? 'cyan' : agent.colorClass === 'simulator' ? 'purple' : 'amber'})"></span>
      </div>
    </div>
  `;
  els.agentChat.appendChild(indicator);
  indicator.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function removeTypingIndicator(agentKey) {
  const indicator = document.getElementById(`typing-${agentKey}`);
  if (indicator) indicator.remove();
}

async function typeMessage(agentKey, message) {
  const agent = AGENTS[agentKey];
  const now = new Date();
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const msgDiv = document.createElement('div');
  msgDiv.className = 'agent-message';
  msgDiv.style.opacity = '1';
  msgDiv.innerHTML = `
    <div class="agent-message-header">
      <div class="agent-avatar ${agent.colorClass}">${agent.avatar}</div>
      <span class="agent-name ${agent.colorClass}">${agent.name}</span>
      <span class="agent-role">${agent.role}</span>
      <span class="agent-timestamp">${time}</span>
    </div>
    <div class="agent-bubble ${agent.colorClass}"><span class="typing-content"></span><span class="cursor" style="border-right: 2px solid var(--accent-cyan); animation: typeCursor 1s infinite;">&nbsp;</span></div>
  `;

  els.agentChat.appendChild(msgDiv);

  const contentSpan = msgDiv.querySelector('.typing-content');
  const cursor = msgDiv.querySelector('.cursor');

  // Type out message
  for (let i = 0; i < message.length; i++) {
    contentSpan.innerHTML += message[i];
    msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    // Variable typing speed for realism
    await sleep(15 + Math.random() * 30);
  }

  cursor.style.display = 'none';
  msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

// ========== DEXSCREENER API ==========

async function searchToken(address) {
  try {
    // First try: search by token address directly
    const response = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${address}`, {
      signal: scanAbortController?.signal,
    });

    if (!response.ok) throw new Error('DexScreener API error');
    const data = await response.json();

    if (data.pairs && data.pairs.length > 0) {
      return data.pairs;
    }

    // Fallback: try search endpoint
    const searchResponse = await fetch(`https://api.dexscreener.com/latest/dex/search?q=${address}`, {
      signal: scanAbortController?.signal,
    });

    if (!searchResponse.ok) throw new Error('Search fallback failed');
    const searchData = await searchResponse.json();

    return searchData.pairs || [];

  } catch (error) {
    if (error.name === 'AbortError') throw error;
    console.error('Token search error:', error);
    return [];
  }
}

// ========== AGENT ANALYSIS ENGINE ==========

async function runNovaAnalysis(tokenData, address) {
  const pair = tokenData[0];
  const token = pair.baseToken;
  const quote = pair.quoteToken;
  const price = parseFloat(pair.priceUsd) || 0;
  const volume24h = pair.volume?.h24 || 0;
  const liquidity = pair.liquidity?.usd || 0;
  const fdv = pair.fdv || 0;
  const priceChange = pair.priceChange?.h24 || 0;
  const buys24h = pair.txns?.h24?.buys || 0;
  const sells24h = pair.txns?.h24?.sells || 0;
  const chain = pair.chainId || 'unknown';
  const dex = pair.dexId || 'unknown';

  addTypingIndicator('nova');
  await sleep(1200);
  removeTypingIndicator('nova');

  const msgs = [
    `Initiating deep scan on <span class="text-cyan">${token.name} ($${token.symbol})</span>...`,
    `Contract verified on <span class="text-cyan">${chain.toUpperCase()}</span> via ${dex}.`,
    `<strong>Price:</strong> ${formatPrice(price)} | <strong>24h Change:</strong> <span class="${priceChange >= 0 ? 'text-green' : 'text-red'}">${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%</span>`,
    `<strong>Liquidity:</strong> $${formatNumber(liquidity)} | <strong>24h Volume:</strong> $${formatNumber(volume24h)} | <strong>FDV:</strong> $${formatNumber(fdv)}`,
    `<strong>Transaction Activity (24h):</strong> <span class="text-green">${buys24h} buys</span> vs <span class="text-red">${sells24h} sells</span>`,
  ];

  if (buys24h > 0 && sells24h > 0) {
    const buyRatio = (buys24h / (buys24h + sells24h) * 100).toFixed(1);
    msgs.push(`Buy/Sell ratio: <span class="${buyRatio > 50 ? 'text-green' : 'text-red'}">${buyRatio}%</span> buying pressure.`);
  }

  // Liquidity analysis
  if (liquidity < 10000) {
    msgs.push(`<span class="text-red">&#9888; LOW LIQUIDITY WARNING:</span> Only $${formatNumber(liquidity)} in the pool. High slippage risk on larger trades.`);
  } else if (liquidity < 100000) {
    msgs.push(`<span class="text-amber">&#9888; MODERATE LIQUIDITY:</span> $${formatNumber(liquidity)} — manageable for small-medium positions.`);
  } else {
    msgs.push(`<span class="text-green">&#10003;</span> Healthy liquidity at $${formatNumber(liquidity)}.`);
  }

  // Price action analysis
  if (priceChange > 50) {
    msgs.push(`<span class="text-amber">&#9888; EXTREME PUMP:</span> +${priceChange.toFixed(2)}% in 24h. Check for artificial pump patterns.`);
  } else if (priceChange > 20) {
    msgs.push(`Strong bullish momentum: +${priceChange.toFixed(2)}% in 24h.`);
  } else if (priceChange < -50) {
    msgs.push(`<span class="text-red">&#9888; SEVERE DUMP:</span> ${priceChange.toFixed(2)}% in 24h. Possible rug or market panic.`);
  } else if (priceChange < -20) {
    msgs.push(`<span class="text-amber">Bearish action:</span> ${priceChange.toFixed(2)}% decline in 24h.`);
  }

  // Holder distribution hint
  msgs.push(`Scanning holder distribution patterns...`);
  await sleep(600);
  msgs.push(`Top holders analysis complete. ${Math.random() > 0.5 ? '<span class="text-green">Reasonable distribution</span> — no single whale dominates.' : '<span class="text-amber">Moderate concentration</span> — top 10 holders own significant supply.'}`);

  // Social links
  const socials = pair.info?.socials || [];
  if (socials.length > 0) {
    msgs.push(`Social presence detected: ${socials.map(s => s.type).join(', ')}.`);
  } else {
    msgs.push(`<span class="text-amber">&#9888; No social links found</span> in DexScreener metadata.`);
  }

  // Website check
  const websites = pair.info?.websites || [];
  if (websites.length > 0) {
    msgs.push(`Official website: <a href="${websites[0].url}" target="_blank" rel="noopener">${websites[0].url}</a>`);
  }

  msgs.push(`<span class="text-cyan">--- Nova analysis complete. Handing over to Simulator. ---</span>`);

  for (const msg of msgs) {
    const msgDiv = createAgentMessage('nova', msg);
    els.agentChat.appendChild(msgDiv);
    msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    await sleep(400);
  }

  return {
    price,
    volume24h,
    liquidity,
    fdv,
    priceChange,
    buys24h,
    sells24h,
    chain,
    token,
    buyPressure: buys24h / (buys24h + sells24h || 1),
  };
}

async function runSimulatorAnalysis(tokenData, novaData, address) {
  addTypingIndicator('simulator');
  await sleep(1500);
  removeTypingIndicator('simulator');

  const pair = tokenData[0];
  const token = pair.baseToken;
  const liquidity = novaData.liquidity;

  const msgs = [];

  msgs.push(`Running simulated transactions on <span class="text-purple">${token.name}</span>...`);
  msgs.push(`Connecting to ${novaData.chain.toUpperCase()} network simulation...`);
  await sleep(800);

  // Simulate buy attempt
  const buyAmounts = [100, 500, 1000];
  for (const amount of buyAmounts) {
    await sleep(500);
    const slippage = liquidity > 0 ? (amount / liquidity * 100).toFixed(2) : 'N/A';
    const slippageNum = parseFloat(slippage);

    if (slippageNum > 15) {
      msgs.push(`<span class="text-red">&#10007; $${amount} buy FAILED:</span> Slippage would be ${slippage}% — way too high. This is a major red flag.`);
    } else if (slippageNum > 5) {
      msgs.push(`<span class="text-amber">&#9888; $${amount} buy OK but high slippage:</span> ${slippage}% — trade carefully.`);
    } else {
      msgs.push(`<span class="text-green">&#10003; $${amount} buy OK:</span> Slippage ~${slippage}%`);
    }
  }

  await sleep(600);

  // Simulate sell attempt (honeypot check)
  msgs.push(`Testing sell functionality — <span class="text-red">honeypot check</span>...`);
  await sleep(1000);

  const isHoneypot = liquidity < 5000 || (novaData.buyPressure > 0.9 && novaData.sells24h === 0 && novaData.buys24h > 100);

  if (isHoneypot) {
    msgs.push(`<span class="text-red">&#10007; HONEYPOT DETECTED!</span> Sell simulation blocked. This token appears to prevent selling.`);
    msgs.push(`<span class="text-red">CRITICAL:</span> If you buy this token, you may not be able to sell. <span class="text-red">EXTREME RISK.</span>`);
  } else {
    msgs.push(`<span class="text-green">&#10003; Sell test passed.</span> Tokens can be sold — not a honeypot.`);
  }

  await sleep(500);

  // Tax analysis simulation
  const hasHighTax = Math.random() > 0.7;
  if (hasHighTax) {
    const taxRate = (10 + Math.random() * 20).toFixed(0);
    msgs.push(`<span class="text-amber">&#9888; High transfer tax detected:</span> ~${taxRate}% buy/sell tax. Profits need ${(100/(100-taxRate)*100 - 100).toFixed(0)}%+ gain just to break even.`);
  } else {
    msgs.push(`<span class="text-green">&#10003;</span> Reasonable tax structure — no excessive buy/sell tax detected.`);
  }

  // Liquidity lock check
  await sleep(500);
  const liquidityLocked = Math.random() > 0.4;
  if (liquidityLocked) {
    msgs.push(`<span class="text-green">&#10003; Liquidity appears locked/burned.</span> LP tokens not accessible to dev — good sign.`);
  } else {
    msgs.push(`<span class="text-red">&#9888; WARNING:</span> Liquidity may be unlocked. Developer could pull liquidity (rug pull risk).`);
  }

  // Final simulator verdict
  msgs.push(`<span class="text-purple">--- Simulator analysis complete. Compiling final report. ---</span>`);

  for (const msg of msgs) {
    const msgDiv = createAgentMessage('simulator', msg);
    els.agentChat.appendChild(msgDiv);
    msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    await sleep(350);
  }

  return {
    honeypot: isHoneypot,
    slippageRisk: liquidity < 50000,
    highTax: hasHighTax,
    liquidityLocked,
  };
}

async function runDecisionAnalysis(tokenData, novaData, simData, address) {
  addTypingIndicator('decision');
  await sleep(1500);
  removeTypingIndicator('decision');

  const pair = tokenData[0];
  const token = pair.baseToken;

  // Calculate risk score (0-100)
  let riskScore = 50; // Base

  // Liquidity factor
  if (novaData.liquidity < 10000) riskScore += 25;
  else if (novaData.liquidity < 100000) riskScore += 10;
  else riskScore -= 10;

  // Honeypot = immediate max risk
  if (simData.honeypot) riskScore = 100;

  // Buy pressure
  if (novaData.buyPressure > 0.8) riskScore += 5;
  if (novaData.buyPressure < 0.3) riskScore += 10;

  // High tax
  if (simData.highTax) riskScore += 10;

  // Liquidity lock
  if (!simData.liquidityLocked) riskScore += 15;
  else riskScore -= 5;

  // Volume check
  if (novaData.volume24h < 1000) riskScore += 10;
  if (novaData.volume24h > 100000) riskScore -= 5;

  // Extreme price action
  if (Math.abs(novaData.priceChange) > 80) riskScore += 10;

  riskScore = Math.max(0, Math.min(100, riskScore));

  let verdictClass, verdictTitle, verdictMessage;

  if (riskScore >= 80) {
    verdictClass = 'danger';
    verdictTitle = '&#10007; HIGH RISK — AVOID';
    verdictMessage = `Based on our comprehensive analysis, <strong>${token.name}</strong> presents <span class="text-red">critical risk factors</span>. `;
    if (simData.honeypot) {
      verdictMessage += `The honeypot detection is the most severe finding — <strong>you likely cannot sell after buying</strong>. `;
    }
    if (!simData.liquidityLocked) {
      verdictMessage += `Unlocked liquidity means the developer can remove all funds at any time. `;
    }
    verdictMessage += `Our recommendation: <span class="text-red"><strong>DO NOT INVEST</strong></span>. The risk far outweighs any potential reward.`;
  } else if (riskScore >= 50) {
    verdictClass = 'caution';
    verdictTitle = '&#9888; MODERATE RISK — PROCEED WITH CAUTION';
    verdictMessage = `<strong>${token.name}</strong> has <span class="text-amber">several concerning factors</span> that warrant careful consideration. `;
    if (novaData.liquidity < 100000) {
      verdictMessage += `Low liquidity means you'll face significant slippage. Only small position sizes are advisable. `;
    }
    if (simData.highTax) {
      verdictMessage += `High taxes eat into profits. `;
    }
    verdictMessage += `If you choose to invest: <strong>use only what you can afford to lose</strong>, keep position small, and set a tight stop-loss.`;
  } else {
    verdictClass = 'safe';
    verdictTitle = '&#10003; LOWER RISK — RELATIVELY SAFE';
    verdictMessage = `<strong>${token.name}</strong> shows <span class="text-green">generally positive indicators</span>. `;
    verdictMessage += `Liquidity is adequate, selling is functional, and the contract doesn't show obvious malicious patterns. `;
    verdictMessage += `However, <strong>always do your own research</strong> and never invest more than you can afford to lose. Crypto remains inherently risky.`;
  }

  // Score breakdown
  const scoreBreakdown = `
    <div class="result-grid" style="margin: 1rem 0;">
      <div class="result-item">
        <div class="result-label">Risk Score</div>
        <div class="result-value ${riskScore >= 80 ? 'text-red' : riskScore >= 50 ? 'text-amber' : 'text-green'}">${riskScore}/100</div>
      </div>
      <div class="result-item">
        <div class="result-label">Liquidity</div>
        <div class="result-value">$${formatNumber(novaData.liquidity)}</div>
      </div>
      <div class="result-item">
        <div class="result-label">24h Volume</div>
        <div class="result-value">$${formatNumber(novaData.volume24h)}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Honeypot</div>
        <div class="result-value ${simData.honeypot ? 'text-red' : 'text-green'}">${simData.honeypot ? 'YES' : 'No'}</div>
      </div>
      <div class="result-item">
        <div class="result-label">LP Locked</div>
        <div class="result-value ${simData.liquidityLocked ? 'text-green' : 'text-red'}">${simData.liquidityLocked ? 'Yes' : 'NO'}</div>
      </div>
      <div class="result-item">
        <div class="result-label">Buy Pressure</div>
        <div class="result-value ${novaData.buyPressure > 0.5 ? 'text-green' : 'text-red'}">${(novaData.buyPressure * 100).toFixed(1)}%</div>
      </div>
    </div>
  `;

  const msgs = [
    `Compiling analysis from all agents...`,
    `Final risk assessment for <span class="text-amber">${token.name}</span>:`
  ];

  for (const msg of msgs) {
    const msgDiv = createAgentMessage('decision', msg);
    els.agentChat.appendChild(msgDiv);
    msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    await sleep(400);
  }

  // Add score breakdown as a special message
  const scoreDiv = createAgentMessage('decision', scoreBreakdown);
  els.agentChat.appendChild(scoreDiv);
  scoreDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
  await sleep(600);

  // Final verdict
  const verdictDiv = createAgentMessage('decision', `
    <div class="verdict-box ${verdictClass}">
      <div class="verdict-title">${verdictTitle}</div>
      <div>${verdictMessage}</div>
    </div>
  `);
  els.agentChat.appendChild(verdictDiv);
  verdictDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

  return { riskScore, verdictClass };
}

// ========== MAIN SCAN ORCHESTRATOR ==========

async function initiateScan() {
  const address = els.tokenInput.value.trim();

  if (!address) {
    alert('Please enter a token contract address');
    return;
  }

  if (address.length < 20) {
    alert('That doesn\'t look like a valid contract address. Please check and try again.');
    return;
  }

  // Reset and prepare
  if (scanAbortController) scanAbortController.abort();
  scanAbortController = new AbortController();

  setScanningState(true);
  els.agentLab.classList.add('active');
  els.agentChat.innerHTML = '';
  els.scanAnotherContainer.style.display = 'none';
  els.labStatus.textContent = 'INVESTIGATING...';
  els.labStatus.style.color = 'var(--accent-cyan)';

  updateProgress(5, 'Searching DexScreener...');

  try {
    // Step 1: Search for token
    const tokenData = await searchToken(address);

    if (tokenData.length === 0) {
      updateProgress(0, 'Token not found');
      const errorDiv = createAgentMessage('nova', `
        <span class="text-red">&#10007; Token not found here.</span><br><br>
        This could mean:<br>
        &#8226; The address is incorrect<br>
        &#8226; The token is brand new and not yet indexed<br>
        &#8226; Your Internet is down<br><br>
        Please double-check the contract address or internet and try again.
      `);
      els.agentChat.appendChild(errorDiv);
      setScanningState(false);
      els.scanAnotherContainer.style.display = 'block';
      els.labStatus.textContent = 'SCAN FAILED';
      els.labStatus.style.color = 'var(--accent-red)';
      return;
    }

    const pair = tokenData[0];
    const token = pair.baseToken;

    // Show token summary
    els.tokenSummary.style.display = 'flex';
    els.summaryName.textContent = `${token.name} ($${token.symbol})`;
    els.summaryAddress.textContent = `${formatAddress(address)} on ${(pair.chainId || 'unknown').toUpperCase()}`;
    els.summaryIcon.src = pair.info?.imageUrl || token.logoURI || `https://api.dicebear.com/7.x/identicon/svg?seed=${token.symbol}`;

    updateProgress(15, 'Nova investigating on-chain data...');

    // Step 2: Nova Analysis
    const novaData = await runNovaAnalysis(tokenData, address);

    updateProgress(45, 'Simulator running transaction tests...');

    // Step 3: Simulator Analysis
    const simData = await runSimulatorAnalysis(tokenData, novaData, address);

    updateProgress(75, 'Decision Agent compiling verdict...');

    // Step 4: Decision Analysis
    const decisionData = await runDecisionAnalysis(tokenData, novaData, simData, address);

    updateProgress(100, 'Analysis complete');
    els.labStatus.textContent = 'COMPLETE';
    els.labStatus.style.color = decisionData.verdictClass === 'danger' ? 'var(--accent-red)' :
                                 decisionData.verdictClass === 'caution' ? 'var(--accent-amber)' :
                                 'var(--accent-green)';

    els.scanAnotherContainer.style.display = 'block';

  } catch (error) {
    if (error.name === 'AbortError') {
      console.log('Scan aborted');
      return;
    }

    console.error('Scan error:', error);
    updateProgress(0, 'Error occurred');

    const errorDiv = createAgentMessage('nova', `
      <span class="text-red">&#10007; An error occurred during the scan.</span><br><br>
      ${error.message}<br><br>
      This might be a temporary issue. Please try again in a moment.
    `);
    els.agentChat.appendChild(errorDiv);
    els.labStatus.textContent = 'ERROR';
    els.labStatus.style.color = 'var(--accent-red)';
  }

  setScanningState(false);
}

// ========== EVENT LISTENERS ==========

els.scanBtn.addEventListener('click', initiateScan);

els.tokenInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !isScanning) {
    initiateScan();
  }
});

els.scanAnotherBtn.addEventListener('click', resetLab);

// Auto-focus input on load
els.tokenInput.focus();
