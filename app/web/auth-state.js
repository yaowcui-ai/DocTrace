// Identity lives only in memory. The session credential remains in HttpOnly Cookie.
let user = null;
let revision = 0;
const listeners = new Set();

export function getIdentity() { return { user, revision }; }
export function setIdentity(next) {
  if (user?.user_id === next?.user_id && user?.username === next?.username) return;
  user = next;
  revision += 1;
  for (const listener of listeners) listener(getIdentity());
}
export function onIdentityChange(listener, first = false) {
  if (first) {
    const existing = [...listeners];
    listeners.clear();
    listeners.add(listener);
    for (const previous of existing) listeners.add(previous);
  }
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function isCurrent(snapshot) {
  return snapshot.revision === revision && snapshot.user?.user_id === user?.user_id;
}
export async function privateFetch(url, options = {}) {
  const snapshot = getIdentity();
  if (!snapshot.user) throw new Error("请先登录。");
  const headers = new Headers(options.headers);
  headers.set("X-DocTrace-User-ID", snapshot.user.user_id);
  const response = await fetch(url, { ...options, headers, credentials: "same-origin", cache: "no-store" });
  if (!isCurrent(snapshot)) throw new Error("登录身份已改变。");
  if (response.status === 401 || response.status === 409 && response.headers.get("X-DocTrace-Identity-Changed") === "1") {
    setIdentity(null);
    throw new Error("登录已失效，请重新登录。");
  }
  return response;
}
