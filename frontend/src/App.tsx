import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowUpRight, Bot, Check, CheckCircle2, ChevronRight, CircleAlert, Clock3, Database, Menu, MessageCircle, Play, Search, Send, Settings, ShieldCheck, Sparkles, WalletCards, X, Zap } from 'lucide-react'
import { api, type EvidenceRecord, type Message, type Portfolio, type Quote, type Investigation } from './api'

const agentTint: Record<string, string> = { nova: 'violet', atlas: 'teal', vega: 'rose', echo: 'amber', orion: 'blue', makto: 'green', human: 'white' }
const agentNames: Record<string, string> = { nova: 'Nova', atlas: 'Atlas', vega: 'Vega', echo: 'Echo', orion: 'Orion', makto: 'Makto', human: 'You' }

export default function App() {
  const [ready, setReady] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const queryClient = useQueryClient()
  const location = useLocation()
  useEffect(() => { void api.session().then(() => setReady(true)).catch(() => setReady(true)) }, [])
  const health = useQuery({queryKey:['health'], queryFn:api.health, refetchInterval:30_000, retry:1})
  useEffect(() => {
    if (!ready) return
    const room = location.pathname.startsWith('/trading') ? 'trading' : location.pathname.startsWith('/war-room') ? 'autonomous' : null
    if (!room) return
    let socket: WebSocket | undefined
    let retryTimer: number | undefined
    let retryDelay = 500
    let stopped = false
    const connect = () => {
      if (stopped) return
      socket = new WebSocket(`${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/${room}`)
      socket.onopen = () => { retryDelay = 500 }
      socket.onmessage = () => { void queryClient.invalidateQueries({ queryKey: [room === 'trading' ? 'trading-messages' : 'warroom-messages'] }) }
      socket.onclose = () => {
        if (stopped) return
        retryTimer = window.setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 15_000)
      }
      socket.onerror = () => socket?.close()
    }
    connect()
    return () => { stopped = true; if (retryTimer) window.clearTimeout(retryTimer); socket?.close() }
  }, [ready, location.pathname, queryClient])
  const wallet = useQuery({ queryKey: ['wallet'], queryFn: api.wallet, enabled: ready, retry: false })
  const connect = useMutation({ mutationFn: api.connect, onSuccess: (data) => queryClient.setQueryData(['wallet'], data) })
  const disconnect = useMutation({ mutationFn: api.disconnect, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['wallet'] }); void queryClient.invalidateQueries({ queryKey: ['trading-messages'] }) } })
  const title = useMemo(() => ({ '/war-room': 'Autonomous War Room', '/trading': 'Interactive Trading Room', '/investigations': 'Investigations', '/portfolio': 'Portfolio', '/settings': 'Settings & system' }[location.pathname] ?? 'Autonomous War Room'), [location.pathname])

  return <div className="app-shell">
    <aside className={`sidebar ${navOpen ? 'open' : ''}`}>
      <Link to="/war-room" className="brand" onClick={() => setNavOpen(false)}><div className="brand-mark"><Activity size={20}/></div><span>claw<span className="brand-accent">intel</span></span><span className="brand-version">01</span></Link>
      <div className="workspace-label">INTELLIGENCE FLOOR</div>
      <nav className="nav-list" aria-label="Main navigation">
        <NavLink to="/war-room" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><ShieldCheck size={17}/><span>War Room</span><span className="live-dot"/></NavLink>
        <NavLink to="/trading" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><MessageCircle size={17}/><span>Trading Room</span></NavLink>
        <div className="nav-caption">YOUR WORKSPACE</div>
        <NavLink to="/investigations" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><Database size={17}/><span>Investigations</span></NavLink>
        <NavLink to="/portfolio" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><WalletCards size={17}/><span>Portfolio</span></NavLink>
        <NavLink to="/settings" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><Settings size={17}/><span>Settings</span></NavLink>
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-status"><span className="status-icon"><Zap size={14}/></span><div><b>Demo environment</b><small>Simulated wallet · no real funds</small></div></div>
        <div className="user-chip"><div className="user-avatar">CI</div><div><b>Observer</b><small>Local workspace</small></div><ChevronRight size={15}/></div>
      </div>
    </aside>
    {navOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)}/>}
    <main className="main-area">
      <header className="topbar"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setNavOpen(true)}><Menu size={19}/></button><div className="breadcrumb"><span>ClawIntel</span><ChevronRight size={14}/><b>{title}</b></div><div className="topbar-right"><span className={`system-state ${health.data?.status === 'ok' ? '' : health.isLoading ? 'checking' : 'offline'}`}><i/>{health.data?.status === 'ok' ? 'API + DATABASE ONLINE' : health.isLoading ? 'CHECKING SYSTEM' : 'SYSTEM UNAVAILABLE'}</span><div className="topbar-divider"/>{wallet.data?.connected ? <button className="wallet-pill connected" onClick={() => disconnect.mutate()} title="Disconnect demo wallet"><span className="wallet-orb"/><span>{wallet.data.address?.slice(0, 14)}…</span><X size={13}/></button> : <button className="wallet-pill" onClick={() => connect.mutate()} title="Connect the simulated NEAR wallet"><WalletCards size={15}/><span>Connect demo wallet</span></button>}{(connect.error || disconnect.error) && <span className="topbar-error" role="status">{(connect.error || disconnect.error)?.message}</span>}</div></header>
      <Routes>
        <Route path="/" element={<WarRoom/>}/><Route path="/war-room" element={<WarRoom/>}/>
        <Route path="/trading" element={<TradingRoom wallet={wallet.data} walletLoading={wallet.isLoading} connect={connect.mutate} connecting={connect.isPending} connectError={connect.error?.message}/>}/>
        <Route path="/investigations" element={<Investigations/>}/><Route path="/portfolio" element={<PortfolioPage wallet={wallet.data} connect={connect.mutate}/>}/><Route path="/settings" element={<SettingsPage/>}/>
      </Routes>
      <footer className="app-footer"><span><i/> All systems monitored</span><span>CLAWINTEL · INTELLIGENCE, WITH EVIDENCE</span><span>DEMO BUILD 01</span></footer>
    </main>
  </div>
}

