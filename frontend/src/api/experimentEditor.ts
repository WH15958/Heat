import axios from 'axios'
export interface Issue { message: string; path: (string | number)[]; step_id?: string; line: number; column: number }
export interface Validation { valid: boolean; errors: Issue[]; warnings: Issue[] }
export interface Source { filename: string; content: string; revision: string }
const base = '/api/experiments'
export const editorApi = {
  read: (name: string) => axios.get<Source>(`${base}/${encodeURIComponent(name)}/source`),
  validate: (content: string) => axios.post<Validation>(`${base}/validate`, { content }),
  save: (name: string, content: string, revision: string | null) => axios.put<Source>(`${base}/${encodeURIComponent(name)}/source`, { content, revision }),
}
