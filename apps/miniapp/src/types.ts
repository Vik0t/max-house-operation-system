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
  provenance: string
  first_seen_at: string
  actions?: Action[]
  submissions?: { id: string; is_simulated: boolean; destination_id: string }[]
  work_orders?: WorkOrder[]
  signals?: { id: string; attachments: Array<Record<string, unknown>> }[]
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
    recurring_issues: number
    initiatives: number
  }
  assets: Asset[]
  issues: Issue[]
  initiatives: Initiative[]
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
