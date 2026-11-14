export type TradingChat = { id: string; title: string; created_at: string; updated_at: string }
export type Message = { id: string; department: string; agent_id: string; role: string; content: string; created_at: string; investigation_id?: string | null; simulated?: boolean }
export type Wallet = { connected: boolean; address?: string; label?: string; kind: string; network: string; near_balance?: string }
export type Event = { sequence: number; event_id: string; department: string; event_type: string; agent_id?: string; payload: Record<string, unknown> }
export type EvidenceRecord = { id: string; chain: string; token_address: string; source: string; data_kind: 'live'|'delayed'|'simulated'; observed_at: string; fields: Record<string, unknown>; limitations?: string }
export type Agent = { id: string; name: string; role: string; investigations: number; tokens_analyzed: number; llm_tokens: number; active_investigations: number; last_activity: string | null }
export type Finding = { id: string; agent_id: string; round: number; phase: string; content: string; confidence: number | null; evidence_ids: string[]; created_at: string }
export type Investigation = { id: string; department: string; chain: string; token_address: string; title: string; status: string; scenario_id: string | null; confidence: number | null; created_at: string; updated_at: string; completed_at: string | null; findings: Finding[] }
export type AppStatus = {
  departments: { department: string; available: boolean; providers: { provider: string; configured: boolean; model: string | null }[] }[]
  data_sources: { dexscreener: { configured: boolean; authentication_required: boolean }; coingecko: { configured: boolean }; rpc: Record<string, boolean>; auto_scan_enabled: boolean; scan_interval_seconds: number }
}

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
  wallet: () => request<Wallet>('/api/wallet'),
  connect: () => request<Wallet>('/api/wallet/connect', { method: 'POST', body: JSON.stringify({ label: 'ClawIntel demo wallet' }) }),
  disconnect: () => request<{ connected: boolean }>('/api/wallet/disconnect', { method: 'POST' }),
  send: (content: string, chatId: string) => request<{ replies?: Message[]; reply?: Message; turns_completed?: number; turns_expected?: number; complete?: boolean }>('/api/trading/messages', { method: 'POST', body: JSON.stringify({ content, chat_id: chatId }) }),
  quote: (body: { chain: string; token_address: string; side: string; amount_near: number }) => request<Quote>('/api/trading/quotes', { method: 'POST', body: JSON.stringify(body) }),
  approve: (quote_id: string, approved: boolean) => request<{ status: string; simulated: boolean }>('/api/trading/approve', { method: 'POST', body: JSON.stringify({ quote_id, approved, idempotency_key: crypto.randomUUID() }) }),
  portfolio: () => request<Portfolio>('/api/trading/portfolio'),
  shiftMarket: () => request<{ scenario: string; simulated: boolean; change_percent: number; positions: { token_address: string; old_price_near: string; new_price_near: string }[] }>('/api/trading/scenarios/market-shift', { method: 'POST' }),
  status: () => request<AppStatus>('/api/settings/status'),
  usage: () => request<{ departments: Record<string, { requests: number; input_tokens: number; output_tokens: number; cost_usd: number | null }> }>('/api/settings/usage'),
  investigations: (room: 'autonomous'|'trading' = 'autonomous') => request<{ investigations: Investigation[] }>(`/api/${room}/investigations`),
  runScenario: (id: string) => request<{ scenario: string; simulated: boolean; evidence_id: string; investigation_id: string; status: string; findings: number; challenge_agent?: string | null }>(`/api/scenarios/${id}/run`, { method: 'POST' }),
  events: (room: 'autonomous' | 'trading') => request<{ events: Event[] }>(`/api/${room}/events`),
  evidence: () => request<{ evidence: EvidenceRecord[] }>('/api/autonomous/evidence'),
}

export type Quote = { quote_id: string; simulated: boolean; source: string; symbol: string; amount_near: string; price_near_per_token: string; estimated_quantity: string; fee_near: string; expires_at: string }
export type Portfolio = { simulated: boolean; near_balance: string; positions: { chain: string; token_address: string; quantity: string; average_price_near: string; current_price_near: string | null; value_near: string | null }[]; trades: { id: string; token_address: string; side: string; amount_near: string; status: string; created_at: string }[] }
