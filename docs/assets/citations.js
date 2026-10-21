export function linkCitations(container, targets) {
  const doc = container.ownerDocument;

  // 收集答案中的文字节点，跳过代码和已有链接、按钮。
  const walker = doc.createTreeWalker(
    container,
    doc.defaultView.NodeFilter.SHOW_TEXT
  );
  const nodes = [];

  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement.closest("pre, code, a, button")) {
      nodes.push(node);
    }
  }

  // 将能匹配到证据的 [编号] 替换成按钮。
  for (const node of nodes) {
    const text = node.textContent;
    const fragment = doc.createDocumentFragment();
    let position = 0;

    for (const match of text.matchAll(/\[(\d+)\]/g)) {
      const target = targets.get(match[1]);
      if (!target) continue;

      fragment.append(text.slice(position, match.index));

      const button = doc.createElement("button");
      button.type = "button";
      button.className = "citation-button";
      button.textContent = match[0];
      button.setAttribute("aria-label", `查看证据 ${match[1]}`);

      button.addEventListener("click", () => {
        for (const item of targets.values()) {
          item.classList.remove("evidence-selected");
        }

        target.open = true;
        target.classList.add("evidence-selected");
        target.tabIndex = -1;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        target.focus({ preventScroll: true });
      });

      fragment.append(button);
      position = match.index + match[0].length;
    }

    if (position > 0) {
      fragment.append(text.slice(position));
      node.replaceWith(fragment);
    }
  }
}