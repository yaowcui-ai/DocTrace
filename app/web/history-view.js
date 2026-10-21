// Display helpers: user content is always text, never executable HTML.
const STATUS_LABELS = {
  processing: "未完成",
  completed: "已完成",
  failed: "失败",
};

export function renderHistory(items, onSelect) {
  const fragment = document.createDocumentFragment();

  for (const record of items) {
    const item = document.createElement("li");
    const card = document.createElement("button");
    card.type = "button";
    card.className = "history-item";
    card.dataset.requestId = record.request_id;
    if (document.querySelector('.chat-turn[aria-current="true"]')?.dataset.requestId === record.request_id) {
      card.setAttribute('aria-current', 'true');
    }

    card.addEventListener("click", () => {
      onSelect(record.request_id);
    });

    const title = document.createElement("span");
    title.className = "history-item-title";
    title.textContent = record.question;

    const meta = document.createElement("span");
    meta.className = "history-item-meta";
    const created = new Date(record.created_at).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    const status = STATUS_LABELS[record.status] ?? "未知状态";
    meta.textContent = `${status} · ${created}`;

    card.append(title, meta);
    item.append(card);
    fragment.append(item);
  }

  document.getElementById("history-list").replaceChildren(fragment);
}
