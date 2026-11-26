import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useConnect, useSignMessage, type Connector } from 'wagmi'
import { Activity, ArrowDownUp, ArrowUpRight, Bell, Bot, Check, CheckCircle2, ChevronRight, CircleAlert, Clock3, Menu, MessageCircle, Paperclip, Plus, Search, Send, Settings, ShieldCheck, Trash2, WalletCards, X, Zap } from 'lucide-react'
import { api, type ChatAttachment, type Investigation, type TokenLookup, type WalletIdentityState, type PaperPortfolio, type TradingWatchlist } from './api'
import { hasWalletConnectProjectId } from './wallet-config'
import WarRoom from './pages/WarRoom'
import { AgentMessageFeed, StreamingAgentMessage } from './components/AgentMessageFeed'

const agentNames: Record<string, string> = { nova: 'Nova', atlas: 'Atlas', vega: 'Vega', echo: 'Echo', orion: 'Orion', makto: 'Makto', human: 'You' }

export default function App() {
  const [ready, setReady] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const [walletDialogOpen, setWalletDialogOpen] = useState(false)
  const [streamingMessage, setStreamingMessage] = useState<{chat_id: string; agent_id: string} | null>(null)
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
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
    let lastSequence = 0
    const connect = () => {
      if (stopped) return
      socket = new WebSocket(`${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/${room}?after=${lastSequence}`)
      socket.onopen = () => { retryDelay = 500 }
      socket.onmessage = event => {
        let message: {event_type?: string; agent_id?: string; payload?: Record<string, unknown>}
        try { message = JSON.parse(event.data) as typeof message } catch { return }
        const sequence = (message as {sequence?: number}).sequence
        if (typeof sequence === 'number') {
          if (sequence <= lastSequence) return
          lastSequence = sequence
        }
        const payload = message.payload ?? {}
        if (message.event_type === 'AGENT_STREAM' && typeof payload.chat_id === 'string' && message.agent_id) {
          const chat_id = payload.chat_id
          const agent_id = message.agent_id
          const status = payload.status
          if (status === 'start') setStreamingMessage({chat_id, agent_id})
          else if (status === 'failed') setStreamingMessage(current => current?.chat_id === chat_id && current.agent_id === agent_id ? null : current)
          else if (status === 'done') void queryClient.invalidateQueries({queryKey: ['trading-messages', chat_id]}).then(() => {
            setStreamingMessage(current => current?.chat_id === chat_id && current.agent_id === agent_id ? null : current)
          })
          return
        }
        const chat_id = typeof payload.chat_id === 'string' ? payload.chat_id : null
        const queryKey = room === 'trading' && chat_id ? ['trading-messages', chat_id] : [room === 'trading' ? 'trading-messages' : 'warroom-messages']
        void queryClient.invalidateQueries({queryKey})
      }
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
  const auth = useQuery({ queryKey: ['wallet-auth'], queryFn: api.walletAuth, enabled: ready, retry: false })
  const openSettings = () => navigate('/settings')
  useEffect(() => {
    const openWalletDialog = () => setWalletDialogOpen(true)
    window.addEventListener('zecto:open-wallet', openWalletDialog)
    return () => window.removeEventListener('zecto:open-wallet', openWalletDialog)
  }, [])
  const title = useMemo(() => ({ '/wallet': 'Dashboard', '/dashboard': 'Dashboard', '/trading': 'Trading Room', '/war-room': 'War Room', '/investigations': 'War Room', '/watchlists': 'War Room', '/settings': 'Settings' }[location.pathname] ?? 'Dashboard'), [location.pathname])

  if (!ready || auth.isLoading) return <div className="connect-loading"><div className="loading-orbit"/><span>Preparing your Zecto wallet…</span></div>
  if (!auth.data?.authenticated) return <><ConnectLanding onConnect={() => setWalletDialogOpen(true)}/><WalletConnectDialog open={walletDialogOpen} onClose={() => setWalletDialogOpen(false)} onConnected={() => {setWalletDialogOpen(false);navigate('/wallet')}}/></>

  return <div className="app-shell">
    <aside className={`sidebar ${navOpen ? 'open' : ''}`}>
      <Link to="/dashboard" className="brand" onClick={() => setNavOpen(false)}><div className="brand-mark"><img src="/zecto-mark.svg" alt=""/></div><span>Zecto</span></Link>
      <div className="workspace-label">ZECTO</div>
      <nav className="nav-list" aria-label="Main navigation">
        <NavLink to="/dashboard" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><WalletCards size={17}/><span>Dashboard</span></NavLink>
        <NavLink to="/trading" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><MessageCircle size={17}/><span>Trading Room</span></NavLink>
        <NavLink to="/war-room" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><ShieldCheck size={17}/><span>War Room</span><span className="live-dot"/></NavLink>
        <NavLink to="/settings" onClick={() => setNavOpen(false)} className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}><Settings size={17}/><span>Settings</span></NavLink>
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-status"><span className="status-icon"><Zap size={14}/></span><div><b>Virtual portfolio</b><small>USDC · live market data</small></div></div>
        <div className="user-chip"><div className="user-avatar">Z</div><div><b>{auth.data?.authenticated ? 'Wallet verified' : 'Guest access'}</b><small>{auth.data?.wallets[0]?.address.slice(0, 16) ?? 'Connect in Settings'}</small></div><ChevronRight size={15}/></div>
      </div>
    </aside>
    {navOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)}/>}
    <main className="main-area">
      <header className="topbar"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setNavOpen(true)}><Menu size={19}/></button><div className="breadcrumb"><span>Zecto</span><ChevronRight size={14}/><b>{title}</b></div><div className="topbar-right"><span className={`system-state ${health.data?.status === 'ok' ? '' : health.isLoading ? 'checking' : 'offline'}`}><i/>{health.data?.status === 'ok' ? 'API + DATABASE ONLINE' : health.isLoading ? 'CHECKING SYSTEM' : 'SYSTEM UNAVAILABLE'}</span><div className="topbar-divider"/>{auth.data?.authenticated ? <button className="wallet-pill connected" onClick={openSettings} title="Manage verified wallet identities"><span className="wallet-orb"/><span>{auth.data.wallets[0]?.address.slice(0, 14) ?? 'Wallet verified'}…</span></button> : <button className="wallet-pill" onClick={() => setWalletDialogOpen(true)} title="Connect and verify a wallet"><WalletCards size={15}/><span>Connect wallet</span></button>}</div></header>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace/>}/><Route path="/dashboard" element={<DashboardPage authenticated={true} welcome={sessionStorage.getItem('zecto:welcome') === '1'} onWelcomeSeen={() => sessionStorage.removeItem('zecto:welcome')}/>}/><Route path="/wallet" element={<Navigate to="/dashboard" replace/>}/><Route path="/war-room" element={<WarRoom/>}/>
        <Route path="/trading" element={<TradingRoom wallet={auth.data} walletLoading={auth.isLoading} streamingMessage={streamingMessage}/>}/>
        <Route path="/portfolio" element={<Navigate to="/dashboard" replace/>}/><Route path="/investigations" element={<Investigations/>}/><Route path="/watchlists" element={<WatchlistsPage authenticated={true}/>}/><Route path="/settings" element={<SettingsPage/>}/>
      </Routes>
      <WalletConnectDialog open={walletDialogOpen} onClose={() => setWalletDialogOpen(false)} onConnected={() => {sessionStorage.setItem('zecto:welcome','1');setWalletDialogOpen(false);navigate('/dashboard')}}/>
      <footer className="app-footer"><span><i/> Service status reflects configured health checks</span><span>ZECTO · INTELLIGENCE, WITH EVIDENCE</span><span>VIRTUAL TRADING · VIRTUAL FUNDS</span></footer>
    </main>
  </div>
}

function PageHeading({eyebrow, title, children, right}: {eyebrow: string; title: string; children: ReactNode; right?: ReactNode}) {
  return <div className="page-heading"><div><div className="eyebrow"><span/>{eyebrow}</div><h1>{title}</h1><p>{children}</p></div>{right && <div className="heading-right">{right}</div>}</div>
}

function ErrorCard({message}: {message: string}) { return <div className="error-card"><CircleAlert size={18}/><span>{message}</span></div> }

function WarRoomSubnav() {
  return <nav className="environment-subnav" aria-label="War Room sections">
    <NavLink end to="/war-room">Overview</NavLink>
    <NavLink to="/investigations">Investigations</NavLink>
    <NavLink to="/watchlists">Watchlists &amp; alerts</NavLink>
  </nav>
}

function ConnectLanding({onConnect}: {onConnect: () => void}) {
  return <main className="connect-landing"><div className="connect-card"><div className="brand-mark connect-brand"><img src="/zecto-mark.svg" alt=""/></div><span className="connect-kicker">ZECTO · AGENTIC MARKETS</span><h1>Connect your wallet</h1><p>Sign in to your private virtual portfolio, live token intelligence, and agent trading rooms.</p><button className="primary-button wide" onClick={onConnect}><WalletCards size={17}/>Connect wallet<ChevronRight size={16}/></button><div className="connect-safety"><ShieldCheck size={15}/> Identity message only · no token transfers · no on-chain trades</div></div><div className="connect-footer">Zecto <span>·</span> The Home of Agentic trade and market analysis</div></main>
}

