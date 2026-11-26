import { motion } from 'framer-motion'
import { Bot, CircleAlert, Paperclip } from 'lucide-react'
import type { Message } from '../api'

const names: Record<string, string> = {
  nova: 'Nova', atlas: 'Atlas', vega: 'Vega', echo: 'Echo', orion: 'Orion', makto: 'Makto', human: 'You',
}

const tints: Record<string, string> = {
  nova: 'violet', atlas: 'teal', vega: 'rose', echo: 'amber', orion: 'blue', makto: 'green', human: 'white',
}

export function AgentMessageFeed({
  messages,
  loading,
  error,
  roundtable = false,
  emptyTitle = 'No conversation yet',
  emptyText = 'Agent activity will appear here as the system investigates.',
}: {
  messages?: Message[]
  loading: boolean
  error?: Error | null
  roundtable?: boolean
  emptyTitle?: string
  emptyText?: string
}) {
  if (loading) return <div className="empty-state"><div className="loading-orbit"/><span>Loading verified agent messages…</span></div>
  if (error) return <div className="error-card"><CircleAlert size={18}/><span>{error.message}</span></div>
  if (!messages?.length) return <div className="empty-state"><div className="empty-icon"><Bot size={22}/></div><b>{emptyTitle}</b><span>{emptyText}</span></div>

  return <div className="message-list" aria-live="polite">
    {messages.map(message => {
      const name = names[message.agent_id] ?? message.agent_id
      return <motion.article
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18 }}
        className={`message-row ${message.agent_id === 'human' ? 'human-row' : ''}`}
        key={message.id}
      >
        <div className={`message-avatar ${tints[message.agent_id] ?? 'blue'}`}>{name.slice(0, 1)}</div>
        <div className="message-body">
          <div className="message-meta">
            <b>{name}</b>
            {roundtable && message.agent_id !== 'human' && <span className="decision-tag">ROUND TABLE</span>}
            {!roundtable && message.agent_id === 'orion' && <span className="decision-tag">SYNTHESIS</span>}
            <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
          </div>
          <p>{message.content}</p>
          {message.sources?.length ? <div className="attachment-list">{message.sources.map(source =>
            <a className="source-chip" key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>,
          )}</div> : null}
          {message.attachments?.length ? <div className="attachment-list">{message.attachments.map(name =>
            <span className="attachment-chip" key={name}><Paperclip size={12}/>{name}</span>,
          )}</div> : null}
        </div>
      </motion.article>
    })}
  </div>
}

export function StreamingAgentMessage({ agentId }: { agentId: string }) {
  const name = names[agentId] ?? agentId
  return <article className="message-row streaming-row" aria-live="polite">
    <div className={`message-avatar ${tints[agentId] ?? 'blue'}`}>{name.slice(0, 1)}</div>
    <div className="message-body">
      <div className="message-meta"><b>{name}</b><span className="decision-tag">WORKING</span></div>
      <p>Reviewing current market inputs…</p>
    </div>
  </article>
}
