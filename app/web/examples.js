import { renderPublicExamples, renderPublicExample, clearPublicExample } from "./examples-view.js";

// 公开快照独立读取，不携带登录 Cookie，也不提交问答请求。
const options = { method: "GET", credentials: "omit", cache: "no-store" };
let selection = 0;

export async function loadPublicExample(id) {
  const current = ++selection;
  const status = document.getElementById("public-example-status");
  clearPublicExample();
  status.textContent = "正在读取示例…";
  try {
    const response = await fetch(`/examples/${encodeURIComponent(id)}`, options);
    if (current !== selection) return;
    if (response.status === 404) {
      status.textContent = "该示例已下架或不存在，请刷新示例列表。";
      return;
    }
    if (!response.ok) throw new Error("public_example_read_failed");
    const example = await response.json();
    // 连续点击时，较早的慢请求不能覆盖新的选择。
    if (current !== selection) return;
    renderPublicExample(example);
    status.textContent = "";
  } catch {
    if (current !== selection) return;
    clearPublicExample();
    status.textContent = "示例读取失败，请稍后重试。";
  }
}

async function loadPublicExamples() {
  const refresh = document.getElementById("refresh-examples");
  const status = document.getElementById("public-examples-status");
  refresh.disabled = true;
  ++selection;
  clearPublicExample();
  document.getElementById("public-example-status").textContent = "";
  renderPublicExamples([], loadPublicExample);
  status.textContent = "正在读取公开示例…";
  try {
    const response = await fetch("/examples?limit=10&offset=0", options);
    if (!response.ok) throw new Error("public_examples_read_failed");
    const result = await response.json();
    renderPublicExamples(result.items, loadPublicExample);
    status.textContent = result.items.length === 0 ? "暂无公开示例。" :
      result.has_more ? "当前展示最新 10 条公开示例。" : "点击问题查看已保存的答案。";
  } catch {
    status.textContent = "公开示例加载失败，可点击刷新重试。";
  } finally {
    refresh.disabled = false;
  }
}

document.getElementById("refresh-examples").addEventListener("click", loadPublicExamples);
export const initialLoad = loadPublicExamples();