function WalletMark({name, className = ''}: {name: string; className?: string}) {
  const key = name.toLowerCase()
  if (key.includes('phantom')) return <span className={`wallet-mark phantom-mark ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M8.2 23.4c-2.1 0-3.3-1.6-3.3-4.2C4.9 11.8 10.2 5 17.5 5c6.1 0 10 4.4 10 10.1 0 5.2-2.8 9-6.3 9-1.4 0-2.3-.7-2.8-2-1.1 1.5-2.6 2.4-4.2 2.4-1.2 0-2.1-.6-2.5-1.7-1 1-2.2 1.6-3.5 1.6Zm4-8.9c-.8 0-1.4 1-1.4 2.3s.6 2.3 1.4 2.3 1.4-1 1.4-2.3-.6-2.3-1.4-2.3Zm7.8 0c-.8 0-1.4 1-1.4 2.3s.6 2.3 1.4 2.3 1.4-1 1.4-2.3-.6-2.3-1.4-2.3Z"/></svg></span>
  if (key.includes('metamask')) return <span className={`wallet-mark metamask-mark ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="m16 4 7 6-3 7-4-2-4 2-3-7 7-6Z"/><path d="m9 10 3 7-2 5-4-3 3-9Zm14 0-3 7 2 5 4-3-3-9ZM12 18l4-2 4 2-1 6h-6l-1-6Z" opacity=".78"/></svg></span>
  if (key.includes('walletconnect')) return <span className={`wallet-mark walletconnect-mark ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M8 12.4c4.4-4.2 11.6-4.2 16 0l.8.8-3.1 3-.8-.7a6.8 6.8 0 0 0-9.1 0l-.8.7-3.1-3 .8-.8Zm-3.3 3.2 3.1-3 2.5 2.4-3.1 3-2.5-2.4Zm17 0 2.5-2.4 3.1 3-2.5 2.4-3.1-3ZM11 20.6l2.4-2.3 2.6 2.5 2.6-2.5 2.4 2.3-5 4.8-5-4.8Z"/></svg></span>
  if (key.includes('coinbase')) return <span className={`wallet-mark coinbase-mark ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11"/><path d="M19.9 13.5a4.4 4.4 0 1 0 0 5h-4a.6.6 0 1 1 0-1.2h7.3v-2.6h-7.3a.6.6 0 1 1 0-1.2h4Z"/></svg></span>
  return <span className={`wallet-mark browser-mark ${className}`} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M16 4 27 10v12l-11 6L5 22V10l11-6Zm0 4.2-7 3.9v7.8l7 3.9 7-3.9v-7.8l-7-3.9Z"/></svg></span>
}

function WalletConnectDialog({open, onClose, onConnected}: {open: boolean; onClose: () => void; onConnected: () => void}) {
  type SolanaProvider = {isPhantom?: boolean; connect(): Promise<{publicKey: {toString(): string}}>; signMessage(message: Uint8Array, display: 'utf8'): Promise<{signature: Uint8Array}>}
  const {connectAsync, connectors} = useConnect()
  const {signMessageAsync} = useSignMessage()
  const queryClient = useQueryClient()
  const [busyWallet, setBusyWallet] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busyWallet) onClose() }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open, busyWallet, onClose])
  if (!open) return null
  const finishAuthentication = async () => {
    const identity = await withWalletTimeout(queryClient.fetchQuery({
      queryKey: ['wallet-auth'],
      queryFn: api.walletAuth,
      staleTime: 0,
    }), 'Session verification')
    if (!identity.authenticated) throw new Error('The wallet signed in, but the browser session was not established. Check that you are using the same site address in the app and wallet, then try again.')
    onConnected()
  }
  const withWalletTimeout = <T,>(operation: Promise<T>, action: string): Promise<T> => Promise.race([
    operation,
    new Promise<T>((_, reject) => window.setTimeout(() => reject(new Error(`${action} timed out. Check your wallet for a pending approval, then try again.`)), 60_000)),
  ])
  const phantomProvider = (): SolanaProvider | null => {
    const ext = window as unknown as {phantom?: {solana?: SolanaProvider}; solana?: SolanaProvider}
    return ext.phantom?.solana?.isPhantom ? ext.phantom.solana : ext.solana?.isPhantom ? ext.solana : null
  }
  const connectEvm = async (connector: Connector) => {
    setBusyWallet(connector.name); setError('')
    try {
      const session = await withWalletTimeout(connectAsync({connector}), 'Wallet connection')
      const address = session.accounts[0]
      const chain = ({1:'ethereum', 56:'bsc', 8453:'base'} as Record<number, string>)[session.chainId]
      if (!address) throw new Error('The wallet did not return an account.')
      if (!chain) throw new Error('Switch to Ethereum, BNB Smart Chain, or Base in your wallet and try again.')
      const walletName = connector.name === 'Injected' ? 'Browser wallet' : connector.name
      const challenge = await withWalletTimeout(api.walletChallenge({chain, address, wallet_name: walletName}), 'Wallet challenge')
      const signature = await withWalletTimeout(signMessageAsync({account: address, message: challenge.message}), 'Wallet signature request')
      await withWalletTimeout(api.walletVerify({challenge_id: challenge.challenge_id, chain, address, wallet_name: walletName, signature}), 'Wallet verification')
      await finishAuthentication()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Wallet authentication failed.') }
    finally { setBusyWallet('') }
  }
  const connectPhantom = async () => {
    setBusyWallet('Phantom'); setError('')
    try {
      // Resolve the injected provider and start connect synchronously from the
      // click handler; awaiting beforehand can consume the browser user gesture.
      const provider = phantomProvider()
      if (!provider) throw new Error('This browser page cannot see Phantom. Install or enable the Phantom extension in this same browser, reload Zecto, and allow the extension to access this site. On mobile, open Zecto in Phantom’s in-app browser.')
      const session = await withWalletTimeout(provider.connect(), 'Phantom connection')
      const address = session.publicKey.toString()
      const challenge = await withWalletTimeout(api.walletChallenge({chain: 'solana', address, wallet_name: 'Phantom'}), 'Wallet challenge')
      const result = await withWalletTimeout(provider.signMessage(new TextEncoder().encode(challenge.message), 'utf8'), 'Phantom signature request')
      const signature = btoa(Array.from(result.signature, byte => String.fromCharCode(byte)).join(''))
      await withWalletTimeout(api.walletVerify({challenge_id: challenge.challenge_id, chain: 'solana', address, wallet_name: 'Phantom', signature}), 'Wallet verification')
      await finishAuthentication()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Phantom authentication failed.') }
    finally { setBusyWallet('') }
  }
  const uniqueConnectors = connectors.filter((connector, index) => connectors.findIndex(other => other.id === connector.id) === index)
  return <div className="wallet-modal-backdrop" onMouseDown={event => {if (event.target === event.currentTarget && !busyWallet) onClose()}}><section className="wallet-modal" role="dialog" aria-modal="true" aria-labelledby="wallet-modal-title"><button className="wallet-modal-close" onClick={onClose} aria-label="Close wallet chooser" disabled={!!busyWallet}><X size={18}/></button><div className="wallet-modal-kicker"><span/> SECURE WALLET SIGN IN</div><h2 id="wallet-modal-title">Connect a wallet</h2><p className="wallet-modal-copy">Choose a wallet to verify your account with a signed message. Zecto never asks for your seed phrase. On-chain sends you start in Dashboard require separate review and approval in your wallet.</p><button className="wallet-choice wallet-choice-primary" onClick={() => void connectPhantom()} disabled={!!busyWallet}><WalletMark name="Phantom"/><span className="wallet-choice-text"><b>Phantom</b><small>Solana · recommended</small></span><span className="wallet-choice-arrow">{busyWallet === 'Phantom' ? 'Waiting…' : 'Connect'}</span></button><div className="wallet-modal-divider"><span>OTHER WALLETS</span><i/></div><div className="wallet-choice-list">{uniqueConnectors.filter(connector => connector.id !== 'walletConnect').map(connector => <button className="wallet-choice" key={connector.uid} onClick={() => void connectEvm(connector)} disabled={!!busyWallet}><WalletMark name={connector.name}/><span className="wallet-choice-text"><b>{connector.name === 'Injected' ? 'Browser wallet' : connector.name}</b><small>Ethereum · BNB Chain · Base</small></span><span className="wallet-choice-arrow">{busyWallet === connector.name ? 'Waiting…' : 'Connect'}</span></button>)}{hasWalletConnectProjectId ? uniqueConnectors.filter(connector => connector.id === 'walletConnect').map(connector => <button className="wallet-choice" key={connector.uid} onClick={() => void connectEvm(connector)} disabled={!!busyWallet}><WalletMark name="WalletConnect"/><span className="wallet-choice-text"><b>WalletConnect</b><small>Mobile and desktop wallets</small></span><span className="wallet-choice-arrow">{busyWallet === connector.name ? 'Waiting…' : 'Connect'}</span></button>) : <div className="wallet-choice wallet-choice-unavailable"><WalletMark name="WalletConnect"/><span className="wallet-choice-text"><b>WalletConnect</b><small>Add VITE_WALLETCONNECT_PROJECT_ID to enable mobile wallets</small></span><span className="wallet-choice-arrow">Setup required</span></div>}</div>{error && <div className="wallet-modal-error" role="alert"><CircleAlert size={15}/>{error}</div>}<div className="wallet-modal-foot"><ShieldCheck size={14}/> Your identity is verified by a short-lived, one-time signed challenge.</div></section></div>
}

function WalletGate() {
  return <div className="gate-wrap"><div className="gate-card"><div className="gate-art"><div className="gate-orbit orbit-one"/><div className="gate-orbit orbit-two"/><div className="gate-core"><WalletCards size={31}/></div><div className="gate-spark spark-a"/><div className="gate-spark spark-b"/></div><div className="eyebrow centered"><span/> PRIVATE TRADING ROOM</div><h2>Connect your wallet</h2><p>Choose Phantom or another supported wallet to verify your account and open your private paper portfolio.</p><button className="primary-button wide" onClick={() => window.dispatchEvent(new Event('zecto:open-wallet'))}><WalletCards size={17}/>Choose a wallet<ChevronRight size={16}/></button><div className="gate-reassurance"><span><Check size={13}/> No private keys</span><span><Check size={13}/> No chain transaction</span><span><Check size={13}/> Signed identity proof</span></div></div></div>
}

function TradingRoom({wallet, walletLoading, streamingMessage}: {wallet?: WalletIdentityState; walletLoading: boolean; streamingMessage: {chat_id: string; agent_id: string} | null}) {
  const queryClient = useQueryClient()
  const authenticated = !!wallet?.authenticated
  const paper = useQuery({queryKey: ['paper-portfolio'], queryFn: api.paperPortfolio, enabled: authenticated, refetchInterval: 30_000})
  const chatsQuery = useQuery({queryKey: ['trading-chats'], queryFn: api.tradingChats, enabled: authenticated, refetchInterval: 15_000})
  const [chatId, setChatId] = useState('')
  const [chatSearch, setChatSearch] = useState('')
  const [toolsOpen, setToolsOpen] = useState(false)
  const [chatSending, setChatSending] = useState(false)
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [attachmentError, setAttachmentError] = useState('')
  useEffect(() => {
    if (!chatId && chatsQuery.data?.chats.length) setChatId(chatsQuery.data.chats[0].id)
  }, [chatId, chatsQuery.data])
  const newChat = useMutation({mutationFn: api.newTradingChat, onSuccess: chat => {
    setChatId(chat.id)
    setText('')
    void queryClient.invalidateQueries({queryKey:['trading-chats']})
  }})
  useEffect(() => {
    if (!authenticated || !chatsQuery.isSuccess || chatsQuery.data.chats.length || chatId || newChat.isPending) return
    newChat.mutate()
  }, [authenticated, chatsQuery.isSuccess, chatsQuery.data, chatId, newChat.isPending, newChat.mutate])
  useEffect(() => {
    if (!chatId || !chatsQuery.data || chatsQuery.data.chats.some(chat => chat.id === chatId)) return
    const nextChat = chatsQuery.data.chats[0]
    if (nextChat) setChatId(nextChat.id)
    else { setChatId(''); newChat.mutate() }
  }, [chatId, chatsQuery.data])
  const deleteChat = useMutation({mutationFn: api.deleteTradingChat, onSuccess: (_result, deletedId) => {
    const cached = queryClient.getQueryData<NonNullable<typeof chatsQuery.data>>(['trading-chats'])
    const remaining = (cached?.chats ?? []).filter(chat => chat.id !== deletedId)
    queryClient.setQueryData(['trading-chats'], {chats: remaining})
    queryClient.removeQueries({queryKey:['trading-messages', deletedId]})
    if (chatId === deletedId) {
      if (remaining[0]) setChatId(remaining[0].id)
      else { setChatId(''); newChat.mutate() }
    }
    void queryClient.invalidateQueries({queryKey:['trading-chats']})
  }})
  const query = useQuery({queryKey: ['trading-messages', chatId], queryFn: () => api.messages('trading', chatId), enabled: authenticated && !!chatId, refetchInterval: chatSending ? 1_000 : 15_000})
  const [text, setText] = useState('')
  const send = useMutation({mutationFn: ({content, attached}: {content: string; attached: ChatAttachment[]}) => api.send(content, chatId, attached), onSuccess: () => {
    setText('')
    setAttachments([])
    setAttachmentError('')
    void queryClient.invalidateQueries({queryKey:['trading-chats']})
    void query.refetch()
  }, onError: () => { void query.refetch() }, onSettled: () => setChatSending(false)})
  const sendMessage = () => {
    if ((text.trim() || attachments.length) && chatId && !send.isPending) {
      setChatSending(true)
      send.mutate({content: text.trim() || 'Please review the attached text evidence.', attached: attachments})
    }
  }
  const requestDeleteChat = (chat: {id: string; title: string}) => {
    if (chatSending || send.isPending || deleteChat.isPending) return
    if (window.confirm(`Delete “${chat.title}” and its saved conversation history? This cannot be undone.`)) {
      deleteChat.mutate(chat.id)
    }
  }
  const addAttachments = async (files: FileList | null) => {
    if (!files?.length) return
    setAttachmentError('')
    if (attachments.length + files.length > 4) { setAttachmentError('Attach up to four text files per message.'); return }
    const allowed = /\.(txt|md|csv)$/i
    const next: ChatAttachment[] = []
    for (const file of Array.from(files)) {
      if (!allowed.test(file.name) || file.size > 20_000) { setAttachmentError('Attachments must be .txt, .md, or .csv files under 20 KB each.'); return }
      next.push({name: file.name, content: await file.text()})
    }
    if ([...attachments, ...next].reduce((sum, item) => sum + item.content.length, 0) > 50_000) {
      setAttachmentError('Combined attachment text cannot exceed 50 KB.')
      return
    }
    setAttachments(current => [...current, ...next])
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    sendMessage()
  }
  if (walletLoading) return <div className="page-content"><div className="empty-state"><div className="loading-orbit"/><span>Checking wallet identity…</span></div></div>
  if (!authenticated) return <div className="page-content"><PageHeading eyebrow="PRIVATE INTELLIGENCE WORKSPACE" title="Trading Room">Verify control of a supported wallet to open private conversations and your $10,000 USD paper portfolio.</PageHeading><WalletGate/></div>

  const visibleChats = (chatsQuery.data?.chats ?? []).filter(chat => chat.title.toLowerCase().includes(chatSearch.trim().toLowerCase()))
  const activeChat = chatsQuery.data?.chats.find(chat => chat.id === chatId)
  return <div className="page-content trading-chat-page">
    <header className="trading-chat-top">
      <div className="trading-chat-title">
        <span className="eyebrow">CLAW INTEL · TRADING ROOM</span>
        <h1>Trading Room</h1>
        <p>Work with six agents using current market evidence and your private paper portfolio.</p>
      </div>
      <div className="trading-chat-actions">
        <span className="paper-balance-pill"><WalletCards size={14}/>{Number(paper.data?.virtual_usdc_balance ?? 10000).toLocaleString(undefined,{maximumFractionDigits:2})} USDC <small>VIRTUAL</small></span>
        <button className={toolsOpen ? 'tools-toggle active' : 'tools-toggle'} onClick={() => setToolsOpen(value => !value)}><Zap size={14}/>{toolsOpen ? 'Hide tools' : 'Trading tools'}</button>
      </div>
    </header>
    <div className={toolsOpen ? 'trading-grid chat-layout tools-visible' : 'trading-grid chat-layout'}>
      <aside className="panel chat-history">
        <div className="chat-history-heading"><span>Chats</span><button className="new-chat-icon" aria-label="Start a new chat" title="New chat" onClick={() => newChat.mutate()} disabled={newChat.isPending}><MessageCircle size={16}/><span>＋</span></button></div>
        <button className="new-chat-button" onClick={() => newChat.mutate()} disabled={newChat.isPending}>＋ New chat</button>
        <label className="chat-search"><Search size={14}/><input aria-label="Search chats" placeholder="Search chats" value={chatSearch} onChange={event => setChatSearch(event.target.value)}/></label>
        <div className="chat-history-list">
          {visibleChats.map(chat => <div key={chat.id} className={`chat-entry ${chat.id === chatId ? 'active' : ''}`}>
            <button className="chat-entry-select" onClick={() => setChatId(chat.id)} title={chat.title}><MessageCircle size={14}/><span>{chat.title}</span></button>
            <button className="chat-delete" aria-label={`Delete chat ${chat.title}`} title="Delete chat" disabled={chatSending || send.isPending || deleteChat.isPending} onClick={() => requestDeleteChat(chat)}><Trash2 size={14}/></button>
          </div>)}
          {!visibleChats.length && <div className="chat-history-empty">{chatSearch ? 'No matching chats' : 'Your conversations will appear here'}</div>}
        </div>
        {chatsQuery.error && <ErrorCard message={chatsQuery.error.message}/>}
        {newChat.error && <ErrorCard message={newChat.error.message}/>}
        {deleteChat.error && <ErrorCard message={deleteChat.error.message}/>}
      </aside>
      <section className="panel conversation-panel trading-convo">
        <div className="chat-thread-header">
          <div><span className="chat-thread-title">{activeChat?.title ?? 'New conversation'}</span><span className="chat-thread-subtitle">Six agents · private wallet account</span></div>
          <span className="private-tag"><ShieldCheck size={13}/> PRIVATE</span>
        </div>
        <div className="feed-scroll">
          {!chatId ? <div className="chat-start"><div className="chat-start-icon"><Bot size={25}/></div><h2>What should we look at?</h2><p>Ask Nova to inspect a token or bring a market question to the full team.</p><div className="chat-suggestions"><button onClick={() => setText('Paste a token address and have Nova check all available details.')}>Check a token address</button><button onClick={() => setText('Ask the team to assess current market risks.')}>Review market risks</button><button onClick={() => setText('@makto review my paper portfolio and explain the main risks')}>Review paper portfolio</button></div></div>
            : query.error ? <ErrorCard message={query.error.message}/>
            : query.isLoading ? <AgentMessageFeed loading={true}/>
            : query.data?.messages.length ? <AgentMessageFeed messages={query.data.messages} loading={false} roundtable/>
            : <div className="chat-start"><div className="chat-start-icon"><Bot size={25}/></div><h2>What should we look at?</h2><p>Ask Nova to inspect a token or bring a market question to the full team.</p><div className="chat-suggestions"><button onClick={() => setText('Paste a token address and have Nova check all available details.')}>Check a token address</button><button onClick={() => setText('Ask the team to assess current market risks.')}>Review market risks</button><button onClick={() => setText('@makto review my paper portfolio and explain the main risks')}>Review paper portfolio</button></div></div>}
          {streamingMessage?.chat_id === chatId && <StreamingAgentMessage agentId={streamingMessage.agent_id}/>}
          {attachmentError && <div className="inline-error" role="alert">{attachmentError}</div>}
          {send.error && <ErrorCard message={send.error.message}/>}
        </div>
        <div className="composer-wrap">
          <div className="mention-row"><span>MENTION AN AGENT</span>{['Nova','Atlas','Vega','Echo','Orion','Makto'].map(name => <button key={name} disabled={send.isPending || !chatId} onClick={() => setText(value => value + (value ? ' ' : '') + '@' + name.toLowerCase() + ' ')}>@{name}</button>)}</div>
          <form className="composer" onSubmit={submit}>
            <textarea aria-label="Message the Trading Room" placeholder="Chat naturally with the team. Example: Makto, buy $25 of <address> on Base, sell 10 of my TOKEN on Solana, or swap 2 TOKEN for USDC." rows={2} value={text} onChange={event => setText(event.target.value)} onKeyDown={event => {if(event.key === 'Enter' && !event.shiftKey){event.preventDefault(); sendMessage()}}}/>
          <div className="composer-bottom"><span>{send.isPending ? 'Agents are taking turns…' : 'Makto can place explicit paper buys, sells, and swaps from chat using fresh provider marks.'}</span><label className="attachment-button" title="Attach text evidence"><Paperclip size={15}/><input aria-label="Attach a text file" type="file" accept=".txt,.md,.csv,text/plain,text/markdown,text/csv" multiple disabled={send.isPending || attachments.length >= 4} onChange={event => {void addAttachments(event.target.files); event.currentTarget.value = ''}}/></label><button className="send-button" aria-label="Send message to all agents" disabled={(!text.trim() && !attachments.length) || !chatId || send.isPending}><Send size={16}/></button></div>
            {attachments.length > 0 && <div className="attachment-list composer-attachments">{attachments.map(item => <button type="button" className="attachment-chip" key={item.name} onClick={() => setAttachments(current => current.filter(candidate => candidate.name !== item.name))} title="Remove attachment"><Paperclip size={12}/>{item.name}<X size={12}/></button>)}</div>}
          </form>
        </div>
      </section>
      {toolsOpen && <aside className="right-rail trading-tools-panel"><div className="panel tools-panel-header"><div><span>Virtual trading controls</span><button onClick={() => setToolsOpen(false)} aria-label="Close trading tools"><X size={15}/></button></div></div><div className="panel wallet-card"><div className="panel-header"><div><span className="panel-title">Zecto Virtual Wallet</span><span className="panel-subtitle">One-time allocation per verified wallet account</span></div><span className="wallet-check"><Check size={14}/></span></div><div className="balance-label">VIRTUAL USDC BALANCE</div><div className="balance-number">{Number(paper.data?.virtual_usdc_balance ?? 10000).toLocaleString(undefined,{maximumFractionDigits:2})} USDC</div><div className="wallet-address">{paper.data?.cash_usd ? Number(paper.data.cash_usd).toLocaleString(undefined,{style:'currency',currency:'USD'}) : "USDC balance unavailable"}</div><div className="wallet-address">Paper trades only · no blockchain transaction is submitted.</div><div className="wallet-actions"><button className="secondary-button" disabled title="Sending is unavailable in the virtual wallet">Send</button><button className="secondary-button" disabled title="Receiving is unavailable in the virtual wallet">Receive</button></div></div><PaperOrderPanel portfolio={paper.data} onComplete={() => {void queryClient.invalidateQueries({queryKey:['paper-portfolio']})}}/><VirtualSwapPanel portfolio={paper.data} onComplete={() => {void queryClient.invalidateQueries({queryKey:["paper-portfolio"]})}}/></aside>}
    </div>
  </div>
}

function PaperOrderPanel({portfolio, onComplete, initialSide = 'buy', initialChain, initialAddress}: {portfolio?: PaperPortfolio; onComplete: () => void; initialSide?: 'buy'|'sell'; initialChain?: string; initialAddress?: string}) {
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const [chain, setChain] = useState(initialChain ?? params.get('chain') ?? 'ethereum')
  const [address, setAddress] = useState(initialAddress ?? params.get('address') ?? '')
  const [side, setSide] = useState<'buy'|'sell'>(initialSide)
  const initialHolding=portfolio?.positions.find(item=>item.chain===(initialChain??params.get('chain')??'ethereum')&&item.token_address.toLowerCase()===(initialAddress??params.get('address')??'').toLowerCase())
  const [amount, setAmount] = useState(initialSide==='sell'&&initialHolding?String(initialHolding.quantity):'100')
  const [lookup, setLookup] = useState<TokenLookup | null>(null)
  const queryClient = useQueryClient()
  const search = useMutation({mutationFn: () => api.tokenLookup(chain, address.trim()), onSuccess: result => setLookup(result)})
  const submit = useMutation({mutationFn: () => api.paperOrder({chain, token_address: address.trim(), side, amount_usd: side==='sell'?Number(amount)*Number(lookup?.asset.price_usd??0):Number(amount), idempotency_key: crypto.randomUUID()}), onSuccess: result => {void queryClient.invalidateQueries({queryKey:['paper-portfolio']}); onComplete(); setLookup(null); setNotice(result.replayed ? 'Order was already recorded.' : `${side === 'buy' ? 'Buy' : 'Sell'} recorded at the observed provider price.`)}})
  const [notice, setNotice] = useState('')
  const setChainAndClear = (value: string) => {setChain(value); setLookup(null); setNotice('')}
  const held = portfolio?.positions.find(item => item.chain === chain && item.token_address.toLowerCase() === address.trim().toLowerCase())
  return <section className="panel quote-panel">
    <div className="eyebrow"><Activity size={13}/> USER APPROVED VIRTUAL ORDER</div><h3>Review an order</h3>
    <label className="field-label" htmlFor="paper-chain">NETWORK</label><input id="paper-chain" list="dex-network-ids" value={chain} onChange={event => setChainAndClear(event.target.value)} placeholder="ethereum, base, polygon…" autoComplete="off"/><datalist id="dex-network-ids"><option value="ethereum"/><option value="bsc"/><option value="base"/><option value="solana"/><option value="polygon"/><option value="arbitrum"/><option value="optimism"/><option value="avalanche"/><option value="fantom"/><option value="zksync"/><option value="linea"/><option value="scroll"/><option value="mantle"/><option value="blast"/><option value="cronos"/><option value="sonic"/></datalist>
    <label className="field-label" htmlFor="paper-address">TOKEN CONTRACT / MINT</label><input id="paper-address" value={address} onChange={event => {setAddress(event.target.value); setLookup(null)}} placeholder={chain === 'solana' ? 'Solana token mint address' : '0x…'} autoComplete="off" spellCheck={false}/>
    <button className="secondary-button full" disabled={search.isPending || !address.trim()} onClick={() => search.mutate()}>{search.isPending ? 'Checking market source…' : 'Review live market evidence'}<ChevronRight size={15}/></button>
    {search.error && <ErrorCard message={(search.error as Error).message}/>}
    {lookup && <><div className="quote-review"><div className="quote-title"><span><CheckCircle2 size={14}/> {lookup.asset.symbol} · {lookup.asset.chain}</span><span className="sim-tag">LIVE DATA</span></div><div className="quote-line"><span>Price</span><b>{lookup.asset.price_usd ? `$${Number(lookup.asset.price_usd).toPrecision(8)}` : 'Unavailable'}</b></div><div className="quote-line"><span>Liquidity</span><b>{lookup.asset.liquidity_usd ? `$${Number(lookup.asset.liquidity_usd).toLocaleString()}` : 'Unavailable'}</b></div><div className="quote-line"><span>Provider</span><b>{lookup.asset.source}</b></div><div className="quote-expiry"><Clock3 size={12}/> Observed {new Date(lookup.asset.provider_retrieved_at).toLocaleString()}</div><small>{lookup.asset.limitations}</small></div>
      <label className="field-label" htmlFor="paper-side">ACTION</label><select id="paper-side" value={side} onChange={event => setSide(event.target.value as 'buy'|'sell')}><option value="buy">Buy with USDC</option><option value="sell">Sell for USDC</option></select>
      <label className="field-label" htmlFor="paper-amount">{side==='buy'?'SPEND · USDC':'AMOUNT TO SELL · TOKEN UNITS'}</label><input id="paper-amount" type="number" min="0.00000001" max={side==='buy'?Math.max(0,Number(portfolio?.cash_usd??10000)):Number(held?.quantity??0)} step="any" value={amount} onChange={event => setAmount(event.target.value)}/>
      {side === 'sell' && <div className="quote-expiry">Available: {held ? `${Number(held.quantity).toPrecision(8)} ${held.symbol} · estimated proceeds $${(Number(amount)*Number(lookup.asset.price_usd??0)).toLocaleString(undefined,{maximumFractionDigits:2})} USDC` : 'none'}</div>}
      <button className="primary-button wide" disabled={submit.isPending || !lookup.asset.price_usd || Number(amount) <= 0 || (side === 'buy' && Number(amount) > Number(portfolio?.cash_usd ?? 0)) || (side==='sell'&&(!held||Number(amount)>Number(held.quantity)))} onClick={() => submit.mutate()}>{submit.isPending ? 'Recording order…' : `Confirm ${side}`}<ChevronRight size={15}/></button>
      </>}
    {(submit.error || notice) && <div className={submit.error ? 'inline-error' : 'success-note'}>{submit.error ? (submit.error as Error).message : notice}</div>}
    <div className="quote-footnote">Virtual funds only. Fills use the latest observed USD price; fees, slippage, latency and liquidity impact are not modeled. Nothing is sent to a blockchain.</div>
  </section>
}

function VirtualSwapPanel({onComplete, portfolio}: {onComplete: () => void; portfolio?: PaperPortfolio}) {
  const [sourceId,setSourceId]=useState('cash'),[targetId,setTargetId]=useState('custom'),[targetChain,setTargetChain]=useState('solana'),[targetAddress,setTargetAddress]=useState(''),[quantity,setQuantity]=useState(''),[notice,setNotice]=useState(''),[quote,setQuote]=useState<{from:string;to:string;sourcePrice:number;targetPrice:number;receive:number;sourceAt:string;targetAt:string}|null>(null)
  const sourceAsset=portfolio?.positions.find(item=>`${item.chain}:${item.token_address}`===sourceId)
  const targetAsset=portfolio?.positions.find(item=>`${item.chain}:${item.token_address}`===targetId)
  const fromCash=sourceId==='cash'
  const toCash=targetId==='wallet-cash'
  const sourceChain=fromCash?(targetAsset?.chain??targetChain):(sourceAsset?.chain??'')
  const sourceAddress=fromCash?`paper:usdc:${sourceChain}`:sourceAsset?.token_address??''
  const resolvedTargetChain=targetAsset?.chain??(toCash?(sourceAsset?.chain??targetChain):targetChain)
  const resolvedTargetAddress=targetAsset?.token_address??(toCash?`paper:usdc:${resolvedTargetChain}`:targetAddress)
  const client=useQueryClient()
  const quoteMutation=useMutation({mutationFn:async()=>{const to=toCash?null:await api.tokenLookup(resolvedTargetChain,resolvedTargetAddress);const from=fromCash?null:await api.tokenLookup(sourceChain,sourceAddress);const fromPrice=fromCash?1:Number(from?.asset.price_usd),toPrice=toCash?1:Number(to?.asset.price_usd),fromAt=fromCash?new Date().toISOString():from!.asset.provider_retrieved_at,toAt=toCash?new Date().toISOString():to!.asset.provider_retrieved_at;if(!Number.isFinite(fromPrice)||!Number.isFinite(toPrice)||fromPrice<=0||toPrice<=0)throw new Error('A fresh price is unavailable for one of these assets.');if(Date.now()-Date.parse(fromAt)>300_000||Date.now()-Date.parse(toAt)>300_000)throw new Error('A quote price is older than five minutes. Refresh and try again.');return {from:fromCash?'USDC':from!.asset.symbol,to:toCash?'USDC':to!.asset.symbol,sourcePrice:fromPrice,targetPrice:toPrice,receive:Number(quantity)*fromPrice/toPrice,sourceAt:fromAt,targetAt:toAt}},onSuccess:value=>{setQuote(value);setNotice('')},onError:error=>{setQuote(null);setNotice(error.message)}})
  const swap=useMutation({mutationFn:async()=>{if(toCash){const result=await api.paperOrder({chain:sourceChain,token_address:sourceAddress,side:'sell',amount_usd:Number(quantity)*Number(quote?.sourcePrice??0),idempotency_key:crypto.randomUUID()});return {replayed:result.replayed,target_quantity:String(Number(quantity)*Number(quote?.sourcePrice??0))}}return api.paperSwap({source_chain:sourceChain,source_token_address:sourceAddress,target_chain:resolvedTargetChain,target_token_address:resolvedTargetAddress,source_quantity:Number(quantity),idempotency_key:crypto.randomUUID(),from_virtual_usdc:fromCash})},onSuccess:result=>{setNotice(result.replayed?'This swap was already recorded.':`Swap completed at provider marks. Received ${Number(result.target_quantity??0).toPrecision(8)} ${quote?.to??'tokens'}.`);void client.invalidateQueries({queryKey:['paper-portfolio']});onComplete()},onError:error=>setNotice(error.message)})
  const available=fromCash?Number(portfolio?.virtual_usdc_balance??0):Number(sourceAsset?.quantity??0)
  const setSource=(value:string)=>{setSourceId(value);setQuote(null);setNotice('')}
  const setReceive=(value:string)=>{setTargetId(value);setQuote(null);setNotice('')}
  const usableSource=!!sourceAddress&&(!fromCash||sourceChain===resolvedTargetChain)&&!(fromCash&&toCash)
  return <section className="panel quote-panel"><div className="eyebrow"><Activity size={13}/> WALLET SWAP</div><h3>Swap assets</h3><label className="field-label" htmlFor="swap-from-asset">YOU PAY</label><select id="swap-from-asset" value={sourceId} onChange={e=>setSource(e.target.value)}><option value="cash">USDC · Available {Number(portfolio?.virtual_usdc_balance??0).toLocaleString()}</option>{(portfolio?.positions??[]).map(asset=><option key={`${asset.chain}:${asset.token_address}`} value={`${asset.chain}:${asset.token_address}`}>{asset.symbol} · {asset.chain} · {Number(asset.quantity).toPrecision(8)} available</option>)}</select><label className="field-label" htmlFor="swap-pay-amount">AMOUNT</label><div className="swap-amount-input"><input id="swap-pay-amount" type="number" min="0" max={available} step="any" value={quantity} onChange={e=>{setQuantity(e.target.value);setQuote(null)}}/><span>{fromCash?'USDC':sourceAsset?.symbol}</span><button type="button" onClick={()=>{setQuantity(String(available));setQuote(null)}} disabled={available<=0}>MAX</button></div><div className="swap-available">Available {available.toLocaleString(undefined,{maximumFractionDigits:8})} {fromCash?'USDC':sourceAsset?.symbol}</div><div className="swap-direction-mark"><ArrowDownUp size={17}/></div><label className="field-label" htmlFor="swap-to-asset">YOU RECEIVE</label><select id="swap-to-asset" value={targetId} onChange={e=>setReceive(e.target.value)}><option value="custom">Find token by contract / mint</option><option value="wallet-cash">USDC · Wallet balance</option>{(portfolio?.positions??[]).map(asset=><option key={`${asset.chain}:${asset.token_address}`} value={`${asset.chain}:${asset.token_address}`}>{asset.symbol} · {asset.chain}</option>)}</select>{targetId==='custom'&&<><label className="field-label">NETWORK</label><input list="dex-swap-network-ids" value={targetChain} onChange={e=>{setTargetChain(e.target.value);setQuote(null)}} placeholder="ethereum, base, polygon…" autoComplete="off"/><datalist id="dex-swap-network-ids"><option value="ethereum"/><option value="bsc"/><option value="base"/><option value="solana"/><option value="polygon"/><option value="arbitrum"/><option value="optimism"/><option value="avalanche"/><option value="fantom"/><option value="zksync"/><option value="linea"/><option value="scroll"/><option value="mantle"/><option value="blast"/><option value="cronos"/><option value="sonic"/></datalist><label className="field-label">TOKEN CONTRACT / MINT</label><input value={targetAddress} onChange={e=>{setTargetAddress(e.target.value);setQuote(null)}} placeholder="Paste the token you want to receive" autoComplete="off" spellCheck={false}/></>}{quote&&<div className="swap-quote-review"><div><span>You pay</span><b>{Number(quantity).toLocaleString()} {quote.from}</b></div><div><span>You receive (estimate)</span><b>{quote.receive.toPrecision(8)} {quote.to}</b></div><div><span>Rate</span><b>1 {quote.from} = {(quote.sourcePrice/quote.targetPrice).toPrecision(8)} {quote.to}</b></div><small>Prices are provider marks. Price impact, execution route, fees and slippage are not modeled.</small></div>}{!quote?<button className="primary-button wide" disabled={quoteMutation.isPending||!usableSource||!resolvedTargetAddress||!Number(quantity)||Number(quantity)>available||sourceId===targetId} onClick={()=>quoteMutation.mutate()}>{quoteMutation.isPending?'Fetching live quote…':'Review quote'}<ChevronRight size={15}/></button>:<button className="primary-button wide" disabled={swap.isPending||!quote} onClick={()=>swap.mutate()}>{swap.isPending?'Recording swap…':'Confirm swap'}<ChevronRight size={15}/></button>}{(notice||quoteMutation.error||swap.error)&&<div className={(quoteMutation.error||swap.error)?'inline-error':'success-note'}>{notice}</div>}<small>Tokens are selected from your wallet assets. For an unheld token, enter its contract or mint; both sides need a fresh exact market match. This records a paper swap; no on-chain transaction is sent.</small></section>
}

function Investigations() {
  const [room, setRoom] = useState<'autonomous'|'trading'>('autonomous')
  const auth = useQuery({queryKey:['wallet-auth'],queryFn:api.walletAuth,retry:false})
  const privateAccess = room === 'trading'
  const query = useQuery({queryKey:['investigations',room],queryFn:()=>api.investigations(room),refetchInterval:20000,enabled:!privateAccess || !!auth.data?.authenticated})
  const [filter, setFilter] = useState('')
  const entries = (query.data?.investigations ?? []).filter(item => `${item.title} ${item.chain} ${item.token_address} ${item.status}`.toLowerCase().includes(filter.toLowerCase()))
  const tabs = <div className="investigation-tabs" role="tablist" aria-label="Investigation department"><button role="tab" aria-selected={room==='autonomous'} className={room==='autonomous'?'active':''} onClick={()=>setRoom('autonomous')}>War Room</button><button role="tab" aria-selected={room==='trading'} className={room==='trading'?'active':''} onClick={()=>setRoom('trading')}>My investigations</button></div>
  return <div className="page-content"><PageHeading eyebrow={privateAccess?'PRIVATE ACCOUNT RECORDS':'PUBLIC ANALYSIS RECORDS'} title="Investigations">Review the saved agent findings and debate. Provider observations are processed in memory and discarded.</PageHeading><WarRoomSubnav/>{tabs}{privateAccess && !auth.data?.authenticated ? <WalletGate/> : <><div className="panel records-panel"><div className="panel-header"><div><span className="panel-title">{privateAccess?'Your Trading Room investigations':'War Room investigations'}</span><span className="panel-subtitle">Independent findings, challenges and Orion's conclusion</span></div><label className="search-box"><Search size={14}/><input aria-label="Search investigations" placeholder="Search token or chain" value={filter} onChange={event=>setFilter(event.target.value)}/></label></div>{query.isLoading ? <div className="empty-state"><div className="loading-orbit"/><span>Loading investigations…</span></div> : query.error ? <ErrorCard message={query.error.message}/> : entries.length ? entries.map((item: Investigation, i)=><article className="record-row investigation-row" key={item.id}><div className="record-icon"><ShieldCheck size={17}/></div><div className="record-main"><div><b>{item.title}</b><span className={`investigation-status ${item.status}`}>{item.status.toUpperCase()}</span></div><small>{item.chain} · {item.token_address} · {new Date(item.updated_at).toLocaleString()} · {item.findings.length} findings{item.confidence != null ? ` · Orion confidence ${item.confidence}%` : ''}</small><details className="investigation-findings"><summary>Review findings and debate</summary>{item.findings.map(finding=><div className="finding-row" key={finding.id}><b>{agentNames[finding.agent_id] ?? finding.agent_id} · {finding.phase.replace('_',' ')}</b><p>{finding.content}</p><small>Round {finding.round} · evidence is processed in memory</small></div>)}</details></div><span className="record-index">{String(entries.length-i).padStart(2,'0')}</span></article>) : <div className="empty-state compact"><span>No investigation records match this search.</span><Link className="text-link" to={privateAccess?'/trading':'/war-room'}>Open {privateAccess?'Trading Room':'War Room'} <ChevronRight size={14}/></Link></div>}</div>
    </>}</div>}


function DashboardPage({authenticated, welcome, onWelcomeSeen}: {authenticated: boolean; welcome: boolean; onWelcomeSeen: () => void}) {
  const client = useQueryClient()
  const [tab, setTab] = useState<'home'|'history'|'intel'>('home')
  const [tradeMode, setTradeMode] = useState<'buy'|'sell'|'swap'|null>(null)
  const [tradeAsset,setTradeAsset]=useState<{chain:string;address:string}|null>(null)
  const [sendOpen, setSendOpen] = useState(false)
  const [receiveOpen, setReceiveOpen] = useState(false)
  const [sendChain, setSendChain] = useState('ethereum')
  const [sendAddress, setSendAddress] = useState('')
  const [sendAmount, setSendAmount] = useState('')
  const [transferError, setTransferError] = useState('')
  const query = useQuery({queryKey:['paper-portfolio'],queryFn:api.paperPortfolio,enabled:authenticated,refetchInterval:20_000})
  const intel = useQuery({queryKey:['intel-tokens'],queryFn:api.intelTokens,enabled:authenticated&&tab==='intel',refetchInterval:60_000})
  const transfers = useQuery({queryKey:['paper-transfers'],queryFn:api.paperTransfers,enabled:authenticated&&tab==='history'})
  const receive = useQuery({queryKey:['paper-receive'],queryFn:api.paperReceive,enabled:authenticated&&receiveOpen})
  const sendTransfer = useMutation({mutationFn:api.paperTransfer,onSuccess:()=>{setTransferError('');setSendAmount('');setSendAddress('');setSendOpen(false);void query.refetch();void client.invalidateQueries({queryKey:['paper-transfers']})},onError:error=>setTransferError(error.message)})
  const data=query.data
  useEffect(()=>{if(welcome)onWelcomeSeen()},[welcome,onWelcomeSeen])
  const money=(value:string|null|undefined)=>value==null?'—':Number(value).toLocaleString(undefined,{style:'currency',currency:'USD',maximumFractionDigits:2})
  const complete=()=>{setTradeMode(null);setTradeAsset(null);void query.refetch()}
  const openAssetTrade=(side:'buy'|'sell',chain:string,address:string)=>{setTradeAsset({chain,address});setTradeMode(side)}
  const historyItems=[...(data?.orders??[]).map(order=>({kind:'order' as const,created_at:order.created_at,order})),...(transfers.data?.transfers??[]).map(transfer=>({kind:'transfer' as const,created_at:transfer.created_at,transfer}))].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at))
  return <div className="page-content dashboard-content">
    <PageHeading eyebrow="YOUR PAPER WALLET · LIVE MARKET MARKS" title="Dashboard">Review your Zecto paper portfolio and its market marks. These balances are virtual and are separate from assets held by your connected wallet.</PageHeading>
    {welcome&&<div className="welcome-banner"><span className="welcome-check"><CheckCircle2 size={19}/></span><div><b>Welcome to Zecto</b><small>The Home of Agentic trade and market analysis</small></div></div>}
    <div className="wallet-tabs" role="tablist" aria-label="Dashboard sections">{([['home','Home'],['history','History'],['intel','Intel Tokens']] as const).map(([id,label])=><button key={id} role="tab" aria-selected={tab===id} className={tab===id?'active':''} onClick={()=>setTab(id)}>{label}{id==='intel'&&intel.data?.tokens.length? <small>{intel.data.tokens.length}</small>:null}</button>)}</div>
    {query.error&&<ErrorCard message={(query.error as Error).message}/>}
    {tab==='home'&&<>
      <section className="wallet-hero"><div className="wallet-hero-top"><div><span className="wallet-overline">{data?.positions.length&&!data?.valuation.available?'WALLET VALUE UNAVAILABLE':'TOTAL WALLET VALUE'} <i className="live-price-dot"/> LIVE</span><h2>{data?.valuation.total_equity_usd?money(data.valuation.total_equity_usd):data?.positions.length?'—':money(data?.cash_usd)}</h2><small>Paper portfolio · values update from live market sources</small></div><div className="wallet-network"><span className="wallet-network-dot"/>Zecto Paper Wallet</div></div>
        <div className="wallet-balance-row"><div><small>AVAILABLE</small><b>{money(data?.cash_usd)} <em>USDC</em></b></div><div><small>ASSETS</small><b>{data?.positions.length??0}</b></div><div><small>UNREALIZED P/L</small><b className={Number(data?.valuation.unrealized_pnl_usd??0)>=0?'positive':'negative'}>{money(data?.valuation.unrealized_pnl_usd)}</b></div></div>
        <div className="wallet-action-row"><button onClick={()=>setTradeMode('buy')}><ArrowUpRight size={16}/>Buy</button><button onClick={()=>setTradeMode('sell')}><ArrowUpRight size={16} className="sell-arrow"/>Sell</button><button onClick={()=>setTradeMode('swap')}><Activity size={16}/>Swap</button><button onClick={()=>{setTransferError('');setSendOpen(value=>!value);setReceiveOpen(false)}}><Send size={16}/>Send</button><button onClick={()=>{setReceiveOpen(value=>!value);setSendOpen(false)}}><Plus size={16}/>Receive</button></div>
        {sendOpen&&<form className="paper-transfer-form" onSubmit={event=>{event.preventDefault();setTransferError('');sendTransfer.mutate({chain:sendChain,recipient_address:sendAddress,amount_usdc:Number(sendAmount),idempotency_key:crypto.randomUUID()})}}><b>Send USDC paper balance to a Zecto account</b><p>Internal paper-ledger transfer only. No blockchain transaction is created.</p><select aria-label="Recipient network" value={sendChain} onChange={event=>setSendChain(event.target.value)}><option value="ethereum">Ethereum</option><option value="bsc">BNB Smart Chain</option><option value="base">Base</option><option value="solana">Solana</option></select><input required aria-label="Recipient wallet address" placeholder="Recipient verified wallet address" value={sendAddress} onChange={event=>setSendAddress(event.target.value)}/><input required aria-label="Amount in USDC" type="number" min="0.000001" max="10000" step="0.000001" placeholder="Amount in USDC" value={sendAmount} onChange={event=>setSendAmount(event.target.value)}/><button className="secondary-button" disabled={sendTransfer.isPending||!sendAmount||Number(sendAmount)>Number(data?.virtual_usdc_balance??0)}>{sendTransfer.isPending?'Sending…':'Review & send'}</button>{transferError&&<small className="inline-error">{transferError}</small>}</form>}
        {receiveOpen&&<div className="paper-transfer-form"><b>Receive USDC paper balance</b>{receive.isLoading?<p>Loading your verified account address…</p>:receive.error?<p className="inline-error">{(receive.error as Error).message}</p>:receive.data&&<><p>Share this verified Zecto identity with another Zecto user. This is not a deposit address.</p><code>{receive.data.address}</code><small>{receive.data.chain.toUpperCase()} · internal paper balance only</small><button type="button" className="secondary-button" onClick={()=>void navigator.clipboard?.writeText(receive.data!.address)}>Copy address</button></>}</div>}
      </section>
      <div className="dashboard-columns"><section className="panel records-panel"><div className="panel-header"><div><span className="panel-title">Your assets</span><span className="panel-subtitle">Fresh token price observations · asset details are provider sourced</span></div><span className="record-count">{(data?.positions.length??0)+1} ASSETS</span></div><div className="asset-row"><div className="asset-logo usdc-asset-logo">$</div><div className="asset-main"><b>USD Coin<small>USDC · Wallet balance</small></b><span>{Number(data?.virtual_usdc_balance??0).toLocaleString(undefined,{maximumFractionDigits:2})} USDC available · $1.00</span></div><div className="asset-value"><b>{money(data?.virtual_usdc_balance)}</b><small>Available balance</small><small>Stablecoin</small></div><div className="asset-quick-actions"><button onClick={()=>setTradeMode('buy')}>Buy</button><button onClick={()=>setTradeMode('swap')}>Swap</button></div></div>{data?.positions.length?data.positions.map((p,i)=><div className="asset-row" key={`${p.chain}-${p.token_address}-${i}`}><div className="asset-logo">{p.logo_url?<img src={p.logo_url} alt="" loading="lazy"/>:p.symbol.slice(0,1)}</div><div className="asset-main"><b>{p.name||p.symbol}<small>{p.symbol} · {p.chain}</small></b><span>{Number(p.quantity).toPrecision(8)} tokens · {p.current_price_usd?money(p.current_price_usd):'price unavailable'} · ATH {p.ath_usd?money(p.ath_usd):'not indexed'}</span></div><div className="asset-value"><b>{money(p.market_value_usd)}</b><small className={Number(p.unrealized_pnl_usd??0)>=0?'positive':'negative'}>{p.unrealized_pnl_usd?`${Number(p.unrealized_pnl_usd)>=0?'+':''}${money(p.unrealized_pnl_usd)}`:'Mark unavailable'}</small><small>24h {p.price_change_24h_pct==null?'—':`${Number(p.price_change_24h_pct)>=0?'+':''}${Number(p.price_change_24h_pct).toFixed(2)}%`}</small></div><div className="asset-quick-actions"><button onClick={()=>openAssetTrade('buy',p.chain,p.token_address)}>Buy</button><button onClick={()=>openAssetTrade('sell',p.chain,p.token_address)}>Sell</button><button onClick={()=>setTradeMode('swap')}>Swap</button></div></div>):null}</section></div>
      <div className="settings-note"><ShieldCheck size={15}/><span>$10,000 virtual USDC allocation. Buy, sell, and swap use provider-reported prices; no real transaction is signed or broadcast. Fees, slippage, and market impact are not modeled.</span></div>
    </>}
    {tab==='history'&&<section className="panel records-panel history-panel"><div className="panel-header"><div><span className="panel-title">Transaction history</span><span className="panel-subtitle">Your paper wallet orders, swaps, and internal virtual USDC transfers</span></div></div>{historyItems.map(item=>item.kind==='order'?<div className="trade-row" key={item.order.id}><span className="trade-icon"><ArrowUpRight size={15}/></span><div><b>{item.order.side.toUpperCase()} {item.order.symbol}</b><small>{item.order.chain} · {new Date(item.order.created_at).toLocaleString()} · price observed {new Date(item.order.observed_at).toLocaleTimeString()} · {item.order.source}</small></div><span className="trade-amount">{money(item.order.amount_usd)}</span></div>:<div className="trade-row" key={item.transfer.id}><span className="trade-icon"><Send size={15}/></span><div><b>{item.transfer.direction.toUpperCase()} virtual USDC</b><small>{item.transfer.chain} · {new Date(item.transfer.created_at).toLocaleString()} · {item.transfer.direction==='send'?'To':'From'} {item.transfer.address}</small></div><span className="trade-amount">{money(item.transfer.amount_usdc)}</span></div>)}{!historyItems.length&&<div className="empty-state compact"><span>Your completed paper trades and transfers will appear here.</span></div>}</section>}
    {tab==='intel'&&<section className="panel records-panel intel-panel"><div className="panel-header"><div><span className="panel-title">War Room token intelligence</span><span className="panel-subtitle">Tokens agents analyzed · current live marks refreshed from DexScreener</span></div><button className="icon-button" onClick={()=>void intel.refetch()} aria-label="Refresh intel tokens"><Activity size={16}/></button></div>{intel.isLoading?<div className="empty-state"><div className="loading-orbit"/><span>Loading analyzed tokens and fresh market data…</span></div>:intel.error?<ErrorCard message={(intel.error as Error).message}/>:intel.data?.tokens.length?intel.data.tokens.map(token=><article className="intel-token-row" key={`${token.chain}-${token.token_address}`}><div className="asset-logo">{token.logo_url?<img src={token.logo_url} alt="" loading="lazy"/>:token.symbol.slice(0,1)}</div><div className="intel-token-main"><b>{token.name} <small>{token.symbol} · {token.chain}</small></b><span>{token.token_address}</span><small>Analyzed {new Date(token.analysis_observed_at).toLocaleString()} · {token.analysis_source}</small>{token.agent_view&&<p className="intel-agent-view"><b>{token.agent_id==='orion'?'Orion’s conclusion':'Latest agent view'}{token.agent_confidence?` · ${token.agent_confidence}% confidence`:''}</b>{token.agent_view}<small>Opinion from {token.agent_view_at?new Date(token.agent_view_at).toLocaleString():'stored analysis'}; not a price guarantee.</small></p>}</div><div className="intel-token-market"><b>{token.live_available?money(token.price_usd):'Price unavailable'}</b><small>{token.price_change_24h_pct==null?'24h change unavailable':`${Number(token.price_change_24h_pct)>=0?'+':''}${Number(token.price_change_24h_pct).toFixed(2)}% · 24h`}</small><small>24h volume {money(token.volume_24h_usd)}</small><small>Market cap {money(token.market_cap_usd)}</small><small>ATH {token.ath_usd?`${money(token.ath_usd)}${token.ath_date?` · ${new Date(token.ath_date).toLocaleDateString()}`:''}`:'Not indexed'}</small><small>Liquidity {money(token.liquidity_usd)}</small></div><Link className="text-link" to={`/trading?chain=${encodeURIComponent(token.chain)}&address=${encodeURIComponent(token.token_address)}`}>Trade</Link></article>):<div className="empty-state compact"><span>No live War Room token analyses are recorded yet.</span></div>}{intel.data&&<div className="intel-source-note">{intel.data.source}. Agent judgments are analysis, not a guaranteed price prediction. {intel.data.tokens.some(token=>!token.live_available)&&'Unavailable marks are left blank rather than carried forward.'}</div>}</section>}
    {tradeMode&&<div className="wallet-trade-modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget){setTradeMode(null);setTradeAsset(null)}}}><section className="wallet-trade-modal" role="dialog" aria-modal="true" aria-labelledby="wallet-trade-title"><header><div><span className="eyebrow">ZECTO WALLET</span><h2 id="wallet-trade-title">{tradeMode==='swap'?'Swap assets':tradeMode==='buy'?'Buy token':'Sell token'}</h2></div><button className="icon-button" aria-label="Close trade panel" onClick={()=>{setTradeMode(null);setTradeAsset(null)}}><X size={18}/></button></header>{tradeMode==='swap'?<VirtualSwapPanel portfolio={data} onComplete={complete}/>:<PaperOrderPanel key={`${tradeMode}:${tradeAsset?.chain??''}:${tradeAsset?.address??''}`} portfolio={data} initialSide={tradeMode} initialChain={tradeAsset?.chain} initialAddress={tradeAsset?.address} onComplete={complete}/>}</section></div>}
  </div>
}

