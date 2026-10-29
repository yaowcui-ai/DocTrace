export type Identity = {user_id: string; username: string; role: string};
export type Reference = {reference_id: string | number; file_path: string; content?: string[] | string; source_url?: string};
export type Message = {id: string; request_id: string; question: string; answer: string; mode: string; actual_mode?: string | null; historical_import?: boolean; corpus_id?: string | null; knowledge_base?: 'frozen' | 'managed'; status: string; feedback?: {helpful: boolean; comment: string} | null; references: Reference[]; retrieval?: Record<string, unknown>; created_at?: string; llm_generated?: boolean};
export type Conversation = {id: string; title: string; created_at?: string; updated_at?: string; messages?: Message[]; has_more?: boolean};
export type ItemList<T> = {items: T[]; has_more?: boolean; limit?: number};
export type AdminItem = Record<string, unknown>;
