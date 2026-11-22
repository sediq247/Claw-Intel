export type TradingChat = { id: string; title: string; created_at: string; updated_at: string }
export type ChatAttachment = {name: string; content: string}
export type Message = { id: string; department: string; agent_id: string; role: string; content: string; created_at: string; investigation_id?: string | null; simulated?: boolean; attachments?: string[]; sources?: {title:string;url:string}[] }
export type Event = { sequence: number; event_id: string; department: string; event_type: string; agent_id?: string; payload: Record<string, unknown> }
export type EvidenceRecord = { id: string; chain: string; token_address: string; source: string; data_kind: 'live'|'delayed'|'simulated'; observed_at: string; fields: Record<string, unknown>; limitations?: string }
export type Agent = { id: string; name: string; role: string; investigations: number; tokens_analyzed: number; llm_tokens: number; active_investigations: number; last_activity: string | null }
export type Finding = { id: string; agent_id: string; round: number; phase: string; content: string; confidence: number | null; evidence_ids: string[]; created_at: string }
export type Investigation = { id: string; department: string; chain: string; token_address: string; title: string; status: string; scenario_id: string | null; confidence: number | null; created_at: string; updated_at: string; completed_at: string | null; findings: Finding[] }
export type AppStatus = {
  departments: { department: string; available: boolean; providers: { provider: string; configured: boolean; model: string | null }[] }[]
  data_sources: { dexscreener: { configured: boolean; authentication_required: boolean }; coingecko: { configured: boolean }; rpc: Record<string, boolean>; auto_scan_enabled: boolean; scan_interval_seconds: number }
}
export type TokenLookup = { asset: { chain: string; token_address: string; symbol: string; name: string; price_usd: string | null; liquidity_usd: string | null; market_cap_usd: string | null; volume_24h_usd: string | null; provider_retrieved_at: string; source: string; data_kind: string; limitations: string }; quote_route: { available: boolean; reason: string }; paper_execution: { available: boolean; reason: string } }
export type WalletIdentityState = { authenticated: boolean; user_id?: string; wallets: { chain: string; address: string; wallet_name: string; verified_at: string }[] }
export type PaperPortfolio = { currency: 'USDC'; initial_virtual_usdc: string; virtual_usdc_balance: string; cash_usd: string; positions: { chain: string; token_address: string; symbol: string; name?:string|null; quantity: string; average_price_usd: string; current_price_usd: string|null; market_value_usd: string|null; unrealized_pnl_usd: string|null; price_observed_at: string|null; logo_url?: string|null; price_change_24h_pct?: string|null; market_cap_usd?: string|null; volume_24h_usd?: string|null; ath_usd?: string|null; ath_date?:string|null }[]; orders: { id: string; side: string; chain: string; token_address: string; symbol: string; amount_usd: string; price_usd: string; quantity: string; source: string; observed_at: string; created_at: string }[]; valuation: { available: boolean; reason: string|null; market_value_usd: string|null; total_equity_usd: string|null; unrealized_pnl_usd: string|null; marked_positions: number; fresh_mark_limit: number } }
export type PaperTransfer = {id:string;direction:'send'|'receive';amount_usdc:string;chain:string;address:string;created_at:string}
export type IntelToken = {chain:string;token_address:string;symbol:string;name:string;logo_url:string|null;price_usd:string|null;price_change_24h_pct:string|null;volume_24h_usd:string|null;liquidity_usd:string|null;market_cap_usd:string|null;ath_usd:string|null;ath_date:string|null;ath_source:string|null;observed_at:string|null;analysis_observed_at:string;analysis_source:string;agent_view:string|null;agent_id:string|null;agent_confidence:string|null;agent_view_at:string|null;data_kind:'live';limitations:string|null;live_available:boolean}
export type WarRoomSummary = {scanned_tokens:number;rugged_tokens_7d:number|null;rug_source:string;safe_tokens:number|null;safe_source:string;agent_phase:'working'|'draining'|'resting'|'starting';phase_ends_at:string|null;updated_at:string}
export type WatchlistEntry = { id: string; chain: string; token_address: string; label: string; created_at: string }
export type PriceAlert = { id: string; watchlist_entry_id: string; chain: string; token_address: string; condition: 'above'|'below'; threshold_usd: string; enabled: boolean; is_triggered: boolean; last_observed_price_usd: string|null; last_checked_at: string|null; created_at: string }
export type PriceAlertNotification = { id: string; alert_id: string; observed_price_usd: string; source: string; observed_at: string; created_at: string; read_at: string|null }
export type TradingWatchlist = { entries: WatchlistEntry[]; alerts: PriceAlert[]; notifications: PriceAlertNotification[]; monitor_interval_seconds: number }
export type TelegramStatus = { configured: boolean; mode: 'webhook'|'polling'|'unavailable'; linked: boolean; username: string|null; linked_at: string|null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'include', headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail && typeof body.detail === 'object' && 'message' in body.detail && typeof body.detail.message === 'string') detail = body.detail.message
    } catch { /* response was not JSON */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  session: () => request<{ session_id: string; wallet_connected: boolean }>('/api/session', { method: 'POST' }),
  health: () => request<{ status: string; database: string; llm: { autonomous: boolean; trading: boolean }; market_data: AppStatus['data_sources'] }>('/health'),
  agents: (department?: 'autonomous'|'trading') => request<{ agents: Agent[] }>(`/api/agents${department ? `?department=${department}` : ''}`),
  messages: (room: 'autonomous' | 'trading', chatId?: string) => request<{ messages: Message[] }>(`/api/${room}/messages${room === 'trading' && chatId ? `?chat_id=${encodeURIComponent(chatId)}` : ''}`),
  tradingChats: () => request<{ chats: TradingChat[] }>('/api/trading/chats'),
  newTradingChat: () => request<TradingChat>('/api/trading/chats', { method: 'POST', body: JSON.stringify({ title: 'New chat' }) }),
  deleteTradingChat: (chatId: string) => request<{ deleted: boolean; chat_id: string }>(`/api/trading/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' }),
  send: (content: string, chatId: string, attachments: ChatAttachment[] = []) => request<{ replies?: Message[]; reply?: Message; turns_completed?: number; turns_expected?: number; complete?: boolean }>('/api/trading/messages', { method: 'POST', body: JSON.stringify({ content, chat_id: chatId, attachments }) }),
  tokenLookup: (chain: string, address: string) => request<TokenLookup>(`/api/trading/token-search?chain=${encodeURIComponent(chain)}&address=${encodeURIComponent(address)}`),
  walletAuth: () => request<WalletIdentityState>('/api/auth/me'),
  walletChallenge: (body: {chain: string; address: string; wallet_name: string}) => request<{challenge_id: string; message: string; expires_at: string}>('/api/auth/wallet/challenge', { method: 'POST', body: JSON.stringify(body) }),
  walletVerify: (body: {challenge_id: string; chain: string; address: string; wallet_name: string; signature: string}) => request<{authenticated: boolean; user_id: string; chain: string; address: string; wallet_name: string}>('/api/auth/wallet/verify', { method: 'POST', body: JSON.stringify(body) }),
  walletLogout: () => request<{authenticated: boolean}>('/api/auth/logout', { method: 'POST' }),
  paperPortfolio: () => request<PaperPortfolio>('/api/paper/portfolio'),
  paperOrder: (body: {chain: string; token_address: string; side: 'buy'|'sell'; amount_usd: number; idempotency_key: string}) => request<{order: PaperPortfolio['orders'][number]; cash_usd: string; replayed: boolean; fill_assumptions?: Record<string,string>}>('/api/paper/orders', { method: 'POST', body: JSON.stringify(body) }),
  paperSwap: (body: {source_chain:string; source_token_address:string; target_chain:string; target_token_address:string; source_quantity:number; idempotency_key:string; from_virtual_usdc?:boolean}) => request<{orders: PaperPortfolio['orders'][number][]; replayed:boolean; virtual_value_usd?:string; target_quantity?:string; limitations?:string}>('/api/paper/swaps', {method:'POST',body:JSON.stringify(body)}),
  paperReceive: () => request<{chain:string;address:string;kind:'internal_virtual_usdc';warning:string}>('/api/paper/receive'),
  paperTransfers: () => request<{transfers:PaperTransfer[]}>('/api/paper/transfers'),
  paperTransfer: (body:{chain:string;recipient_address:string;amount_usdc:number;idempotency_key:string}) => request<{transfer_id:string;amount_usdc:string;replayed:boolean;kind:'internal_virtual_usdc';warning?:string}>('/api/paper/transfers',{method:'POST',body:JSON.stringify(body)}),
  tradingWatchlist: () => request<TradingWatchlist>('/api/trading/watchlist'),
  addWatchlistEntry: (body: {chain: string; token_address: string; label: string}) => request<WatchlistEntry>('/api/trading/watchlist', { method: 'POST', body: JSON.stringify(body) }),
  deleteWatchlistEntry: (id: string) => request<{deleted: boolean; id: string}>(`/api/trading/watchlist/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  createPriceAlert: (body: {watchlist_entry_id: string; condition: 'above'|'below'; threshold_usd: number}) => request<PriceAlert>('/api/trading/price-alerts', { method: 'POST', body: JSON.stringify(body) }),
  setPriceAlertEnabled: (id: string, enabled: boolean) => request<PriceAlert>(`/api/trading/price-alerts/${encodeURIComponent(id)}/enabled`, { method: 'POST', body: JSON.stringify({enabled}) }),
  deletePriceAlert: (id: string) => request<{deleted: boolean; id: string}>(`/api/trading/price-alerts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  markPriceAlertRead: (id: string) => request<{read: boolean; id: string}>(`/api/trading/price-alert-notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }),
  telegramStatus: () => request<TelegramStatus>('/api/telegram/status'),
  createTelegramLink: () => request<{url:string;expires_at:string}>('/api/telegram/link', {method:'POST'}),
  unlinkTelegram: () => request<{linked:boolean}>('/api/telegram/link', {method:'DELETE'}),
  status: () => request<AppStatus>('/api/settings/status'),
  usage: () => request<{ departments: Record<string, { requests: number; input_tokens: number; output_tokens: number; cost_usd: string | null; cost_reported_requests: number; cost_complete: boolean }> }>('/api/settings/usage'),
  investigations: (room: 'autonomous'|'trading' = 'autonomous') => request<{ investigations: Investigation[] }>(`/api/${room}/investigations`),
  runScenario: (id: string) => request<{ scenario: string; simulated: boolean; evidence_id: string; investigation_id: string; status: string; findings: number; challenge_agent?: string | null }>(`/api/scenarios/${id}/run`, { method: 'POST' }),
  events: (room: 'autonomous' | 'trading') => request<{ events: Event[] }>(`/api/${room}/events`),
  evidence: () => request<{ evidence: EvidenceRecord[] }>('/api/autonomous/evidence'),
  intelTokens: () => request<{tokens:IntelToken[];source:string}>('/api/intel/tokens'),
  warRoomSummary: () => request<WarRoomSummary>('/api/warroom/summary'),
}
