import { getIdentity, isCurrent, onIdentityChange, privateFetch } from "./auth-state.js";
import { loadHistory } from "./history.js";
import {
  setQuestionBusy,
  showQuestionWaiting,
  showSubmittedAnswer,
  showQuestionFailure,
  showPendingOperation,
} from "./question-view.js";
import {
  createPendingOperation,
  readPendingOperation,
  clearPendingOperation,
} from "./pending-operation.js";
const form = document.getElementById("question-form");
const questionInput = document.getElementById("question");
const modeInput = document.getElementById("retrieval-mode");

let submitting = false;
function restorePendingOperation() {
  if (!getIdentity().user) { showPendingOperation(null); return null; }
  const operation = readPendingOperation(getIdentity().user.user_id);
  showPendingOperation(operation);
  return operation;
}
async function submitQuestion(event) {
  event.preventDefault();
  if (!getIdentity().user) { showQuestionFailure("请先登录。"); return; }

  if (submitting) {
    return;
  }

  const question = questionInput.value.trim();

  if (!question) {
    showQuestionFailure("请输入问题。");
    return;
  }

  if (question.length > 2000) {
    showQuestionFailure("问题不能超过 2000 个字符。");
    return;
  }

  let operation;

  try {
    if (restorePendingOperation()) {
      showQuestionFailure("请先重试原请求，或结束跟踪后再提交新问题。");
      return;
    }

    operation = createPendingOperation(question, getIdentity().user.user_id, modeInput.value);
    showPendingOperation(operation);
  } catch {
    showQuestionFailure("无法保存或读取提问操作，本次没有发送请求。");
    return;
  }

  await sendOperation(operation);
}

async function sendOperation(operation) {
  if (submitting) return;

  const identity = getIdentity();
  if (!identity.user) return;
  const question = operation.question;

  submitting = true;
  setQuestionBusy(true);
  showQuestionWaiting(question, operation.key);
  try {
    const response = await privateFetch("/ask/optimized", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": operation.key,
      },
      body: JSON.stringify({ question, mode: operation.mode ?? "mix" }),
    });

    const body = await response.json();
    if (!isCurrent(identity)) return;

    if (!response.ok) {
      const detail = body.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message ?? "请求未成功完成。";

      showQuestionFailure(
        message,
        detail?.request_id ?? null,
        detail?.stage ?? null,
        response.status
      );
      return;
    }

    if (
      typeof body.response !== "string" ||
      !Array.isArray(body.references) ||
      typeof body.request_id !== "string"
    ) {
      throw new Error("Invalid answer response");
    }

    showSubmittedAnswer(body, question, operation.key);
    try {
      clearPendingOperation(operation.key, identity.user.user_id);
      restorePendingOperation();
    } catch {
      showQuestionFailure(
        "答案已保存，但本页操作记录清理失败，请先查看历史记录。"
      );
    }
  } catch {
    if (!isCurrent(identity)) return;
    showQuestionFailure(
      "未能确认本次请求结果。服务端可能仍在处理，请先刷新历史记录核对，避免重复提交。"
    );
  } finally {
    if (isCurrent(identity)) {
      submitting = false;
      setQuestionBusy(false);
      await loadHistory(0);
    }
  }
}

async function retryPending() {
  if (!getIdentity().user) return;
  if (submitting) return;

  let operation;
  try {
    operation = restorePendingOperation();
  } catch {
    showQuestionFailure("无法读取原操作，本次没有发送请求。");
    return;
  }

  if (operation) {
    await sendOperation(operation);
  }
}

function discardPending() {
  const identity = getIdentity();
  if (!identity.user) return;
  if (submitting) return;

  try {
    const operation = readPendingOperation(getIdentity().user?.user_id);
    if (operation) {
      clearPendingOperation(operation.key, identity.user.user_id);
    }
    restorePendingOperation();
  } catch {
    showQuestionFailure("无法清除本页操作记录，请先查看历史记录。");
  }
}

form.addEventListener("submit", submitQuestion);
document.getElementById("retry-pending")
  .addEventListener("click", retryPending);
document.getElementById("discard-pending")
  .addEventListener("click", discardPending);

setQuestionBusy(false);

try {
  restorePendingOperation();
} catch {
  showQuestionFailure("无法读取本页保存的操作，请先查看历史记录。");
}
onIdentityChange(() => {
  submitting = false;
  setQuestionBusy(false);
  try { restorePendingOperation(); }
  catch { showQuestionFailure("无法读取本账号的待确认操作。"); }
});
