export class OwnerScope {
  private generation = 0;
  owner: string | null = null;
  setOwner(owner: string | null) { this.owner = owner; this.generation += 1; }
  stamp() { return this.generation; }
  current(stamp: number) { return stamp === this.generation; }
}
export type Mode = 'naive' | 'mix';
export type KnowledgeBase = 'frozen' | 'managed';
export type Pending = {owner: string; conversationId: string; question: string; mode: Mode; key: string; knowledgeBase: KnowledgeBase};
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const prefix = 'doctrace.react.pending.v1:';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function createPending(owner: string, conversationId: string, question: string, mode: Mode, knowledgeBase: KnowledgeBase = 'frozen'): Pending {
  return {owner, conversationId, question, mode, knowledgeBase, key: crypto.randomUUID()};
}
export function loadPending(store: Store, owner: string): Pending | null {
  try {
    const raw = store.getItem(prefix + owner);
    if (!raw) return null;
    const p = JSON.parse(raw) as Pending;
    if (p.owner !== owner || !uuid.test(p.key) || typeof p.conversationId !== 'string' || !p.conversationId || typeof p.question !== 'string' || !p.question.trim() || p.question.length > 2000 || !['naive', 'mix'].includes(p.mode)) return null;
    if (!Object.hasOwn(p, 'knowledgeBase')) p.knowledgeBase = 'frozen';
    if (!['frozen', 'managed'].includes(p.knowledgeBase)) return null;
    return p;
  } catch {return null;}
}
export function savePending(store: Store, pending: Pending) {store.setItem(prefix + pending.owner, JSON.stringify(pending));}
export function clearPending(store: Store, owner: string, key?: string) {
  if (!key || loadPending(store, owner)?.key === key) store.removeItem(prefix + owner);
}
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {super(message); this.status = status;}
}
export class StaleIdentityError extends Error {}
type RequestOptions = {owner?: string | null; method?: string; body?: unknown; key?: string; fetcher?: typeof fetch};
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers({'Accept': 'application/json'});
  if (options.owner) headers.set('X-DocTrace-User-ID', options.owner);
  if (options.key) headers.set('Idempotency-Key', options.key);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await (options.fetcher ?? fetch)(path, {
    method: options.method ?? 'GET', credentials: 'same-origin', cache: 'no-store', headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : `请求未完成（HTTP ${response.status}），请稍后重试。`;
    throw new ApiError(response.status, message);
  }
  if (!payload || typeof payload !== 'object') throw new ApiError(502, '服务返回了无法识别的内容。');
  return (Object.hasOwn(payload, 'data') ? payload.data : payload) as T;
}