function WatchlistsPage({authenticated}: {authenticated: boolean}) {
  const client = useQueryClient()
  const query = useQuery({queryKey:['trading-watchlist'], queryFn:api.tradingWatchlist, enabled:authenticated, refetchInterval:30_000, retry:false})
  const [chain, setChain] = useState('ethereum')
  const [address, setAddress] = useState('')
  const [label, setLabel] = useState('')
  const [entryId, setEntryId] = useState('')
  const [condition, setCondition] = useState<'above'|'below'>('above')
  const [threshold, setThreshold] = useState('')
  const [error, setError] = useState('')
  const refresh = () => client.invalidateQueries({queryKey:['trading-watchlist']})
  const add = useMutation({mutationFn:api.addWatchlistEntry, onSuccess:() => {setAddress('');setLabel('');setError('');void refresh()}, onError:e => setError(e.message)})
  const create = useMutation({mutationFn:api.createPriceAlert, onSuccess:() => {setThreshold('');setError('');void refresh()}, onError:e => setError(e.message)})
  const perform = (fn:()=>Promise<unknown>) => {setError('');void fn().then(refresh).catch(e => setError(e.message))}
  if (!authenticated) return <section className="page-content"><PageHeading eyebrow="PERSONAL MARKET MONITOR" title="Watchlists & alerts">Track tokens and get durable in-app notifications when their observed price crosses your level.</PageHeading><WalletGate/></section>
  const data: TradingWatchlist|undefined = query.data
  return <section className="page-content"><PageHeading eyebrow="PERSONAL MARKET MONITOR" title="Watchlists & alerts">Track live token observations and manage price alerts. The monitor checks about every {data?.monitor_interval_seconds ?? 300} seconds; alerts are informational and do not execute trades.</PageHeading><WarRoomSubnav/>
    {error && <ErrorCard message={error}/>} {query.isError && <ErrorCard message={(query.error as Error).message}/>}
    <div className="watchlist-grid"><form className="panel watchlist-form" onSubmit={e => {e.preventDefault();add.mutate({chain,token_address:address.trim(),label:label.trim()})}}><h2>Add a token</h2><label>Network<select value={chain} onChange={e=>setChain(e.target.value)}><option value="ethereum">Ethereum</option><option value="bsc">BNB Chain</option><option value="base">Base</option><option value="solana">Solana</option></select></label><label>Token address<input required value={address} onChange={e=>setAddress(e.target.value)} placeholder="Contract or mint address"/></label><label>Label (optional)<input value={label} onChange={e=>setLabel(e.target.value)} maxLength={80} placeholder="Token name"/></label><button className="primary-button" disabled={add.isPending}><Plus size={16}/>Add token</button></form>
      <form className="panel watchlist-form" onSubmit={e=>{e.preventDefault();if(entryId)create.mutate({watchlist_entry_id:entryId,condition,threshold_usd:Number(threshold)})}}><h2>Create a price alert</h2><label>Watched token<select required value={entryId} onChange={e=>setEntryId(e.target.value)}><option value="">Select a token</option>{data?.entries.map(x=><option key={x.id} value={x.id}>{x.label || `${x.chain} · ${x.token_address.slice(0,12)}…`}</option>)}</select></label><div className="watchlist-inline"><label>Condition<select value={condition} onChange={e=>setCondition(e.target.value as 'above'|'below')}><option value="above">At or above</option><option value="below">At or below</option></select></label><label>USD threshold<input required type="number" min="0.00000001" step="any" value={threshold} onChange={e=>setThreshold(e.target.value)} placeholder="0.00"/></label></div><button className="primary-button" disabled={create.isPending || !data?.entries.length}><Bell size={16}/>Save alert</button></form>
    </div>
    <div className="panel watchlist-panel"><div className="panel-heading"><h2>Watched tokens</h2><span>{data?.entries.length ?? 0} / 50</span></div>{data?.entries.length ? data.entries.map(x=><div className="watchlist-row" key={x.id}><div><b>{x.label || x.chain}</b><small>{x.chain} · {x.token_address}</small></div><button className="icon-button" aria-label="Remove token" onClick={()=>perform(()=>api.deleteWatchlistEntry(x.id))}><Trash2 size={16}/></button></div>):<p className="muted">No tokens in this watchlist yet.</p>}</div>
    <div className="panel watchlist-panel"><div className="panel-heading"><h2>Price alerts</h2><span>{data?.alerts.length ?? 0} / 25</span></div>{data?.alerts.length ? data.alerts.map(a=><div className="watchlist-row" key={a.id}><div><b>{a.condition === 'above'?'At or above':'At or below'} ${a.threshold_usd}</b><small>{a.chain} · {a.token_address} · {a.enabled?(a.is_triggered?'Triggered':'Monitoring'):'Paused'}{a.last_observed_price_usd?` · Last $${a.last_observed_price_usd}`:''}</small></div><div className="watchlist-actions"><button className="secondary-button" onClick={()=>perform(()=>api.setPriceAlertEnabled(a.id,!a.enabled))}>{a.enabled?'Pause':'Resume'}</button><button className="icon-button" aria-label="Delete alert" onClick={()=>perform(()=>api.deletePriceAlert(a.id))}><Trash2 size={16}/></button></div></div>):<p className="muted">No price alerts yet.</p>}</div>
    <div className="panel watchlist-panel"><div className="panel-heading"><h2>Notifications</h2></div>{data?.notifications.length?data.notifications.map(n=><div className="watchlist-row" key={n.id}><div><b>Price threshold reached: ${n.observed_price_usd}</b><small>{n.source} · {new Date(n.observed_at).toLocaleString()}</small></div>{!n.read_at&&<button className="secondary-button" onClick={()=>perform(()=>api.markPriceAlertRead(n.id))}>Mark read</button>}</div>):<p className="muted">Triggered price alerts will appear here.</p>}</div>
  </section>
}

