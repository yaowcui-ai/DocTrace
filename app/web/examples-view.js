import { renderMarkdown } from "./markdown.js";
import { linkCitations } from "./citations.js";

export function renderPublicExamples(items, onSelect) {
  const list = document.getElementById("public-examples-list");
  list.replaceChildren();
  for (const item of items) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "public-example-item";
    button.textContent = item.question;
    button.addEventListener("click", () => onSelect(item.example_id));
    row.append(button);
    list.append(row);
  }
}

export function clearPublicExample() {
  document.getElementById("public-example-detail").hidden = true;
  for (const id of ["public-example-question", "public-example-meta",
    "public-example-answer", "public-example-references"]) {
    document.getElementById(id).replaceChildren();
  }
}

export function renderPublicExample(example) {
  clearPublicExample();
  document.getElementById("public-example-question").textContent = example.question;
  const date = new Date(example.published_at).toLocaleString("zh-CN");
  document.getElementById("public-example-meta").textContent =
    `已审核发布 · 知识库：${example.corpus_id} · 发布时间：${date}`;
  const answer = document.getElementById("public-example-answer");
  renderMarkdown(answer, example.answer);
  const references = document.getElementById("public-example-references");
  const targets = new Map();
  for (const reference of example.references) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `[${reference.reference_id}] ${reference.file_path}`;
    details.append(summary);
    for (const content of reference.content) {
      const pre = document.createElement("pre");
      pre.textContent = content;
      details.append(pre);
    }
    references.append(details);
    targets.set(reference.reference_id, details);
  }
  linkCitations(answer, targets);
  document.getElementById("public-example-detail").hidden = false;
}
