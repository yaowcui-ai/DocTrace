import { getIdentity, setIdentity, onIdentityChange } from "./auth-state.js";
import { invalidateRecordSelection } from "./record-detail.js";
import { clearOwnerOperations } from "./pending-operation.js";
import { clearConversation } from "./conversation.js";

const form = document.getElementById("login-form");
const status = document.getElementById("auth-status");
const logoutButton = document.getElementById("logout-button");
const loginButton = document.getElementById("login-button");
let busy = false;
let authSequence = 0;
let logoutUnconfirmed = false;
const CHANNEL_KEY = "doctrace.auth-change.v1";

function resetPrivateView() {
  invalidateRecordSelection();
  clearConversation();
  for (const id of ["answer-content", "selected-question", "record-info", "reference-list", "history-list", "error-message", "request-status", "answer-meta", "pending-question"]) document.getElementById(id).replaceChildren();
  for (const id of ["answer-content", "selected-question", "record-info", "evidence-panel", "pending-operation", "error-message"]) document.getElementById(id).hidden = true;
  document.getElementById("answer-empty").hidden = false;
  document.getElementById("question").value = "";
    document.getElementById("retrieval-mode").value = "naive";
}
function showIdentity() {
  const {user} = getIdentity();
  form.hidden = Boolean(user);
  logoutButton.hidden = !user && !logoutUnconfirmed;
  loginButton.disabled = busy;
  logoutButton.disabled = busy;
  status.textContent = user ? `当前账户：${user.username}` : "请先登录，个人问答仅自己可见。";
}
onIdentityChange(() => { resetPrivateView(); showIdentity(); }, true);
function broadcast() {
  try { localStorage.setItem(CHANNEL_KEY, crypto.randomUUID()); } catch { /* Optional cross-tab notification. */ }
}
async function refreshIdentity() {
  if (busy) return;
  const sequence = ++authSequence;
  try {
    const response = await fetch("/auth/me", {credentials:"same-origin",cache:"no-store"});
    if (sequence !== authSequence) return;
    if (response.status === 401) setIdentity(null);
    else if (response.ok) {
      const identity = await response.json();
      if (sequence !== authSequence) return;
      setIdentity(identity);
    } else throw new Error("Identity service unavailable");
    showIdentity();
  } catch {
    if (sequence !== authSequence) return;
    setIdentity(null);
    showIdentity();
    status.textContent = "暂时无法确认登录状态，请稍后刷新。";
  }
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const sequence = ++authSequence;
  showIdentity();
  const password = document.getElementById("login-password");
  const body = JSON.stringify({username:document.getElementById("login-username").value, password:password.value});
  password.value = "";
  try {
    const response = await fetch("/auth/login", {method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body});
    const result = await response.json();
    if (sequence !== authSequence) return;
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "登录未成功。");
    logoutUnconfirmed = false;
    setIdentity(result);
    broadcast();
    showIdentity();
  } catch (error) { status.textContent = error.message || "未能确认登录结果，请重试。"; }
  finally { busy=false; loginButton.disabled=false; logoutButton.disabled=false; }
});
logoutButton.addEventListener("click", async () => {
  if (busy) return;
  busy=true;
  ++authSequence;
  const previous = getIdentity().user;
  if (previous) { try { clearOwnerOperations(previous.user_id); } catch { /* Private view still cleared. */ } }
  logoutUnconfirmed=true;
  setIdentity(null);
  resetPrivateView();
  showIdentity();
  try {
    const response = await fetch("/auth/logout", {method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:"{}"});
    if (!response.ok) throw new Error("退出未确认，请再次点击退出登录。");
    logoutUnconfirmed=false;
    broadcast();
    showIdentity();
    status.textContent="已退出登录。";
  } catch (error) { status.textContent=error.message; }
  finally { busy=false; loginButton.disabled=false; logoutButton.disabled=false; }
});
window.addEventListener("storage", event => {
  if (event.key === CHANNEL_KEY) { setIdentity(null); refreshIdentity(); }
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !logoutUnconfirmed) refreshIdentity();
});
window.addEventListener("pageshow", event => { if (event.persisted) {setIdentity(null);refreshIdentity();} });
// Pre-account storage has no trustworthy owner and must never be restored.
try { sessionStorage.removeItem("doctrace.pending-question.v1"); } catch { /* Optional browser storage. */ }
resetPrivateView();
refreshIdentity();