function TelegramPanel() {
  const client = useQueryClient()
  const auth = useQuery({queryKey:['wallet-auth'], queryFn:api.walletAuth})
  const status = useQuery({queryKey:['telegram-status'], queryFn:api.telegramStatus, enabled:!!auth.data?.authenticated})
  const [link, setLink] = useState<{url:string;expires_at:string}|null>(null)
  const [error, setError] = useState('')
  const create = useMutation({mutationFn:api.createTelegramLink, onSuccess:value=>{setLink(value);setError('')}, onError:e=>setError(e.message)})
  const unlink = useMutation({mutationFn:api.unlinkTelegram, onSuccess:()=>{setLink(null);void client.invalidateQueries({queryKey:['telegram-status']})}, onError:e=>setError(e.message)})
  return <section className="panel settings-panel"><div className="panel-header"><div><span className="panel-title">Telegram notifications</span><span className="panel-subtitle">Link a Telegram chat for price-alert notifications. Linking never authorizes or executes trades.</span></div><MessageCircle size={17}/></div>{!auth.data?.authenticated?<div className="settings-note"><CircleAlert size={15}/><span>Connect and verify a wallet before linking Telegram.</span></div>:<><div className="provider-row"><div><b>{status.data?.linked?'Linked Telegram chat':'Telegram account'}</b><small>{status.data?.linked?(status.data.username?`@${status.data.username}`:'Private Telegram chat'):status.data?.mode==='polling'?'Local Telegram long polling is active.':status.data?.configured?'Telegram webhook is ready.':'Telegram bot is not configured'}</small></div><span className={status.data?.linked?'provider-on':'provider-off'}>{status.data?.linked?'Linked':status.data?.configured?'Ready':'Setup needed'}</span></div>{status.data?.linked?<button className="secondary-button" onClick={()=>unlink.mutate()} disabled={unlink.isPending}>Unlink Telegram</button>:<button className="secondary-button" onClick={()=>create.mutate()} disabled={create.isPending||!status.data?.configured}>{create.isPending?'Creating link…':'Create one-time link'}</button>}{link&&<div className="settings-note"><a href={link.url} target="_blank" rel="noreferrer">Open Telegram to link account</a><span> Link expires {new Date(link.expires_at).toLocaleTimeString()}.</span></div>}{error&&<ErrorCard message={error}/>} {status.error&&<ErrorCard message={(status.error as Error).message}/>}</>}</section>
}

