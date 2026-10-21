import { renderMarkdown } from "./markdown.js";
import { linkCitations } from "./citations.js";
import { acquireTurn, focusTurn, recordTurn, turnFields } from "./conversation.js";
// 答案使用经过清理的 Markdown；问题、错误和原文使用纯文本。
const STATUS_LABELS = { processing: "未完成", completed: "已完成", failed: "失败" };

export function showRecordLoading() {
  document.getElementById("request-status").textContent = "正在读取已保存的问答…";
  document.getElementById("error-message").hidden = true;
}

export function showRecordError() {
  document.getElementById("request-status").textContent = "记录读取失败";
  const message = document.getElementById("error-message");
  message.textContent = "暂时无法读取这条问答，请稍后再次点击记录。";
  message.hidden = false;
}

export function renderRecord(record, options = {}) {
  const existing = recordTurn(record.request_id);
  if (existing?.dataset.status === 'completed' && record.status === 'processing') return existing;
  const turn = acquireTurn(record, options);
  const fields = turnFields(turn);
  turn.dataset.status = record.status;
  const selectedQuestion = fields["selected-question"];
  selectedQuestion.textContent = record.question;
  selectedQuestion.hidden = false;
  document.getElementById("answer-empty").hidden = true;
  if (options.focus !== false) document.getElementById("error-message").hidden = true;

  const content = fields["answer-content"];
  const statusLabel = STATUS_LABELS[record.status] ?? "未知状态";
  content.classList.remove("markdown-answer");

  if (record.status === "completed") {
    renderMarkdown(content, record.answer ?? "这条记录没有保存答案。");
  } else if (record.status === "failed") {
    content.textContent = "这次问答未成功完成。\n" + (record.error_message ?? "未保存具体错误说明。");
  } else {
    content.textContent = "这条请求尚未保存最终结果，可能仍在处理，也可能中途停止。请稍后刷新记录确认。";
  }
  content.hidden = false;
  fields["answer-meta"].textContent = statusLabel;
  if (options.focus !== false) document.getElementById("request-status").textContent = "已定位到这条问答";

  const info = [
    `记录编号：${record.request_id}`,
  ];
  if (record.corpus_id) info.push(`知识库：${record.corpus_id}`);
  if (record.retrieval?.mode) {
    const label = {naive:"标准问答", mix:"关联问答"}[record.retrieval.mode] ?? "检索";
    info.push(`实际检索模式：${label}（${record.retrieval.mode}）`);
  }
  info.push(`原请求状态：${statusLabel}`);
  if (record.http_status !== null) info.push(`原请求 HTTP 状态：${record.http_status}`);
  if (record.error_stage) info.push(`错误阶段：${record.error_stage}`);
  if (record.llm_generated === false) info.push("本条答案未由模型生成。");
  if (record.llm_generated === null) info.push("未确认是否由模型生成。");
  if (record.retrieval?.degraded) info.push("检索发生降级，请结合原文核对答案。");
  const recordInfo = fields["record-info"];
  recordInfo.textContent = info.join("\n");
  recordInfo.hidden = false;

  const references = record.references ?? [];
  const list = fields["reference-list"];
  const fragment = document.createDocumentFragment();
  const targets = new Map();

  for (const reference of references) {
    const details = document.createElement("details");
    targets.set(String(reference.reference_id), details);
    const summary = document.createElement("summary");
    summary.textContent = `[${reference.reference_id}] ${reference.file_path}`;
    details.append(summary);
    for (const chunk of reference.content ?? []) {
      const text = document.createElement("pre");
      text.textContent = chunk;
      details.append(text);
    }
    if (!reference.content?.length) {
      const hint = document.createElement("p");
      hint.textContent = "此记录未保存原文片段。";
      details.append(hint);
    }
    fragment.append(details);
  }
  list.replaceChildren(fragment);
  fields["evidence-panel"].hidden = references.length === 0;
  if (record.status === "completed") {
    linkCitations(content, targets);
  }
  if (options.focus !== false) focusTurn(turn);
  return turn;
}
