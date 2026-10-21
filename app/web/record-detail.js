import { getIdentity, isCurrent, privateFetch } from "./auth-state.js";
import { focusRecord, recordTurn } from "./conversation.js";
import {
  renderRecord,
  showRecordLoading,
  showRecordError,
} from "./record-view.js";

let latestSelection = 0;

export function invalidateRecordSelection() {
  latestSelection += 1;
}

export async function loadRecord(requestId) {
  const identity = getIdentity();
  if (!identity.user) return;
  const selection = ++latestSelection;
  if (recordTurn(requestId)?.dataset.status === 'completed') {
    focusRecord(requestId);
    document.getElementById('error-message').hidden = true;
    document.getElementById('request-status').textContent = '已定位到这条问答';
    return;
  }
  showRecordLoading();

  try {
    const response = await privateFetch(
      `/records/${encodeURIComponent(requestId)}`,
      { cache: "no-store" }
    );

    if (!response.ok) {
      throw new Error("Record request failed");
    }

    const record = await response.json();

    if (selection !== latestSelection || !isCurrent(identity)) {
      return;
    }

    renderRecord(record);
  } catch {
    if (selection === latestSelection && isCurrent(identity)) {
      showRecordError();
    }
  }
}

// Load only the displayed history page, using existing read-only detail APIs.
export async function loadConversationRecords(items) {
  const identity = getIdentity();
  if (!identity.user) return;
  const selection = latestSelection;
  const hadTurns = Boolean(document.querySelector('.chat-turn[data-request-id]'));
  const outcomes = await Promise.allSettled(items.map(async item => {
    if (recordTurn(item.request_id)?.dataset.status === 'completed') return;
    const response = await privateFetch(`/records/${encodeURIComponent(item.request_id)}`, {cache:'no-store'});
    if (!response.ok) throw new Error('Record read failed');
    const record = await response.json();
    if (isCurrent(identity)) renderRecord(record, {focus:false});
  }));
  if (!isCurrent(identity)) return;
  if (!hadTurns && selection === latestSelection && items.length) focusRecord(items[0].request_id);
  if (outcomes.some(result => result.status === 'rejected')) {
    document.getElementById('history-status').textContent = '部分历史对话未能加载，可点击对应历史记录重试。';
  }
}