function SettingsPage() {
  return <div className="page-content settings-content"><PageHeading eyebrow="WALLET PREFERENCES" title="Settings">Manage connected wallet identity, provider setup, usage limits, and the virtual wallet’s security boundaries.</PageHeading><WalletIdentityPanel/><ProviderOperationsPanel/><TelegramPanel/><section className="panel wallet-preference-panel"><div className="panel-header"><div><span className="panel-title">Wallet security</span><span className="panel-subtitle">How Zecto protects your wallet boundary</span></div><ShieldCheck size={17}/></div><div className="wallet-preference-row"><div><b>Identity verification</b><small>A one-time signed message proves wallet ownership. Your wallet keeps its keys.</small></div><span className="provider-on">MESSAGE SIGNATURE</span></div><div className="wallet-preference-row"><div><b>Trade execution</b><small>Orders and swaps update only the Zecto paper ledger. No transaction signing or broadcast.</small></div><span className="provider-on">VIRTUAL ONLY</span></div><div className="wallet-preference-row"><div><b>Starting balance</b><small>One $10,000 virtual USDC allocation per verified account.</small></div><span className="provider-on">USDC</span></div></section></div>
}

function ProviderOperationsPanel() {
  const auth = useQuery({queryKey:['wallet-auth'], queryFn:api.walletAuth})
  const status = useQuery({queryKey:['settings-status'], queryFn:api.status, staleTime:60_000})
  const usage = useQuery({queryKey:['settings-usage'], queryFn:api.usage, enabled:auth.data?.authenticated===true, refetchInterval:30_000})
  const sources = status.data?.data_sources
  return <section className="panel settings-panel"><div className="panel-header"><div><span className="panel-title">Providers and budgets</span><span className="panel-subtitle">Configured means a key or endpoint is present; it does not mean the source is currently operational or live-verified.</span></div><ShieldCheck size={17}/></div>{status.isLoading?<div className="data-source-note">Loading provider status…</div>:status.error?<ErrorCard message="Provider status is unavailable."/>:<><div className="settings-subheading">Language models</div>{status.data?.departments.map(department=><div className="provider-row" key={department.department}><div><b>{department.department==='autonomous'?'War Room':'Trading Room'}</b><small>{department.providers.map(provider=>`${provider.provider}: ${provider.configured?'configured':'not configured'}`).join(' · ')}</small></div><span className={department.available?'provider-on':'provider-off'}>{department.available?'CONFIGURED':'UNAVAILABLE'}</span></div>)}<div className="settings-subheading">Market and research data</div>{[
    ['DexScreener', sources?.dexscreener?.configured, 'Public DEX discovery and pair observations'],
    ['CoinGecko', sources?.coingecko?.configured, 'Optional contract and market enrichment'],
    ['Exa', sources?.exa?.configured, `Optional web search · ${sources?.exa?.daily_call_budget??0} calls/day`],
    ['Alpha Vantage', sources?.alpha_vantage_daily?.configured, `Daily historical OHLCV · license status ${sources?.alpha_vantage_daily?.license_status??'disabled'}`],
    ...Object.entries(sources?.rpc??{}).map(([chain, configured])=>[`${chain} RPC`, configured, 'Chain observation endpoint'] as [string, boolean, string]),
  ].map(([name, configured, note])=><div className="provider-row" key={String(name)}><div><b>{name}</b><small>{note}</small></div><span className={configured?'provider-on':'provider-off'}>{configured?'CONFIGURED':'UNAVAILABLE'}</span></div>)}{!auth.data?.authenticated?<div className="settings-note"><CircleAlert size={15}/><span>Verify a wallet to view your account’s LLM usage and current daily call budget counters.</span></div>:usage.isLoading?<div className="data-source-note">Loading daily usage…</div>:usage.error?<ErrorCard message="Usage and budget status are unavailable."/>:usage.data&&<><div className="settings-subheading">Daily model-call limits · {usage.data.daily_call_budgets.budget_date} UTC</div>{Object.entries(usage.data.daily_call_budgets.providers).map(([provider,budget])=><div className="wallet-preference-row" key={provider}><div><b>{provider}</b><small>{budget.used} of {budget.limit} provider calls reserved today</small></div><span className="provider-on">{Math.max(0,budget.limit-budget.used)} LEFT</span></div>)}<div className="wallet-preference-row"><div><b>Global calls</b><small>{usage.data.daily_call_budgets.global.used} of {usage.data.daily_call_budgets.global.limit} reserved today · counters are shared across replicas</small></div><span className="provider-on">{Math.max(0,usage.data.daily_call_budgets.global.limit-usage.data.daily_call_budgets.global.used)} LEFT</span></div><div className="settings-note"><CircleAlert size={15}/><span>{usage.data.daily_call_budgets.cost_policy} Providers that omit cost metadata are marked as cost-incomplete in usage totals.</span></div></>}</>}</section>
}