function PageHeading({eyebrow, title, children, right}: {eyebrow: string; title: string; children: string; right?: ReactNode}) {
  return <div className="page-heading"><div><div className="eyebrow"><span/>{eyebrow}</div><h1>{title}</h1><p>{children}</p></div>{right && <div className="heading-right">{right}</div>}</div>
}

function AgentStrip({room}: {room: 'autonomous'|'trading'}) {
  const query = useQuery({queryKey: ['agents', room], queryFn: () => api.agents(room)})
  const agents = (query.data?.agents ?? []).filter(agent => room === 'autonomous' ? agent.id !== 'makto' : true)
  return <div className="agent-strip"><div className="agent-strip-title"><span className="tiny-label">YOUR INTELLIGENCE TEAM</span><span className="agent-count">{agents.length} ACTIVE IDENTITIES</span></div><div className="agent-list">{agents.map((agent) => <div className="agent-chip" key={agent.id} title={`${agent.role} · ${agent.tokens_analyzed} crypto assets analyzed · ${agent.llm_tokens} LLM tokens used · ${agent.investigations} investigations · ${agent.active_investigations} active`}><span className={`agent-avatar ${agentTint[agent.id]}`}>{agent.name.slice(0,1)}</span><span>{agent.name}</span></div>)}</div></div>
}

function ErrorCard({message}: {message: string}) { return <div className="error-card"><CircleAlert size={18}/><span>{message}</span></div> }

