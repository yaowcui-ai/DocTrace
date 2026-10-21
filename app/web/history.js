import { getIdentity, onIdentityChange, isCurrent, privateFetch } from "./auth-state.js";
import { renderHistory } from "./history-view.js";
import { loadRecord, loadConversationRecords } from "./record-detail.js";

const historyStatus = document.getElementById("history-status");
const refreshButton = document.getElementById("refresh-history");
const previousButton = document.getElementById("history-prev");
const nextButton = document.getElementById("history-next");
const pageLabel = document.getElementById("history-page");

const PAGE_SIZE = 2;

let historyOffset = 0;
let nextOffset = null;
let loadingHistory = false;

function updatePagination() {
  refreshButton.disabled = loadingHistory || !getIdentity().user;
  previousButton.disabled = !getIdentity().user || loadingHistory || historyOffset === 0;
  nextButton.disabled = !getIdentity().user || loadingHistory || nextOffset === null;

  pageLabel.textContent =
    `第 ${Math.floor(historyOffset / PAGE_SIZE) + 1} 页`;
}

export async function loadHistory(offset = historyOffset) {
  if (loadingHistory || !getIdentity().user) {
    return;
  }

  const identity = getIdentity();
  loadingHistory = true;
  updatePagination();
  historyStatus.textContent = "正在读取历史记录…";

  try {
    const response = await privateFetch(
      `/records?limit=${PAGE_SIZE}&offset=${offset}`,
      { cache: "no-store" }
    );

    if (!response.ok) {
      throw new Error("History request failed");
    }

    const data = await response.json();
    if (!isCurrent(identity)) return;

    if (!Array.isArray(data.items)) {
      throw new Error("Invalid history data");
    }

    renderHistory(data.items, loadRecord);

    historyOffset = offset;
    nextOffset = data.next_offset;

    historyStatus.textContent =
      data.items.length === 0
        ? "本页暂无记录。"
        : `本页 ${data.items.length} 条记录`;
    await loadConversationRecords(data.items);
  } catch {
    if (!isCurrent(identity)) return;
    historyStatus.textContent = "读取历史失败，请点击刷新重试。";
  } finally {
    if (isCurrent(identity)) { loadingHistory = false; updatePagination(); }
  }
}

refreshButton.addEventListener("click", () => {
  loadHistory(historyOffset);
});

previousButton.addEventListener("click", () => {
  loadHistory(Math.max(0, historyOffset - PAGE_SIZE));
});

nextButton.addEventListener("click", () => {
  if (nextOffset !== null) {
    loadHistory(nextOffset);
  }
});

onIdentityChange(() => {
  historyOffset=0; nextOffset=null; loadingHistory=false;
  document.getElementById("history-list").replaceChildren();
  historyStatus.textContent="请登录后查看自己的问答。";
  updatePagination();
  if (getIdentity().user) loadHistory(0);
});
updatePagination();
