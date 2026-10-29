import {useCallback, useEffect, useRef, useState} from 'react';
import type {FormEvent} from 'react';
import {ApiError, OwnerScope, StaleIdentityError, apiRequest, clearPending, createPending, loadPending, savePending} from './state.ts';
import type {KnowledgeBase, Mode, Pending} from './state.ts';
import type {AdminItem, Conversation, Identity, ItemList, Message, Reference} from './types.ts';
import {RequestStatistics} from './RequestStatistics.tsx';

type Api = <T>(path: string, method?: string, body?: unknown, key?: string) => Promise<T>;
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求未完成，请稍后重试。';
const savedConversationKey = (owner: string) => `doctrace.react.conversation.v1:${owner}`;
const draftKey = (owner: string) => `doctrace.react.draft.v1:${owner}`;
const syncKey = 'doctrace.auth-change.v1';
function ignoreStale(error: unknown) {return error instanceof StaleIdentityError || error instanceof ApiError && error.status === 401;}
function localRead(key: string) {try {return sessionStorage.getItem(key);} catch {return null;}}
function localWrite(key: string, value: string | null) {try {if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key);} catch { /* Recovery is optional; current in-memory operation stays available. */ }}
function announceAuth() {try {localStorage.setItem(syncKey, crypto.randomUUID());} catch { /* Visibility revalidation still applies. */ }}

