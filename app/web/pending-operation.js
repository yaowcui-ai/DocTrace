const STORAGE_PREFIX = "doctrace.pending-question.v2:";
function storageKey(owner) {
  if (!UUID_PATTERN.test(owner)) throw new Error("需要有效的用户身份。");
  return STORAGE_PREFIX + owner;
}
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// 主动发起一次新操作：生成新键，并保存原问题。
export function createPendingOperation(question, owner, mode = "naive") {
  if (!["naive", "mix"].includes(mode)) throw new Error("检索模式无效。");
  const operation = {
    key: crypto.randomUUID(),
    question,
    mode,
  };

  sessionStorage.setItem(
    storageKey(owner),
    JSON.stringify(operation)
  );

  return operation;
}

// 恢复原操作：读取时不生成新键。
export function readPendingOperation(owner) {
  const raw = sessionStorage.getItem(storageKey(owner));
  if (raw === null) return null;

  const operation = JSON.parse(raw);

  if (
    !UUID_PATTERN.test(operation?.key) ||
    typeof operation?.question !== "string" ||
    operation.question.trim().length === 0 ||
    operation.question.length > 2000
  ) {
    throw new Error("保存的提问操作格式异常。");
  }

  // 无模式的旧操作创建于固定 mix 阶段，重试不能改用新的默认 naive。
  if (!Object.hasOwn(operation, "mode")) operation.mode = "mix";
  if (!["naive", "mix"].includes(operation.mode)) throw new Error("保存的检索模式无效。");

  return operation;
}

// 只清除指定操作，避免旧结果误删新操作。
export function clearPendingOperation(key, owner) {
  const current = readPendingOperation(owner);

  if (current?.key === key) {
    sessionStorage.removeItem(storageKey(owner));
  }
}
// Logout clears only this account's pending browser operation.
export function clearOwnerOperations(owner) {
  sessionStorage.removeItem(storageKey(owner));
}