function MessageList({messages, loading, error, simulated = false, roundtable = false}: {messages?: Message[]; loading: boolean; error?: Error | null; simulated?: boolean; roundtable?: boolean}) {
  if (loading) return <div className="empty-state"><div className="loading-orbit"/><span>Connecting to the intelligence feed…</span></div>
  if (error) return <ErrorCard message={error.message}/>
  if (!messages?.length) return <div className="empty-state"><div className="empty-icon"><Bot size={22}/></div><b>No conversation yet</b><span>Agent activity will appear here as the system investigates.</span></div>
  return <div className="message-list">{messages.map((message) => <article className={`message-row ${message.agent_id === 'human' ? 'human-row' : ''}`} key={message.id}>
    <div className={`message-avatar ${agentTint[message.agent_id] ?? 'blue'}`}>{message.agent_id === 'human' ? 'Y' : (agentNames[message.agent_id] ?? message.agent_id).slice(0,1)}</div>
    <div className="message-body"><div className="message-meta"><b>{agentNames[message.agent_id] ?? message.agent_id}</b>{roundtable && message.agent_id !== 'human' && <span className="decision-tag">ROUND TABLE</span>}{!roundtable && message.agent_id === 'orion' && <span className="decision-tag">DECISION</span>}{(simulated || message.simulated) && <span className="sim-tag">SIMULATED</span>}<time>{new Date(message.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</time></div><p>{message.content}</p></div>
  </article>)}</div>
}

function WarRoom() {
  const query = useQuery({queryKey: ['warroom-messages'], queryFn: () => api.messages('autonomous'), refetchInterval: 12_000})
  const run = useMutation({mutationFn: (id: string) => api.runScenario(id), onSuccess: () => { void query.refetch() }})
  return <div className="page-content"><PageHeading eyebrow="AUTONOMOUS DEPARTMENT · READ ONLY" title="War Room">Five independent analysts monitor, investigate and challenge market signals. Watch the evidence move through the team.</PageHeading><AgentStrip room="autonomous"/>
    <div className="war-grid"><section className="panel conversation-panel"><div className="panel-header"><div><span className="panel-title">Live intelligence feed</span><span className="panel-subtitle">Autonomous agent conversation</span></div><span className="feed-live"><i/> LIVE</span></div><div className="feed-scroll"><MessageList messages={query.data?.messages} loading={query.isLoading} error={query.error}/></div><div className="readonly-note"><ShieldCheck size={15}/><span>Observer access · War Room is read-only</span></div></section>
    <aside className="right-rail"><div className="panel agents-panel"><div className="panel-header"><div><span className="panel-title">The team</span><span className="panel-subtitle">Independent perspectives</span></div><span className="icon-frame"><Bot size={16}/></span></div><AgentList room="autonomous"/></div><div className="panel scenario-panel"><div className="eyebrow"><Sparkles size={13}/> REPEATABLE DEMOS</div><h3>See the agents at work</h3><p>Controlled scenarios use simulated evidence and exercise the real event feed.</p><button className="scenario-button" onClick={() => run.mutate('suspicious-token')} disabled={run.isPending}><span className="scenario-icon"><Play size={14} fill="currentColor"/></span><span>Run suspicious token case</span><ChevronRight size={15}/></button><button className="scenario-button" onClick={() => run.mutate('potential-opportunity')} disabled={run.isPending}><span className="scenario-icon pale"><Play size={14} fill="currentColor"/></span><span>Run opportunity case</span><ChevronRight size={15}/></button>{run.error && <div className="inline-error">{run.error.message}</div>}{run.data && <div className="success-note"><CheckCircle2 size={14}/> Scenario complete · simulated</div>}</div></aside></div>
  </div>
}

function AgentList({room}: {room: 'autonomous'|'trading'}) {
  const query = useQuery({queryKey: ['agents', room], queryFn: () => api.agents(room)})
  const descriptions: Record<string,string> = {nova:'Market intelligence',atlas:'Trading & liquidity',vega:'Contract security',echo:'Wallet intelligence',orion:'Debate & decisions',makto:'Demo portfolio'}
  return <div className="agents-list">{query.data?.agents.filter(agent => room === 'autonomous' ? agent.id !== 'makto' : true).map(agent => <div className="agent-row" key={agent.id} title={`${agent.tokens_analyzed} crypto assets analyzed · ${agent.llm_tokens} LLM tokens used · ${agent.investigations} investigations · last activity ${agent.last_activity ? new Date(agent.last_activity).toLocaleString() : 'none'}`}><span className={`agent-avatar ${agentTint[agent.id]}`}>{agent.name[0]}</span><div><b>{agent.name}</b><small>{descriptions[agent.id] ?? agent.role} · {agent.tokens_analyzed} crypto assets · {agent.investigations} investigations</small></div></div>)}</div>
}

function WalletGate({connect, connecting, error}: {connect: () => void; connecting: boolean; error?: string}) {
  return <div className="gate-wrap"><div className="gate-card"><div className="gate-art"><div className="gate-orbit orbit-one"/><div className="gate-orbit orbit-two"/><div className="gate-core"><WalletCards size={31}/></div><div className="gate-spark spark-a"/><div className="gate-spark spark-b"/></div><div className="eyebrow centered"><span/> TRADING ROOM ACCESS</div><h2>Connect your demo wallet</h2><p>The Trading Room is available after connecting a simulated NEAR wallet. It uses test balances and never signs real transactions.</p><button className="primary-button wide" onClick={connect} disabled={connecting}><WalletCards size={17}/>{connecting ? 'Connecting…' : 'Connect demo wallet'}<ChevronRight size={16}/></button>{error && <div className="inline-error gate-error">{error}</div>}<div className="gate-reassurance"><span><Check size={13}/> No private keys</span><span><Check size={13}/> No real funds</span><span><Check size={13}/> Demo only</span></div></div></div>
}

function TradingRoom({wallet, walletLoading, connect, connecting, connectError}: {wallet?: {connected: boolean; address?: string; near_balance?: string}; walletLoading: boolean; connect: () => void; connecting: boolean; connectError?: string}) {
  const queryClient = useQueryClient()
  const chatsQuery = useQuery({queryKey: ['trading-chats'], queryFn: api.tradingChats, enabled: !!wallet?.connected})
  const [chatId, setChatId] = useState('')
  const [chatSearch, setChatSearch] = useState('')
  const [toolsOpen, setToolsOpen] = useState(false)
  const [chatSending, setChatSending] = useState(false)
  useEffect(() => {
    if (!chatId && chatsQuery.data?.chats.length) setChatId(chatsQuery.data.chats[0].id)
  }, [chatId, chatsQuery.data])
  const newChat = useMutation({mutationFn: api.newTradingChat, onSuccess: chat => {
    setChatId(chat.id)
    setText('')
    void queryClient.invalidateQueries({queryKey:['trading-chats']})
  }})
  const query = useQuery({queryKey: ['trading-messages', chatId], queryFn: () => api.messages('trading', chatId), enabled: !!wallet?.connected && !!chatId, refetchInterval: chatSending ? 1_000 : 15_000})
  const [text, setText] = useState('')
  const send = useMutation({mutationFn: (content: string) => api.send(content, chatId), onSuccess: () => {
    setText('')
    void queryClient.invalidateQueries({queryKey:['trading-chats']})
    void query.refetch()
  }, onError: () => { void query.refetch() }, onSettled: () => setChatSending(false)})
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (text.trim() && chatId && !send.isPending) {
      setChatSending(true)
      send.mutate(text.trim())
    }
  }
  if (walletLoading) return <div className="page-content"><div className="empty-state"><div className="loading-orbit"/><span>Checking wallet session…</span></div></div>
  if (!wallet?.connected) return <div className="page-content"><PageHeading eyebrow="COLLABORATIVE DEPARTMENT" title="Trading Room">Work alongside the agents with a private conversation and a simulated wallet.</PageHeading><WalletGate connect={connect} connecting={connecting} error={connectError}/></div>

  const visibleChats = (chatsQuery.data?.chats ?? []).filter(chat => chat.title.toLowerCase().includes(chatSearch.trim().toLowerCase()))
  const activeChat = chatsQuery.data?.chats.find(chat => chat.id === chatId)
  return <div className="page-content trading-chat-page">
    <header className="trading-chat-top">
      <div className="trading-chat-title">
        <span className="eyebrow">CLAW INTEL · TRADING ROOM</span>
        <h1>Trading Room</h1>
        <p>Chat with six agents about tokens, markets, and your demo portfolio.</p>
      </div>
      <div className="trading-chat-actions">
        <span className="demo-balance-pill"><WalletCards size={14}/>{Number(wallet.near_balance ?? 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} NEAR <small>DEMO</small></span>
        <button className={toolsOpen ? 'tools-toggle active' : 'tools-toggle'} onClick={() => setToolsOpen(value => !value)}><Zap size={14}/>{toolsOpen ? 'Hide tools' : 'Trading tools'}</button>
      </div>
    </header>
    <div className={toolsOpen ? 'trading-grid chat-layout tools-visible' : 'trading-grid chat-layout'}>
      <aside className="panel chat-history">
        <div className="chat-history-heading"><span>Chats</span><button className="new-chat-icon" aria-label="Start a new chat" title="New chat" onClick={() => newChat.mutate()} disabled={newChat.isPending}><MessageCircle size={16}/><span>＋</span></button></div>
        <button className="new-chat-button" onClick={() => newChat.mutate()} disabled={newChat.isPending}>＋ New chat</button>
        <label className="chat-search"><Search size={14}/><input aria-label="Search chats" placeholder="Search chats" value={chatSearch} onChange={event => setChatSearch(event.target.value)}/></label>
        <div className="chat-history-list">
          {visibleChats.map(chat => <button key={chat.id} className={chat.id === chatId ? 'active' : ''} onClick={() => setChatId(chat.id)} title={chat.title}><MessageCircle size={14}/><span>{chat.title}</span></button>)}
          {!visibleChats.length && <div className="chat-history-empty">{chatSearch ? 'No matching chats' : 'Your conversations will appear here'}</div>}
        </div>
        {chatsQuery.error && <ErrorCard message={chatsQuery.error.message}/>}
        {newChat.error && <ErrorCard message={newChat.error.message}/>}
      </aside>
      <section className="panel conversation-panel trading-convo">
        <div className="chat-thread-header">
          <div><span className="chat-thread-title">{activeChat?.title ?? 'New conversation'}</span><span className="chat-thread-subtitle">Six agents · private demo workspace</span></div>
          <span className="private-tag"><ShieldCheck size={13}/> PRIVATE</span>
        </div>
        <div className="feed-scroll">
          {!chatId ? <div className="chat-start"><div className="chat-start-icon"><Bot size={25}/></div><h2>What should we look at?</h2><p>Ask Nova to inspect a token or bring a market question to the full team.</p><div className="chat-suggestions"><button onClick={() => setText('Paste a token address and have Nova check all available details.')}>Check a token address</button><button onClick={() => setText('Ask the team to assess current market risks.')}>Review market risks</button><button onClick={() => setText('@makto open a demo trade for CLAW')}>Open a demo position</button></div></div>
            : query.error ? <ErrorCard message={query.error.message}/>
            : query.isLoading ? <MessageList loading={true}/>
            : query.data?.messages.length ? <MessageList messages={query.data.messages} loading={false} roundtable/>
            : <div className="chat-start"><div className="chat-start-icon"><Bot size={25}/></div><h2>What should we look at?</h2><p>Ask Nova to inspect a token or bring a market question to the full team.</p><div className="chat-suggestions"><button onClick={() => setText('Paste a token address and have Nova check all available details.')}>Check a token address</button><button onClick={() => setText('Ask the team to assess current market risks.')}>Review market risks</button><button onClick={() => setText('@makto open a demo trade for CLAW')}>Open a demo position</button></div></div>}
          {send.error && <ErrorCard message={send.error.message}/>}
        </div>
        <div className="composer-wrap">
          <div className="mention-row"><span>MENTION AN AGENT</span>{['Nova','Atlas','Vega','Echo','Orion','Makto'].map(name => <button key={name} disabled={send.isPending || !chatId} onClick={() => setText(value => value + (value ? ' ' : '') + '@' + name.toLowerCase() + ' ')}>@{name}</button>)}</div>
          <form className="composer" onSubmit={submit}>
            <textarea aria-label="Message the Trading Room" placeholder="Message the Trading Room…" rows={2} value={text} onChange={event => setText(event.target.value)} onKeyDown={event => {if(event.key === 'Enter' && !event.shiftKey){event.preventDefault(); if(text.trim() && chatId && !send.isPending) send.mutate(text.trim())}}}/>
            <div className="composer-bottom"><span>{send.isPending ? 'Agents are taking turns…' : 'Enter to send · Shift + Enter for a new line'}</span><button className="send-button" aria-label="Send message to all agents" disabled={!text.trim() || !chatId || send.isPending}><Send size={16}/></button></div>
          </form>
        </div>
      </section>
      {toolsOpen && <aside className="right-rail trading-tools-panel"><div className="panel tools-panel-header"><div><span>Wallet & trade controls</span><button onClick={() => setToolsOpen(false)} aria-label="Close trading tools"><X size={15}/></button></div></div><WalletCard balance={wallet.near_balance}/><QuotePanel balance={wallet.near_balance ?? '0'}/></aside>}
    </div>
  </div>
}

function WalletCard({balance}: {balance?: string}) { return <div className="panel wallet-card"><div className="panel-header"><div><span className="panel-title">Demo wallet</span><span className="panel-subtitle">NEAR Wallet</span></div><span className="wallet-check"><Check size={14}/></span></div><div className="balance-label">AVAILABLE BALANCE</div><div className="balance-number">{Number(balance ?? 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}<span>NEAR</span></div><div className="wallet-address"><span className="wallet-orb"/> demo wallet connected <span>·</span> no real funds</div></div> }

function QuotePanel({balance}: {balance: string}) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState('demo:claw')
  const [side, setSide] = useState<'buy'|'sell'>('buy')
  const [amount, setAmount] = useState('10')
  const [quote, setQuote] = useState<Quote | null>(null)
  const [notice, setNotice] = useState('')
  const quoteMutation = useMutation({mutationFn: () => api.quote({chain:'demo', token_address:token, side, amount_near:Number(amount)}), onSuccess: data => {setQuote(data); setNotice('')}, onError: error => {setQuote(null); setNotice(error.message)}})
  const approveMutation = useMutation({mutationFn: (approved: boolean) => api.approve(quote!.quote_id, approved), onSuccess: data => {setQuote(null); setNotice(data.status === 'confirmed_demo' ? 'Trade simulated and added to portfolio.' : 'Quote rejected. No balance changed.'); void queryClient.invalidateQueries({queryKey:['portfolio']}); void queryClient.invalidateQueries({queryKey:['wallet']})}})
  return <div className="panel quote-panel"><div className="eyebrow"><Zap size={13}/> MAKTO · DEMO EXECUTION</div><h3>Prepare a trade</h3><label className="field-label" htmlFor="demo-side">ACTION</label><select id="demo-side" value={side} onChange={e => {setSide(e.target.value as 'buy'|'sell'); setQuote(null)}}><option value="buy">Buy with NEAR</option><option value="sell">Sell position value</option></select><label className="field-label" htmlFor="demo-token">SIMULATED TOKEN</label><select id="demo-token" value={token} onChange={e => {setToken(e.target.value); setQuote(null)}}><option value="demo:claw">CLAW · fixture token</option><option value="demo:signal">SIGNAL · fixture token</option></select><label className="field-label" htmlFor="demo-amount">{side === 'buy' ? 'SPEND' : 'SELL VALUE'} <small>· NEAR</small></label><div className="input-with-suffix"><input id="demo-amount" type="number" min="0.1" max="250" step="0.1" value={amount} onChange={e => setAmount(e.target.value)}/><span>NEAR</span></div><button className="secondary-button full" disabled={quoteMutation.isPending || Number(amount) <= 0 || (side === 'buy' && Number(amount) > Number(balance))} onClick={() => quoteMutation.mutate()}>{quoteMutation.isPending ? 'Getting quote…' : 'Get simulated quote'}<ChevronRight size={15}/></button>{notice && <div className={notice.startsWith('Trade') || notice.startsWith('Quote rejected') ? 'success-note' : 'inline-error'}>{notice}</div>}{quote && <div className="quote-review"><div className="quote-title"><span><CheckCircle2 size={14}/> Quote ready</span><span className="sim-tag">SIMULATED</span></div><div className="quote-line"><span>{side === 'buy' ? 'You spend' : 'Position value sold'}</span><b>{quote.amount_near} NEAR</b></div><div className="quote-line"><span>Price</span><b>{quote.price_near_per_token} NEAR / token</b></div><div className="quote-line"><span>Est. quantity</span><b>{Number(quote.estimated_quantity).toFixed(4)} {quote.symbol}</b></div><div className="quote-line"><span>Demo fee</span><b>{quote.fee_near} NEAR</b></div><div className="quote-expiry"><Clock3 size={12}/> Expires {new Date(quote.expires_at).toLocaleTimeString()}</div><div className="quote-actions"><button onClick={() => approveMutation.mutate(false)} disabled={approveMutation.isPending}>Reject</button><button onClick={() => approveMutation.mutate(true)} disabled={approveMutation.isPending}><Check size={14}/> Approve simulation</button></div></div>}{approveMutation.error && <div className="inline-error">{approveMutation.error.message}</div>}<div className="quote-footnote">Fixture prices only · execution never reaches a blockchain.</div></div>
}

function Investigations() {
  const query = useQuery({queryKey:['autonomous-investigations'],queryFn:()=>api.investigations('autonomous'),refetchInterval:20000})
  const evidenceQuery = useQuery({queryKey:['warroom-evidence'],queryFn:api.evidence,refetchInterval:30000})
  const [filter, setFilter] = useState('')
  const entries = (query.data?.investigations ?? []).filter(item => `${item.title} ${item.chain} ${item.token_address} ${item.status}`.toLowerCase().includes(filter.toLowerCase()))
  const evidence = (evidenceQuery.data?.evidence ?? []).filter(item => `${item.chain} ${item.token_address} ${String(item.fields.symbol ?? '')} ${item.source}`.toLowerCase().includes(filter.toLowerCase()))
  return <div className="page-content"><PageHeading eyebrow="EVIDENCE RECORDS" title="Investigations">Persisted investigations, agent findings, debate rounds and source records.</PageHeading><div className="panel records-panel"><div className="panel-header"><div><span className="panel-title">Investigation history</span><span className="panel-subtitle">Independent findings, challenges and Orion's conclusion</span></div><label className="search-box"><Search size={14}/><input aria-label="Search investigations" placeholder="Search token or chain" value={filter} onChange={event=>setFilter(event.target.value)}/></label></div>{query.isLoading ? <div className="empty-state"><div className="loading-orbit"/><span>Loading investigations…</span></div> : query.error ? <ErrorCard message={query.error.message}/> : entries.length ? entries.map((item: Investigation, i)=><article className="record-row investigation-row" key={item.id}><div className="record-icon"><ShieldCheck size={17}/></div><div className="record-main"><div><b>{item.title}</b><span className={`investigation-status ${item.status}`}>{item.status.toUpperCase()}</span>{item.scenario_id && <span className="sim-tag">SIMULATED</span>}</div><small>{item.chain} · {item.token_address} · {new Date(item.updated_at).toLocaleString()} · {item.findings.length} findings{item.confidence != null ? ` · Orion confidence ${item.confidence}%` : ''}</small><details className="investigation-findings"><summary>Review findings and debate</summary>{item.findings.map(finding=><div className="finding-row" key={finding.id}><b>{agentNames[finding.agent_id] ?? finding.agent_id} · {finding.phase.replace('_',' ')}</b><p>{finding.content}</p><small>Round {finding.round} · evidence {finding.evidence_ids.join(', ') || 'not linked'}</small></div>)}</details></div><span className="record-index">{String(entries.length-i).padStart(2,'0')}</span></article>) : <div className="empty-state compact"><span>No investigation records match this search.</span><Link className="text-link" to="/war-room">Open War Room <ChevronRight size={14}/></Link></div>}</div>
    <div className="panel records-panel evidence-panel"><div className="panel-header"><div><span className="panel-title">Evidence ledger</span><span className="panel-subtitle">Source and data status are preserved with each observation</span></div><label className="search-box"><Search size={14}/><input aria-label="Search evidence" placeholder="Search chain or token" value={filter} onChange={event=>setFilter(event.target.value)}/></label></div>{evidenceQuery.isLoading ? <div className="empty-state compact"><span>Loading evidence…</span></div> : evidenceQuery.error ? <ErrorCard message={(evidenceQuery.error as Error).message}/> : evidence.length ? evidence.map(item=><EvidenceRow item={item} key={item.id}/>) : <div className="empty-state compact"><span>No matching evidence has been recorded.</span></div>}</div></div>
}

function EvidenceRow({item}: {item: EvidenceRecord}) {
  const symbol = String(item.fields.symbol ?? 'Unknown token')
  const price = item.fields.price_usd
  const liquidity = item.fields.liquidity_usd
  const volume = item.fields.volume_24h_usd
  return <article className="evidence-row"><span className={`evidence-state ${item.data_kind}`}>{item.data_kind}</span><div className="evidence-main"><div><b>{symbol}</b><span>{item.chain}</span></div><small>{item.token_address}</small><small className="evidence-source">{item.source} · {new Date(item.observed_at).toLocaleString()}</small>{item.limitations && <p>{item.limitations}</p>}</div><div className="evidence-metrics"><span>PRICE <b>{price == null ? 'Unavailable' : `$${String(price)}`}</b></span><span>LIQUIDITY <b>{liquidity == null ? 'Unavailable' : `$${String(liquidity)}`}</b></span><span>24H VOL <b>{volume == null ? 'Unavailable' : `$${String(volume)}`}</b></span></div></article>
}

function PortfolioPage({wallet, connect}: {wallet?: {connected:boolean; near_balance?:string}; connect: ()=>void}) {
  const queryClient = useQueryClient()
  const query = useQuery({queryKey:['portfolio'], queryFn:api.portfolio, enabled:!!wallet?.connected})
  const shift = useMutation({mutationFn:api.shiftMarket, onSuccess: () => { void queryClient.invalidateQueries({queryKey:['portfolio']}); void queryClient.invalidateQueries({queryKey:['trading-messages']}) }})
  if (!wallet?.connected) return <div className="page-content"><PageHeading eyebrow="DEMO WALLET" title="Portfolio">Positions and simulated execution history for your demo session.</PageHeading><WalletGate connect={connect} connecting={false}/></div>
  const data = query.data as Portfolio | undefined
  return <div className="page-content"><PageHeading eyebrow="MAKTO · SIMULATED PORTFOLIO" title="Portfolio">Positions, balances and trade activity from the demo ledger.</PageHeading>{query.error && <ErrorCard message={(query.error as Error).message}/>}<div className="portfolio-summary"><div className="panel metric-card"><span>AVAILABLE BALANCE</span><b>{Number(data?.near_balance ?? wallet.near_balance ?? 0).toFixed(2)} <small>NEAR</small></b><i><WalletCards size={15}/> Demo ledger</i></div><div className="panel metric-card"><span>OPEN POSITIONS</span><b>{data?.positions.length ?? '—'}</b><i><Activity size={15}/> Simulated marks only</i></div><div className="panel metric-card"><span>RECENT TRADE RECORDS</span><b>{data?.trades.length ?? '—'}</b><i><ShieldCheck size={15}/> Simulated only</i></div></div><section className="panel scenario-controls"><div className="panel-header"><div><span className="panel-title">Scenario E · Market changes after a trade</span><span className="panel-subtitle">Applies a deterministic +25% simulated mark to open fixture positions; Makto and Orion discuss the change.</span></div><button className="secondary-button" onClick={()=>shift.mutate()} disabled={shift.isPending || !data?.positions.length}><Activity size={14}/>{shift.isPending ? 'Updating…' : 'Simulate market shift'}</button></div>{shift.error && <ErrorCard message={(shift.error as Error).message}/>}</section><div className="portfolio-grid"><div className="panel records-panel"><div className="panel-header"><div><span className="panel-title">Positions</span><span className="panel-subtitle">Deterministic demo marks, never live quotes</span></div></div>{data?.positions.length ? data.positions.map((p,i)=><div className="position-row" key={`${p.chain}-${p.token_address}-${i}`}><div className="token-monogram">{p.token_address.split(':').at(-1)?.slice(0,1).toUpperCase()}</div><div><b>{p.token_address.split(':').at(-1)?.toUpperCase()}</b><small>{p.chain} · {p.quantity} units · value {p.value_near ?? 'Unavailable'} NEAR</small></div><span className="position-price">Now {p.current_price_near ?? '—'} NEAR</span></div>) : <div className="empty-state compact"><span>No simulated positions yet.</span><Link to="/trading" className="text-link">Prepare a demo trade <ChevronRight size={14}/></Link></div>}</div><div className="panel records-panel"><div className="panel-header"><div><span className="panel-title">Recent trades</span><span className="panel-subtitle">All executions are simulations</span></div></div>{data?.trades.length ? data.trades.map(t=><div className="trade-row" key={t.id}><span className="trade-icon"><ArrowUpRight size={15}/></span><div><b>{t.side.toUpperCase()} {t.token_address.split(':').at(-1)?.toUpperCase()}</b><small>{new Date(t.created_at).toLocaleString()}</small></div><span className="trade-amount">{t.amount_near} NEAR</span></div>) : <div className="empty-state compact"><span>No trades yet.</span></div>}</div></div></div>
}

function SettingsPage() {
  const query = useQuery({queryKey:['settings'],queryFn:api.status})
  const usage = useQuery({queryKey:['llm-usage'],queryFn:api.usage})
  const run = useMutation({mutationFn:api.runScenario})
  const sources=query.data?.data_sources
  return <div className="page-content"><PageHeading eyebrow="CONFIGURATION & HEALTH" title="Settings & system">Review server-side provider configuration, live data sources, usage and controlled demo workflows.</PageHeading>{query.error && <ErrorCard message={(query.error as Error).message}/>}<div className="settings-grid">{query.data?.departments.map(department=><section className="panel settings-panel" key={department.department}><div className="panel-header"><div><span className="panel-title">{department.department === 'autonomous' ? 'War Room' : 'Trading Room'} providers</span><span className="panel-subtitle">Keys stay on the server</span></div><span className={`availability ${department.available ? 'available' : 'unavailable'}`}><i/>{department.available ? 'READY' : 'NOT CONFIGURED'}</span></div>{department.providers.map(provider=><div className="provider-row" key={provider.provider}><div className={`provider-mark ${provider.provider}`}>{provider.provider.slice(0,1).toUpperCase()}</div><div><b>{provider.provider}</b><small>{provider.model ?? 'Provider key or model is not configured'}</small></div><span className={provider.configured ? 'provider-on' : 'provider-off'}>{provider.configured ? 'Configured' : 'Unavailable'}</span></div>)}</section>)}</div><div className="settings-grid"><section className="panel settings-panel"><div className="panel-header"><div><span className="panel-title">Live data sources</span><span className="panel-subtitle">Configured integrations; status does not expose credentials</span></div><Activity size={16}/></div><div className="provider-row"><div><b>DexScreener</b><small>Latest profiles and pair metrics · public API</small></div><span className="provider-on">{sources?.dexscreener.configured ? 'Available' : 'Unavailable'}</span></div><div className="provider-row"><div><b>CoinGecko</b><small>Contract-address metadata and market context</small></div><span className={sources?.coingecko.configured ? 'provider-on' : 'provider-off'}>{sources?.coingecko.configured ? 'Configured' : 'Not configured'}</span></div>{Object.entries(sources?.rpc ?? {}).map(([chain,configured])=><div className="provider-row" key={chain}><div><b>{chain.toUpperCase()} RPC</b><small>Read-only account or contract-code facts</small></div><span className={configured ? 'provider-on' : 'provider-off'}>{configured ? 'Configured' : 'Not configured'}</span></div>)}<div className="settings-note"><Database size={15}/><span>Autonomous scan {sources?.auto_scan_enabled ? `runs every ${Math.round((sources?.scan_interval_seconds ?? 0)/60)} minutes` : 'is disabled'}.</span></div></section><section className="panel settings-panel"><div className="panel-header"><div><span className="panel-title">LLM usage</span><span className="panel-subtitle">Provider-reported token counts · costs unavailable unless pricing is verified</span></div><Activity size={16}/></div>{(['autonomous','trading'] as const).map(department=>{const row=usage.data?.departments[department];return <div className="provider-row" key={department}><div><b>{department==='autonomous'?'War Room':'Trading Room'}</b><small>{row?.requests ?? 0} requests · {row?.input_tokens ?? 0} input / {row?.output_tokens ?? 0} output tokens</small></div><span className="provider-off">Cost unavailable</span></div>})}{usage.error && <ErrorCard message={(usage.error as Error).message}/>}</section></div><section className="panel settings-panel scenario-controls"><div className="panel-header"><div><span className="panel-title">Deterministic evidence scenarios</span><span className="panel-subtitle">Fixtures are labeled simulated; agent responses are generated dynamically</span></div><Sparkles size={17}/></div><div className="scenario-control-row"><div><b>Suspicious token case</b><small>Controlled market anomaly, contract uncertainty and unresolved deployer history.</small></div><button className="secondary-button" onClick={()=>run.mutate('suspicious-token')} disabled={run.isPending}><Play size={14}/> Run case</button></div><div className="scenario-control-row"><div><b>Potential opportunity</b><small>Balanced fixture with explicit execution and source-verification limits.</small></div><button className="secondary-button" onClick={()=>run.mutate('potential-opportunity')} disabled={run.isPending}><Play size={14}/> Run case</button></div>{run.error && <div className="inline-error">{run.error.message}</div>}{run.data && <div className="success-note"><CheckCircle2 size={14}/> {run.data.findings} agent findings stored · simulated</div>}</section><div className="settings-note"><Database size={16}/><span>PostgreSQL is the source of truth. Apply Alembic migrations before first start; the API does not create schema automatically.</span></div></div>
}
