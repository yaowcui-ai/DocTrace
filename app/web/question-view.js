import { getIdentity } from "./auth-state.js";
import { invalidateRecordSelection } from "./record-detail.js";
import { renderRecord, showRecordLoading } from "./record-view.js";
import { beginPendingTurn, showPendingFailure } from "./conversation.js";
let waitingTurn = null;

export function setQuestionBusy(busy) {
  busy = busy || !getIdentity().user;
  document.getElementById("question").disabled = busy;
  document.getElementById("retrieval-mode").disabled = busy;
  document.getElementById("submit-question").disabled = busy;
  document.getElementById("submit-question").textContent = busy ? "处理中…" : "提交问题 ↗";
  document.getElementById("history-controls").disabled = busy;
  document.getElementById("retry-pending").disabled = busy;
  document.getElementById("discard-pending").disabled = busy;
  document.getElementById("question-form").setAttribute("aria-busy", String(busy));
}

export function showPendingOperation(operation) {
  document.getElementById("pending-operation").hidden = operation === null;
  document.getElementById("pending-question").textContent = operation
    ? `${operation.question}\n原请求模式：${operation.mode ?? "mix"}` : "";
  if (operation) document.getElementById("retrieval-mode").value = operation.mode ?? "mix";
}

export function showQuestionWaiting(question, operationKey) {
  // A detail request started before submission must not replace the new result.
  invalidateRecordSelection();
  showRecordLoading();
  if (question && operationKey) waitingTurn = beginPendingTurn(question, operationKey);
  document.getElementById("request-status").textContent = "正在处理问题，请勿重复提交…";
}

export function showSubmittedAnswer(result, question, operationKey) {
  // POST already confirms a committed answer; no second model call or mandatory GET.
  renderRecord({
    request_id: result.request_id,
    question,
    answer: result.response,
    references: result.references,
    retrieval: result.retrieval ?? null,
    corpus_id: null,
    status: "completed",
    http_status: 200,
    error_stage: null,
    error_message: null,
    llm_generated: result.llm_generated,
  }, {operationKey});
  waitingTurn = null;
  document.getElementById("request-status").textContent = "回答已保存，可从历史记录重新查看。";
}

export function showQuestionFailure(message, requestId = null, stage = null, httpStatus = null) {
  const lines = [message];
  if (httpStatus !== null) lines.push(`HTTP 状态：${httpStatus}`);
  if (stage) lines.push(`阶段：${stage}`);
  if (requestId) lines.push(`记录编号：${requestId}。可从历史记录核对结果。`);
  const panel = document.getElementById("error-message");
  panel.textContent = lines.join("\n");
  panel.hidden = false;
  showPendingFailure(waitingTurn, lines.join("\n"), requestId);
  document.getElementById("request-status").textContent = "请查看下方提示";
}