export function App() {
  const scope = useRef(new OwnerScope());
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [logoutUnconfirmed, setLogoutUnconfirmed] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [query, setQuery] = useState('');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [listLimit, setListLimit] = useState(30);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [historyStatus, setHistoryStatus] = useState('');
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<Mode>('naive');
  const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBase>('frozen');
  const [pending, setPending] = useState<Pending | null>(null);
  const [sending, setSending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState<'chat' | 'admin'>('chat');
  const [citation, setCitation] = useState<{message: Message; reference: Reference} | null>(null);

  const clearPrivate = useCallback(() => {
    setConversations([]); setConversationId(null); setConversation(null); setPending(null); setQuestion('');
    setQuery(''); setError(''); setCitation(null); setTab('chat'); setSending(false); setCreating(false); setImporting(false); setHistoryStatus('');
    setListLoading(false); setDetailLoading(false); setMode('naive'); setKnowledgeBase('frozen'); setHasMore(false); setListLimit(30);
  }, []);

  const invalidate = useCallback(() => {
    scope.current.setOwner(null); setIdentity(null); clearPrivate();
  }, [clearPrivate]);

  const adoptIdentity = useCallback((user: Identity) => {
    scope.current.setOwner(user.user_id); clearPrivate(); setIdentity(user);
    const operation = loadPending(sessionStorage, user.user_id);
    setPending(operation);
    setQuestion(localRead(draftKey(user.user_id)) ?? '');
    setConversationId(operation?.conversationId ?? localRead(savedConversationKey(user.user_id)));
  }, [clearPrivate]);

  const verifyIdentity = useCallback(async () => {
    const stamp = scope.current.stamp();
    setAuthChecking(true);
    try {
      const user = await apiRequest<Identity>('/api/v1/me');
      if (!scope.current.current(stamp)) return;
      if (!user.user_id || !user.username || !user.role) throw new Error('身份服务返回不完整，请重新登录。');
      adoptIdentity(user); setAuthError('');
    } catch (failure) {
      if (!scope.current.current(stamp)) return;
      invalidate();
      if (!(failure instanceof ApiError && failure.status === 401)) setAuthError(errorText(failure));
    } finally {setAuthChecking(false);}
  }, [adoptIdentity, invalidate]);

  useEffect(() => {void verifyIdentity();}, [verifyIdentity]);
  useEffect(() => {
    function check() {if (!document.hidden && !authBusy && !logoutUnconfirmed && !sending) {invalidate(); void verifyIdentity();}}
    function storage(event: StorageEvent) {if (event.key === syncKey) {invalidate(); void verifyIdentity();}}
    function pageshow(event: PageTransitionEvent) {if (event.persisted) check();}
    document.addEventListener('visibilitychange', check); window.addEventListener('storage', storage); window.addEventListener('pageshow', pageshow);
    return () => {document.removeEventListener('visibilitychange', check); window.removeEventListener('storage', storage); window.removeEventListener('pageshow', pageshow);};
  }, [authBusy, invalidate, logoutUnconfirmed, sending, verifyIdentity]);

  const api: Api = useCallback(async <T,>(path: string, method = 'GET', body?: unknown, key?: string): Promise<T> => {
    const stamp = scope.current.stamp();
    const owner = scope.current.owner;
    try {
      const data = await apiRequest<T>(path, {owner, method, body, key});
      if (!scope.current.current(stamp)) throw new StaleIdentityError();
      return data;
    } catch (failure) {
      if (!scope.current.current(stamp)) throw new StaleIdentityError();
      if (failure instanceof ApiError && failure.status === 401) {invalidate(); setAuthError('登录已过期，请重新登录。');}
      throw failure;
    }
  }, [invalidate]);

  useEffect(() => {
    if (!identity) return;
    let current = true;
    setListLoading(true);
    const timer = window.setTimeout(() => {
      const load = async () => {
        const items: Conversation[] = []; let more = true;
        while (current && more && items.length < listLimit) {
          const data = await api<ItemList<Conversation>>(`/api/v1/conversations?q=${encodeURIComponent(query)}&limit=30&offset=${items.length}`);
          items.push(...data.items); more = Boolean(data.has_more) && data.items.length > 0;
        }
        if (current) {setConversations([...new Map(items.map(item => [item.id, item])).values()]); setHasMore(more);}
      };
      void load().catch(failure => {if (current && !ignoreStale(failure)) setError(errorText(failure));}).finally(() => {if (current) setListLoading(false);});
    }, query ? 250 : 0);
    return () => {current = false; window.clearTimeout(timer);};
  }, [identity, query, refresh, listLimit, api]);

  useEffect(() => {
    setConversation(null); setCitation(null);
    if (!identity || !conversationId) return;
    let current = true;
    setDetailLoading(true);
    void api<Conversation>(`/api/v1/conversations/${encodeURIComponent(conversationId)}`).then(data => {if (current) setConversation(data);}).catch(failure => {
      if (current && !ignoreStale(failure)) setError(errorText(failure));
    }).finally(() => {if (current) setDetailLoading(false);});
    return () => {current = false;};
  }, [identity, conversationId, refresh, api]);

  async function loadEarlier() {
    if (!conversationId || !conversation || detailLoading) return;
    const id = conversationId, stamp = scope.current.stamp();
    setDetailLoading(true);
    try {
      const earlier = await api<Conversation>(`/api/v1/conversations/${encodeURIComponent(id)}?offset=${conversation.messages?.length ?? 0}`);
      setConversation(previous => previous?.id === id ? {...previous, has_more: earlier.has_more,
        messages: [...new Map([...(earlier.messages ?? []), ...(previous.messages ?? [])].map(item => [item.id, item])).values()]} : previous);
    } catch (failure) {if (!ignoreStale(failure)) setError(errorText(failure));}
    finally {if (scope.current.current(stamp)) setDetailLoading(false);}
  }
  async function login(event: FormEvent) {
    event.preventDefault(); if (authBusy) return;
    setAuthBusy(true); setAuthError(''); invalidate();
    const stamp = scope.current.stamp();
    const suppliedPassword = password; setPassword('');
    try {
      await apiRequest('/auth/login', {method: 'POST', body: {username, password: suppliedPassword}});
      if (!scope.current.current(stamp)) return;
      setLogoutUnconfirmed(false); announceAuth(); await verifyIdentity();
    } catch (failure) {if (scope.current.current(stamp)) setAuthError(errorText(failure));}
    finally {setAuthBusy(false);}
  }
  async function logout() {
    if (authBusy) return;
    const previous = scope.current.owner;
    if (previous) {try {clearPending(sessionStorage, previous);} catch {} localWrite(savedConversationKey(previous), null); localWrite(draftKey(previous), null);}
    invalidate(); setAuthBusy(true); setAuthError(''); setLogoutUnconfirmed(true);
    try {
      await apiRequest('/auth/logout', {owner: previous, method: 'POST', body: {}});
      setLogoutUnconfirmed(false); announceAuth();
    } catch {setAuthError('退出尚未确认，请再次点击“重试退出”。');}
    finally {setAuthBusy(false);}
  }
  function chooseConversation(id: string) {
    if (!identity || sending) return;
    setConversationId(id); localWrite(savedConversationKey(identity.user_id), id); setError(''); setTab('chat');
  }
  async function createConversation() {
    if (!identity || creating || sending) return;
    setCreating(true); setError('');
    const stamp = scope.current.stamp();
    try {
      const created = await api<Conversation>('/api/v1/conversations', 'POST', {title: '新的政策对话'});
      chooseConversation(created.id); setRefresh(value => value + 1);
    } catch (failure) {if (!ignoreStale(failure)) setError(errorText(failure));}
    finally {if (scope.current.current(stamp)) setCreating(false);}
  }
  async function importHistory() {
    if (!identity || importing || sending) return;
    const stamp = scope.current.stamp(); setImporting(true); setHistoryStatus('');
    try {await api('/api/v1/conversations/import-records', 'POST', {}); setHistoryStatus('旧问答已导入。重复导入不会创建重复会话。'); setRefresh(value => value + 1);}
    catch (failure) {if (!ignoreStale(failure)) setHistoryStatus(errorText(failure));}
    finally {if (scope.current.current(stamp)) setImporting(false);}
  }
  async function send(operation: Pending) {
    if (sending || operation.owner !== identity?.user_id) return;
    const stamp = scope.current.stamp();
    setSending(true); setError('');
    try {
      const result = await api<Message>(`/api/v1/conversations/${encodeURIComponent(operation.conversationId)}/messages`, 'POST', {question: operation.question, mode: operation.mode, knowledge_base: operation.knowledgeBase}, operation.key);
      if (result.status !== 'completed') {
        setError(result.status === 'failed' ? '原请求已记录为失败。恢复原操作不会再次生成回答，请核对会话中的状态。' : '原请求仍未确认完成，请稍后手动恢复原操作。');
        setRefresh(value => value + 1); return;
      }
      try {clearPending(sessionStorage, operation.owner, operation.key);} catch {}
      setPending(null); setQuestion(''); localWrite(draftKey(operation.owner), null); chooseConversation(operation.conversationId); setRefresh(value => value + 1);
    } catch (failure) {if (!ignoreStale(failure)) setError(`${errorText(failure)} 原问题已保留；重试会使用同一操作编号。`);}
    finally {if (scope.current.current(stamp)) setSending(false);}
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!identity || !conversationId || pending || !question.trim() || sending) return;
    const operation = createPending(identity.user_id, conversationId, question.trim(), mode, knowledgeBase);
    try {savePending(sessionStorage, operation);} catch {setError('浏览器无法保存待处理操作，请启用会话存储后重试，以便避免重复提问。'); return;}
    setPending(operation); void send(operation);
  }
  function discard() {
    if (!pending || sending || !window.confirm('服务端可能仍在处理原问题。放弃本地恢复信息后，新提问会使用新的操作编号。确定继续？')) return;
    try {clearPending(sessionStorage, pending.owner, pending.key);} catch {}
    setPending(null); setError('');
  }

  return <>
    <a className="skip-link" href="#main-content">跳转到问答区</a>
    <div className="workspace">
      <aside className="sidebar" aria-label="个人会话">
        <a className="brand" href="/workspace/"><span className="brand-icon" aria-hidden="true">D<span>·</span></span><span>DocTrace<small>HR POLICY WORKSPACE</small></span></a>
        <div className="sidebar-intro"><span className="eyebrow">你的工作空间</span><h2>每次回答，<br />都有迹可循。</h2><p>查看政策，保留问题，回到依据。</p></div>
        <div className="section-heading"><h2>我的会话</h2><button className="text-button" onClick={() => setRefresh(value => value + 1)} disabled={!identity || sending}>刷新</button></div>
        <button className="new-conversation" onClick={() => void createConversation()} disabled={!identity || creating || sending}>{creating ? '正在创建…' : '＋ 新建会话'}</button>
        <button className="text-button import-history" onClick={() => void importHistory()} disabled={!identity || importing || sending}>{importing ? '正在导入…' : '导入旧问答'}</button>
        {historyStatus && <p className="history-hint" role="status">{historyStatus}</p>}
        <label className="visually-hidden" htmlFor="conversation-search">搜索个人会话</label><input id="conversation-search" className="search" placeholder="搜索会话内容" value={query} onChange={event => {setQuery(event.target.value); setListLimit(30);}} disabled={!identity} maxLength={200} />
        <div className="history-section" aria-busy={listLoading}>
          {listLoading && <p className="history-hint" role="status">正在查找会话…</p>}
          {!listLoading && conversations.length === 0 && <p className="history-hint">{identity ? '还没有匹配的会话。' : '登录后查看自己的会话。'}</p>}
          <ul className="history-list">{conversations.map(item => <li key={item.id}><button className="history-item" aria-current={conversationId === item.id ? 'true' : undefined} onClick={() => chooseConversation(item.id)} disabled={sending}><span className="history-item-title">{item.title}</span><span className="history-item-meta">{item.updated_at ? new Date(item.updated_at).toLocaleString('zh-CN') : '个人会话'}</span></button></li>)}</ul>
          {hasMore && <button className="secondary-button" onClick={() => setListLimit(value => Math.min(value + 30, 10020))} disabled={listLoading || listLimit >= 10020}>{listLimit >= 10020 ? '请搜索更多会话' : '显示更多'}</button>}
        </div>
        <div className="sidebar-footer"><span className="footer-mark" />企业 HR 政策问答与证据追溯</div>
      </aside>
      <main id="main-content" className="main-content">
        <header className="topbar"><span className="breadcrumb">DocTrace <span>/</span> 政策工作台</span><a className="legacy-link" href="/">旧版工作台 ↗</a></header>
        <div className="content-column">
          <section className="auth-card" aria-label="账户登录">
            {authChecking ? <p role="status">正在确认登录状态…</p> : identity ? <div className="account-row"><p>已登录 <strong>{identity.username}</strong><span className="role-badge">{identity.role === 'admin' ? '管理员' : '成员'}</span></p><button className="quiet-button" onClick={() => void logout()} disabled={authBusy}>退出登录</button></div> : <form onSubmit={event => void login(event)}><label htmlFor="username">用户名</label><input id="username" autoComplete="username" required value={username} maxLength={32} onChange={event => setUsername(event.target.value)} disabled={authBusy} /><label htmlFor="password">密码</label><input id="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} disabled={authBusy} /><button className="primary-button" disabled={authBusy}>{authBusy ? '正在登录…' : '登录'}</button></form>}
            {logoutUnconfirmed && <button className="quiet-button" onClick={() => void logout()} disabled={authBusy}>重试退出</button>}
            {authError && <p className="error-message" role="alert">{authError}</p>}
            <p className="muted">登录后查看个人记录。账户由管理员创建，政策内容以保存的来源快照为准。</p>
          </section>
          <section className="intro"><span className="eyebrow">ASK WITH CONTEXT</span><h1>把政策问题，<br />交给有依据的回答。</h1><p>在对话中查阅休假、福利与职业发展政策，并回到回答引用的原文。</p></section>
          {identity?.role === 'admin' && <nav className="tabs" aria-label="工作台功能"><button className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')}>政策问答</button><button className={tab === 'admin' ? 'active' : ''} onClick={() => setTab('admin')}>知识库与实验报告</button></nav>}
          {error && <div className="error-message" role="alert">{error}</div>}
          {tab === 'admin' && identity?.role === 'admin' ? <div key={identity.user_id}><RequestStatistics api={api} /><AdminPanel api={api} /></div> : <>
            <section className="answer-panel" aria-label="政策对话" aria-busy={detailLoading || sending}>
              <div className="section-heading answer-heading"><h2>{conversation?.title ?? '政策对话'}</h2><span className="muted">个人会话</span></div>
              {detailLoading && <p className="request-status" role="status">正在读取会话…</p>}
              {!conversation?.messages?.length && !detailLoading && <div className="empty-state"><span className="document-icon" aria-hidden="true">≡</span><h3>{conversationId ? '从一个政策问题开始' : '新建会话，开始查阅政策'}</h3><p>问题、回答和原文依据会保存在你的会话中。</p>{identity && !conversationId && <button className="quiet-button" onClick={() => void createConversation()} disabled={creating}>创建第一个会话</button>}</div>}
              {conversation?.has_more && <button className="quiet-button" disabled={detailLoading || sending} onClick={() => void loadEarlier()}>加载更早的消息</button>}
              <div className="conversation-log" role="log" aria-label="个人政策问答对话">{conversation?.messages?.map(message => <ChatMessage key={message.id ?? message.request_id} message={message} api={api} onCitation={reference => setCitation({message, reference})} />)}</div>
              {pending && <section className="pending-operation" aria-label="待处理问题"><p className="pending-question">{pending.question}</p><p role="status">{sending ? '正在检索政策并生成回答，可能需要较长时间。请保留此页面。' : '发现尚未确认完成的提问。页面不会自动重复提交，请手动恢复原操作。'}</p><p className="muted">模式：{pending.mode} · {pending.knowledgeBase === 'managed' ? '托管政策库' : '冻结 HR 库'} · 恢复时保持原问题、知识库与操作编号</p><div className="pending-actions"><button className="primary-button" onClick={() => void send(pending)} disabled={sending}>使用原操作重试</button><button className="quiet-button" onClick={discard} disabled={sending}>放弃本地恢复</button></div></section>}
            </section>
            <form className="question-card" onSubmit={submit}><label htmlFor="question">想了解哪项政策？</label><textarea id="question" value={question} onChange={event => {setQuestion(event.target.value); if (identity) localWrite(draftKey(identity.user_id), event.target.value);}} placeholder="例如：培训资助获批后，还需要单独申请休假吗？" maxLength={2000} required disabled={!identity || !conversationId || sending || Boolean(pending)} /><div className="composer-footer"><div className="composer-options"><div><label className="mode-label" htmlFor="knowledge-base">知识库</label><select id="knowledge-base" value={knowledgeBase} onChange={event => setKnowledgeBase(event.target.value as KnowledgeBase)} disabled={sending || Boolean(pending)}><option value="frozen">冻结HR库（68份政策）</option><option value="managed">托管政策库（管理员上传）</option></select></div><div><label className="mode-label" htmlFor="mode">检索模式</label><select id="mode" value={mode} onChange={event => setMode(event.target.value as Mode)} disabled={sending || Boolean(pending)}><option value="naive">naive · 文本检索</option><option value="mix">mix · 图与文本</option></select></div>{knowledgeBase === 'managed' && <p>仅检索已完成索引的上传政策。空库或缺少依据时，系统会明确说明。</p>}<p>请勿输入个人工资、证件或其他敏感记录。</p></div><button className="primary-button" disabled={!identity || !conversationId || !question.trim() || sending || Boolean(pending)}>{sending ? '处理中…' : '发送问题 →'}</button></div></form>
          </>}
          <p className="policy-note">回答用于理解公开政策。引用编号有效不代表结论必然正确，请核对适用地区、条件与例外。</p>
        </div>
      </main>
    </div>
    {citation && <CitationDrawer key={`${citation.message.request_id}:${citation.reference.reference_id}`} api={api} message={citation.message} reference={citation.reference} close={() => setCitation(null)} />}
  </>;
}

function ChatMessage({message, api, onCitation}: {message: Message; api: Api; onCitation: (reference: Reference) => void}) {
  const [feedback, setFeedback] = useState<boolean | null>(message.feedback?.helpful ?? null);
  const [comment, setComment] = useState(message.feedback?.comment ?? '');
  const [feedbackStatus, setFeedbackStatus] = useState('');
  const [busy, setBusy] = useState(false);
  async function saveFeedback(helpful: boolean) {
    if (busy) return;
    setBusy(true); setFeedbackStatus('');
    try {await api(`/api/v1/messages/${encodeURIComponent(message.request_id)}/feedback`, 'PUT', {helpful, comment: comment.trim()}); setFeedback(helpful); setFeedbackStatus('反馈已保存。');}
    catch (failure) {if (!ignoreStale(failure)) setFeedbackStatus(errorText(failure));}
    finally {setBusy(false);}
  }
  return <article className="chat-turn">
    <div className="chat-message chat-user"><span className="chat-speaker">你</span><p>{message.question}</p></div>
    <div className="chat-message chat-assistant">
      <div className="section-heading"><span className="chat-speaker">DocTrace</span><span className="muted">{message.historical_import ? message.actual_mode ?? '模式未记录' : message.mode} · {message.historical_import ? message.corpus_id ?? '原知识库未记录' : message.knowledge_base === 'managed' ? '托管政策库' : '冻结 HR 库'} · {message.status === 'completed' ? '已完成' : message.status}</span></div>
      <div className="answer-content">{message.answer || '此条提问尚未保存可用回答。'}</div>
      {message.retrieval?.degraded === true && <p className="degraded">本次检索已降级，请仔细核对依据。</p>}
      <div className="reference-list" aria-label="答案引用">{message.references?.map((reference, index) => <button className="reference-button" key={`${reference.reference_id}:${index}`} onClick={() => onCitation(reference)}>[{reference.reference_id}] {reference.file_path}</button>)}</div>
      {message.answer && <details className="feedback"><summary>这条回答有帮助吗？</summary><label htmlFor={`feedback-${message.request_id}`}>补充意见（可选）</label><textarea id={`feedback-${message.request_id}`} value={comment} onChange={event => setComment(event.target.value)} maxLength={1000} rows={2} /><div className="feedback-actions"><button className="quiet-button" aria-pressed={feedback === true} disabled={busy} onClick={() => void saveFeedback(true)}>有帮助</button><button className="quiet-button" aria-pressed={feedback === false} disabled={busy} onClick={() => void saveFeedback(false)}>需要改进</button></div><p role="status">{feedbackStatus}</p></details>}
    </div>
  </article>;
}

function CitationDrawer({message, reference, api, close}: {message: Message; reference: Reference; api: Api; close: () => void}) {
  const [evidence, setEvidence] = useState<Reference | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
      if (event.key === 'Tab') {event.preventDefault(); closeButton.current?.focus();}
    }
    document.addEventListener('keydown', key);
    return () => {document.removeEventListener('keydown', key); previous?.focus();};
  }, [close]);
  useEffect(() => {
    let current = true;
    void api<Reference>(`/api/v1/citations/${encodeURIComponent(message.request_id)}/${encodeURIComponent(String(reference.reference_id))}`).then(data => {if (current) setEvidence(data);}).catch(failure => {if (current && !ignoreStale(failure)) setError(errorText(failure));}).finally(() => {if (current) setLoading(false);});
    return () => {current = false;};
  }, [message.request_id, reference.reference_id, api]);
  const content = evidence?.content;
  return <div className="drawer-backdrop" onClick={close}><aside className="citation-drawer" role="dialog" aria-modal="true" aria-labelledby="citation-title" onClick={event => event.stopPropagation()}><div className="section-heading"><h2 id="citation-title">原文依据 [{reference.reference_id}]</h2><button ref={closeButton} className="quiet-button" onClick={close}>关闭</button></div><p className="source-file">{evidence?.file_path ?? reference.file_path}</p>{loading && <p role="status">正在读取你有权查看的引用…</p>}{error && <p className="error-message" role="alert">{error}</p>}{evidence && <pre>{Array.isArray(content) ? content.join('\n\n') : content || '此来源没有保存原文片段。'}</pre>}<p className="muted">原文按纯文本显示。内容来自本条回答已保存的引用。</p></aside></div>;
}