function WalletIdentityPanel() {
  const queryClient = useQueryClient()
  const account = useQuery({queryKey: ['wallet-auth'], queryFn: api.walletAuth})
  const [notice, setNotice] = useState('')
  const signOut = useMutation({mutationFn:api.walletLogout, onSuccess: async () => {
    queryClient.removeQueries({queryKey:['paper-portfolio']})
    queryClient.removeQueries({queryKey:['trading-chats']})
    queryClient.removeQueries({queryKey:['trading-messages']})
    await queryClient.invalidateQueries({queryKey:['wallet-auth']})
    setNotice('Wallet identity signed out.')
  }})
  return <section className="panel settings-panel wallet-identity-panel"><div className="panel-header"><div><span className="panel-title">Connected wallets</span><span className="panel-subtitle">Your wallet extension keeps its keys; Zecto requests a one-time identity message.</span></div><ShieldCheck size={17}/></div>{account.data?.wallets.map(item=><div className="provider-row wallet-identity-row" key={`${item.chain}:${item.address}`}><WalletMark name={item.wallet_name}/><div><b>{item.wallet_name} · {item.chain}</b><small>{item.address}</small></div><span className="provider-on">Verified</span></div>)}<button className="secondary-button wallet-add-button" onClick={() => window.dispatchEvent(new Event('zecto:open-wallet'))}><WalletCards size={15}/>{account.data?.authenticated ? 'Link another wallet' : 'Connect a wallet'}</button>{signOut.error && <div className="inline-error">{(signOut.error as Error).message}</div>}{notice && <div className="success-note">{notice}</div>}{account.data?.authenticated && <button className="text-link" onClick={() => signOut.mutate()} disabled={signOut.isPending}>Sign out of wallet identity</button>}<div className="settings-note"><CircleAlert size={15}/><span>Paper assets are virtual only. Dashboard can prepare on-chain sends, but your wallet controls the keys and must approve each transaction. Zecto never has custody of your assets.</span></div></section>
}
