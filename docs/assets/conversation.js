// One saved QA record is one turn. This view never adds model conversation history.
const FIELD_IDS = ['selected-question', 'answer-content', 'record-info',
  'answer-meta', 'evidence-panel', 'reference-list'];

const log = () => document.getElementById('conversation-log');
const turns = () => [...log().querySelectorAll('.chat-turn')];

export function recordTurn(requestId) {
  return turns().find(turn => turn.dataset.requestId === String(requestId)) ?? null;
}

export function turnFields(turn) {
  return Object.fromEntries(FIELD_IDS.map(name => [name,
    turn.querySelector(`[data-field="${name}"]`)]));
}

function activate(turn) {
  // Keep the existing current-record DOM IDs, with only one owner at a time.
  for (const other of turns()) {
    other.removeAttribute('aria-current');
    for (const element of other.querySelectorAll('[data-field]')) element.removeAttribute('id');
  }
  turn.setAttribute('aria-current', 'true');
  for (const [name, element] of Object.entries(turnFields(turn))) element.id = name;
  for (const button of document.querySelectorAll('#history-list [data-request-id]')) {
    if (button.dataset.requestId === turn.dataset.requestId) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  }
}

export function focusRecord(requestId) {
  const turn = recordTurn(requestId);
  if (!turn) return false;
  focusTurn(turn);
  return true;
}

export function focusTurn(turn) {
  activate(turn);
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  turn.scrollIntoView?.({behavior: reduced ? 'auto' : 'smooth', block: 'start'});
  turn.focus({preventScroll:true});
}

export function acquireTurn(record, {operationKey, focus = true} = {}) {
  const pending = operationKey
    ? turns().find(turn => turn.dataset.operationKey === operationKey) : null;
  let turn = record.request_id ? recordTurn(record.request_id) : pending;
  if (turn && pending && turn !== pending) pending.remove();
  turn ??= pending ?? turns().find(t => !t.dataset.requestId && !t.dataset.operationKey);
  if (!turn) {
    turn = document.getElementById('chat-turn-template').content.firstElementChild.cloneNode(true);
    log().append(turn);
  }
  if (record.request_id) {
    turn.dataset.requestId = String(record.request_id);
    delete turn.dataset.operationKey;
  } else if (operationKey) turn.dataset.operationKey = operationKey;
  const timestamp = Date.parse(record.created_at);
  if (Number.isFinite(timestamp)) turn.dataset.orderTime = String(timestamp);
  else turn.dataset.orderTime ??= String(Date.now());
  for (const row of turns().sort((a,b) => Number(a.dataset.orderTime) - Number(b.dataset.orderTime))) log().append(row);
  turn.hidden = false;
  document.getElementById('answer-empty').hidden = true;
  if (focus || !log().querySelector('.chat-turn[aria-current="true"]')) activate(turn);
  return turn;
}

export function beginPendingTurn(question, operationKey) {
  const turn = acquireTurn({question}, {operationKey});
  const fields = turnFields(turn);
  fields['selected-question'].textContent = question;
  fields['selected-question'].hidden = false;
  fields['answer-content'].classList.remove('markdown-answer');
  fields['answer-content'].textContent = '正在查找政策并生成回答…';
  fields['answer-content'].hidden = false;
  fields['answer-meta'].textContent = '处理中';
  fields['record-info'].textContent = '';
  fields['record-info'].hidden = true;
  fields['evidence-panel'].hidden = true;
  fields['reference-list'].replaceChildren();
  turn.dataset.status = 'processing';
  turn.dataset.operationKey = operationKey;
  focusTurn(turn);
  return turn;
}

export function showPendingFailure(turn, message, requestId) {
  if (!turn?.isConnected) return;
  const fields = turnFields(turn);
  if (requestId) {
    const duplicate = recordTurn(requestId);
    // A committed history answer is stronger evidence than an uncertain transport result.
    if (duplicate?.dataset.status === 'completed') {
      if (duplicate !== turn) turn.remove();
      focusTurn(duplicate);
      return;
    }
    if (duplicate && duplicate !== turn) duplicate.remove();
    turn.dataset.requestId = requestId;
  }
  fields['answer-content'].classList.remove('markdown-answer');
  fields['answer-content'].textContent = message;
  fields['answer-meta'].textContent = '请核对请求结果';
  turn.dataset.status = 'unconfirmed';
}

export function clearConversation() {
  const placeholder = document.getElementById('chat-turn-template').content.firstElementChild.cloneNode(true);
  placeholder.hidden = true;
  log().replaceChildren(placeholder);
  activate(placeholder);
  document.getElementById('answer-empty').hidden = false;
}
