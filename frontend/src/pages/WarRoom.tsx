import { useMemo, useState } from 'react'
import { CircleHelp, Users } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { AgentMessageFeed } from '../components/AgentMessageFeed'

const agentList = [
  { id: 'all', name: 'All agents', role: 'Shared intelligence feed', mark: 'Z' },
  { id: 'nova', name: 'Nova', role: 'Market intelligence', mark: 'N' },
  { id: 'atlas', name: 'Atlas', role: 'Quantitative analysis', mark: 'A' },
  { id: 'vega', name: 'Vega', role: 'Token and contract risk', mark: 'V' },
  { id: 'echo', name: 'Echo', role: 'On-chain research', mark: 'E' },
  { id: 'orion', name: 'Orion', role: 'Forecasts and synthesis', mark: 'O' },
] as const

type SelectedAgent = typeof agentList[number]['id']

export default function WarRoom() {
  const [selected, setSelected] = useState<SelectedAgent>('all')
  const feed = useQuery({
    queryKey: ['warroom-messages'],
    queryFn: () => api.messages('autonomous'),
    refetchInterval: 12_000,
  })
  const summary = useQuery({
    queryKey: ['warroom-summary'],
    queryFn: api.warRoomSummary,
    refetchInterval: 30_000,
  })

  const messages = useMemo(() => {
    const rows = feed.data?.messages ?? []
    return rows.filter(message => selected === 'all' || message.agent_id === selected)
  }, [feed.data?.messages, selected])

  const counts = useMemo(() => {
    const rows = feed.data?.messages ?? []
    return Object.fromEntries(agentList.map(agent => [
      agent.id,
      agent.id === 'all' ? rows.length : rows.filter(message => message.agent_id === agent.id).length,
    ])) as Record<SelectedAgent, number>
  }, [feed.data?.messages])

  const phase = summary.data?.agent_phase ?? 'starting'
  const phaseLabels: Record<string, string> = {
    crypto: 'Crypto session',
    resting: 'Scheduled break',
    stocks: 'Stock session',
    idle: 'Between sessions',
    starting: 'Connecting',
  }
  const phaseLabel = phaseLabels[phase] ?? 'Schedule unavailable'

  return <div className="page-content zecto-room-page">
    <header className="zecto-room-heading">
      <div>
        <span className="eyebrow"><i/> ZECTO · WAR ROOM</span>
        <h1>Agent conversations</h1>
        <p>Follow the research team’s live discussion and evidence-backed conclusions.</p>
      </div>
      <div className={`room-status room-status-${phase}`}>
        <span className="room-status-dot"/>
        <span><b>{phaseLabel}</b><small>{summary.data?.phase_ends_at
          ? `Next phase ${new Date(summary.data.phase_ends_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
          : 'Schedule status updates automatically'}</small></span>
      </div>
    </header>

    <div className="agent-chat-layout">
      <aside className="agent-chat-sidebar" aria-label="War Room conversations">
        <div className="agent-sidebar-title"><span>RESEARCH TEAM</span><Users size={15}/></div>
        <nav className="agent-chat-nav">
          {agentList.map(agent => <button
            key={agent.id}
            type="button"
            className={`agent-chat-nav-item ${selected === agent.id ? 'active' : ''}`}
            onClick={() => setSelected(agent.id)}
            aria-current={selected === agent.id ? 'page' : undefined}
          >
            <span className={`agent-chat-mark agent-mark-${agent.id}`}>{agent.mark}</span>
            <span className="agent-chat-copy"><b>{agent.name}</b><small>{agent.role}</small></span>
            <span className="agent-chat-count">{counts[agent.id]}</span>
          </button>)}
        </nav>
        <div className="agent-sidebar-note"><CircleHelp size={14}/><span>Messages reflect actual system activity. Missing provider data is reported as unavailable.</span></div>
      </aside>

      <section className="agent-chat-thread" aria-label={`${agentList.find(agent => agent.id === selected)?.name ?? 'All agents'} messages`}>
        <header className="agent-thread-heading">
          <div className="agent-thread-avatar">{agentList.find(agent => agent.id === selected)?.mark ?? 'Z'}</div>
          <div>
            <h2>{agentList.find(agent => agent.id === selected)?.name ?? 'All agents'}</h2>
            <p>{agentList.find(agent => agent.id === selected)?.role ?? 'Shared intelligence feed'}</p>
          </div>
          <span className="thread-live-label"><i/> LIVE FEED</span>
        </header>
        <div className="agent-thread-scroll">
          <AgentMessageFeed
            messages={messages}
            loading={feed.isLoading}
            error={feed.error as Error | null}
            emptyTitle={selected === 'all' ? 'The room is quiet' : `No messages from ${agentList.find(agent => agent.id === selected)?.name ?? 'this agent'} yet`}
            emptyText={phase === 'resting' || phase === 'idle'
              ? 'The scheduled session is paused. New agent messages will appear when the next block begins.'
              : 'No verified agent messages are available in the current feed.'}
          />
        </div>
      </section>
    </div>
  </div>
}
