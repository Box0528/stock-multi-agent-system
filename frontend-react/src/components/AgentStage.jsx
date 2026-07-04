import AgentCard from './AgentCard'

const AGENTS = ['technical', 'news', 'sector', 'supervisor', 'risk', 'reflection']

export default function AgentStage({ agents, stageLabel }) {
  return (
    <div className="agent-stage">
      <div className="stage-header">
        <span className="stage-title">Agent 协作中</span>
        <span className="stage-sub">{stageLabel}</span>
      </div>
      <div className="agents-grid">
        {AGENTS.map(id => (
          <AgentCard key={id} id={id} {...agents[id]} />
        ))}
      </div>
    </div>
  )
}
