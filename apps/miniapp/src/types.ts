export type House = {
  id: string
  address: string
  region: string
  management_org: string
  configuration_id: string
}

export type Asset = {
  id: string
  house_id: string
  zone_id: string
  type: string
  name: string
  operational_state: string
}

export type Action = {
  id: string
  suggested_destination: string
  rationale: string
  confidence: number
  provenance: string
}

export type Evidence = {
  id: string
  type: string
  uri: string
  comment: string
  created_at: string
}

export type WorkOrder = {
  id: string
  status: string
  assignee_id: string
  title: string
  evidence: Evidence[]
}

export type Issue = {
  id: string
  house_id: string
  zone_id: string | null
  asset_id: string | null
  category: string
  title: string
  description: string
  severity: string
  state: string
  confirmations_count: number
  recurrence_count: number
  asset_name?: string | null
  zone_name?: string | null
  related_issue_count?: number
  related_issue_ids?: string[]
  signals_count?: number
  provenance: string
  first_seen_at: string
  actions?: Action[]
  submissions?: { id: string; is_simulated: boolean; destination_id: string }[]
  work_orders?: WorkOrder[]
  signals?: Signal[]
}

export type Signal = {
  id: string
  chat_id: string | null
  author_id: string
  source_type: string
  text: string
  attachments: Array<Record<string, unknown>>
  provenance: string
  created_at: string
  status?: 'CLUSTERED' | 'AWAITING_CONTEXT'
  issue?: { id: string; title: string; state: string } | null
}

export type Initiative = {
  id: string
  title: string
  summary: string
  options: string[]
  votes: Record<string, number>
  state: string
  requires_formal_process: boolean
  formal_handoff_type: string | null
  provenance: string
}

export type HouseState = {
  house: House
  metrics: {
    active_issues: number
    work_in_progress: number
    awaiting_confirmation?: number
    awaiting_representative?: number
    submitted_to_management?: number
    awaiting_verification?: number
    recurring_issues: number
    initiatives: number
  }
  assets: Asset[]
  issues: Issue[]
  history_issues?: Issue[]
  initiatives: Initiative[]
  recent_signals: Signal[]
  integration: { max: string; external_submission: string }
}

export type SignalResult = {
  signal?: { id: string }
  issue?: Issue
  initiative?: Initiative
  fallback?: {
    type: string
    message?: string
    choices?: { id: string; name: string }[]
    candidate?: Issue
    actions?: string[]
  }
  clustered?: boolean
}
