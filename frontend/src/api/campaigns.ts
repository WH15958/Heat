import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Campaign {
  campaign_id: string
  name: string
  material_system: string
  objective_metric: string
  parameter_names: string[]
  status: string
  created_at: string
  updated_at: string
  notes: string
}

export interface Trial {
  trial_id: string
  campaign_id: string
  parameters: Record<string, unknown>
  status: string
  recommendation_id: string
  run_id: string
  sample_id: string
  notes: string
  created_at: string
  updated_at: string
}

export interface CharacterizationResult {
  characterization_id: string
  campaign_id: string
  trial_id: string
  characterization_type: string
  metrics: Record<string, unknown>
  sample_id: string
  raw_file_path: string
  notes: string
  measured_at?: string | null
  created_at: string
}

export interface CreateCampaignPayload {
  name: string
  material_system: string
  objective_metric: string
  parameter_names: string[]
  notes?: string
}

export interface CharacterizationPayload {
  trial_id: string
  characterization_type: string
  metrics: Record<string, unknown>
  sample_id?: string
  raw_file_path?: string
  notes?: string
  measured_at?: string
}

export const campaignsApi = {
  list: () => api.get<Campaign[]>('/campaigns/'),
  create: (payload: CreateCampaignPayload) => api.post<Campaign>('/campaigns/', payload),
  recommendManual: (campaignId: string, parametersBatch: Record<string, unknown>[]) =>
    api.post<{ recommendation: unknown; trials: Trial[] }>(
      `/campaigns/${campaignId}/recommendations/manual`,
      { parameters_batch: parametersBatch, batch_size: parametersBatch.length },
    ),
  listTrials: (campaignId: string) => api.get<Trial[]>(`/campaigns/${campaignId}/trials`),
  updateTrial: (campaignId: string, trialId: string, payload: Partial<Pick<Trial, 'status' | 'run_id' | 'sample_id' | 'notes'>>) =>
    api.patch<Trial>(`/campaigns/${campaignId}/trials/${trialId}`, payload),
  createCharacterization: (campaignId: string, payload: CharacterizationPayload) =>
    api.post<CharacterizationResult>(`/campaigns/${campaignId}/characterizations`, payload),
  listCharacterizations: (campaignId: string) =>
    api.get<CharacterizationResult[]>(`/campaigns/${campaignId}/characterizations`),
  history: (campaignId: string) => api.get<unknown[]>(`/campaigns/${campaignId}/history`),
}