function AdminPanel({api}: {api: Api}) {
  const [documents, setDocuments] = useState<AdminItem[]>([]);
  const [reports, setReports] = useState<AdminItem[]>([]);
  const [tasks, setTasks] = useState<AdminItem[]>([]);
  const [editing, setEditing] = useState<AdminItem | null>(null);
  const [selectedReport, setSelectedReport] = useState<unknown>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let current = true; setLoading(true); setError('');
    const load = async () => {
      const results = await Promise.allSettled([api<ItemList<AdminItem> | AdminItem[]>('/api/v1/admin/documents'), api<ItemList<AdminItem>>('/api/v1/admin/reports'), api<AdminItem[]>('/api/v1/admin/tasks')]);
      if (!current) return;
      const [docs, reportList, taskList] = results;
      if (docs.status === 'fulfilled') setDocuments(Array.isArray(docs.value) ? docs.value : docs.value.items ?? []);
      if (reportList.status === 'fulfilled') setReports(reportList.value.items ?? []);
      if (taskList.status === 'fulfilled') setTasks(taskList.value);
      const failures = results.filter((value): value is PromiseRejectedResult => value.status === 'rejected');
      if (failures.some(value => !ignoreStale(value.reason))) setError('部分管理信息暂时无法读取，请刷新重试。');
      setLoading(false);
    };
    void load(); return () => {current = false;};
  }, [api, refresh]);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || busy) return;
    if (!/\.(txt|md)$/i.test(file.name)) {setError('当前仅支持 UTF-8 编码的 .txt 和 .md 文件，暂不支持 PDF、Word 或表格。'); return;}
    if (file.size > 1024 * 1024) {setError('当前单文件上限为 1 MB。'); return;}
    setBusy(true); setError(''); setStatus('');
    try {
      const content = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer());
      if (!content.trim()) throw new Error('文件内容不能为空。');
      await api(editing ? `/api/v1/admin/documents/${encodeURIComponent(String(editing.doc_id))}` : '/api/v1/admin/documents', editing ? 'PUT' : 'POST', {filename: file.name, content});
      setStatus('文档已保存，尚未完成索引。请为该文档提交索引任务，并刷新查看处理状态。');
      setFile(null); setEditing(null); setRefresh(value => value + 1);
    } catch (failure) {if (!ignoreStale(failure)) setError(failure instanceof TypeError ? '文件不是有效 UTF-8 文本，请转换编码后重试。' : errorText(failure));}
    finally {setBusy(false);}
  }
  async function documentAction(item: AdminItem, action: 'index' | 'retire') {
    if (busy) return;
    if (action === 'retire' && !window.confirm('确认停用此文档？已建立的索引将进入删除任务，完成前请核对状态。')) return;
    setBusy(true); setError(''); setStatus('');
    const path = `/api/v1/admin/documents/${encodeURIComponent(String(item.doc_id))}`;
    try {
      await api(action === 'index' ? `${path}/index` : path, action === 'index' ? 'POST' : 'DELETE', {});
      setStatus(action === 'index' ? '索引任务已进入队列。排队不代表处理完成，请刷新核对状态。' : '停用请求已保存，请刷新核对文档和删除任务状态。');
      setRefresh(value => value + 1);
    } catch (failure) {if (!ignoreStale(failure)) setError(errorText(failure));}
    finally {setBusy(false);}
  }
  async function openReport(item: AdminItem) {
    setError(''); setSelectedReport(null);
    const id = item.report_id ?? item.id;
    if (!id) {setSelectedReport(item); return;}
    try {setSelectedReport(await api(`/api/v1/admin/reports/${encodeURIComponent(String(id))}`));}
    catch (failure) {if (!ignoreStale(failure)) setError(errorText(failure));}
  }
  return <section className="admin-panel" aria-label="知识库与实验报告"><div className="section-heading"><h2>知识库与实验报告</h2><button className="quiet-button" onClick={() => setRefresh(value => value + 1)} disabled={loading}>刷新状态</button></div><p className="muted">上传文档进入独立的可写知识库，不会修改冻结实验语料。</p>{error && <p className="error-message" role="alert">{error}</p>}{loading && <p role="status">正在读取管理信息…</p>}<form className="upload-form" onSubmit={event => void upload(event)}><label htmlFor="document-file">上传政策文档</label>{editing && <p>更新 {String(editing.filename)} 的版本。<button type="button" className="quiet-button" onClick={() => setEditing(null)}>取消更新</button></p>}<input id="document-file" type="file" accept=".txt,.md,text/plain,text/markdown" onChange={event => setFile(event.target.files?.[0] ?? null)} disabled={busy} /><p className="muted">支持 UTF-8 .txt / .md，单文件最多 1 MB。PDF、Word 和表格暂不支持。</p><button className="primary-button" disabled={!file || busy}>{busy ? '正在提交…' : editing ? '保存新版本' : '提交文档'}</button><p role="status">{status}</p></form><h3>文档与任务状态</h3>{documents.length === 0 && !loading && <p className="muted">尚无可显示的上传文档。</p>}<ul className="admin-list">{documents.map((item, index) => <li key={String(item.doc_id ?? item.id ?? index)}><strong>{String(item.filename ?? item.title ?? item.doc_id ?? '文档')}</strong><p>版本 {String(item.version ?? '—')} · 状态 {String(item.state ?? '未知')}</p><div className="feedback-actions"><button className="quiet-button" disabled={busy || !['draft', 'failed'].includes(String(item.state))} onClick={() => void documentAction(item, 'index')}>提交索引</button><button className="quiet-button" disabled={busy || !['draft', 'processed', 'failed'].includes(String(item.state))} onClick={() => {setEditing(item); setFile(null);}}>更新版本</button><button className="quiet-button" disabled={busy || item.state === 'retired'} onClick={() => void documentAction(item, 'retire')}>停用文档</button></div><details><summary>查看版本详情</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></li>)}</ul><details className="task-list"><summary>索引与删除任务（{tasks.length}）</summary>{tasks.map((item, index) => <pre key={String(item.task_id ?? index)}>{JSON.stringify(item, null, 2)}</pre>)}</details><h3>只读实验报告</h3><p className="muted">历史覆盖率、回答质量与运行状态分别核对。此页面不会发起付费评测。</p><ul className="report-list">{reports.map((item, index) => <li key={String(item.report_id ?? item.id ?? index)}><button className="quiet-button" onClick={() => void openReport(item)}>{String(item.title ?? item.report_id ?? item.id ?? `报告 ${index + 1}`)}</button></li>)}</ul>{!reports.length && !loading && <p className="muted">没有可读取的报告。</p>}{selectedReport !== null && <div className="report-detail"><h3>报告内容</h3><pre>{JSON.stringify(selectedReport, null, 2)}</pre></div>}</section>;
}
