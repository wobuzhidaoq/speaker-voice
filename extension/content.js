// Контент-скрипт для claude.ai: ждёт, пока Claude допишет ответ,
// и отправляет новый текст на озвучку.

const SETTLE_MS = 1500; // сколько тишины в DOM считаем «ответ дописан»

// Селекторы ответов Claude. Вёрстка claude.ai меняется — список можно
// дополнить своим селектором в настройках расширения.
const DEFAULT_SELECTORS = [
  ".font-claude-response",
  '[data-testid="assistant-message"]',
  ".font-claude-message",
];

const spoken = new WeakMap(); // элемент -> уже озвученный текст
let settings = { autoRead: true, skipCode: true, customSelector: "" };
let timer = null;

chrome.storage.sync.get(settings, (s) => {
  settings = { ...settings, ...s };
  markExistingAsSpoken();
});
chrome.storage.onChanged.addListener((changes) => {
  for (const [k, { newValue }] of Object.entries(changes)) settings[k] = newValue;
});

function selectors() {
  return settings.customSelector
    ? [settings.customSelector, ...DEFAULT_SELECTORS]
    : DEFAULT_SELECTORS;
}

function findMessages() {
  for (const sel of selectors()) {
    try {
      const found = document.querySelectorAll(sel);
      if (found.length) return [...found];
    } catch {
      // кривой пользовательский селектор — пропускаем
    }
  }
  return [];
}

function extractText(el) {
  const clone = el.cloneNode(true);
  if (settings.skipCode) {
    clone.querySelectorAll("pre").forEach((n) => n.replaceWith(" (блок кода) "));
  }
  clone.querySelectorAll("button, svg, [aria-hidden='true']").forEach((n) => n.remove());
  return (clone.innerText ?? clone.textContent ?? "")
    .replace(/[*_#>`|]+/g, " ") // остатки markdown
    .replace(/https?:\/\/\S+/g, " ссылка ")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function isStreaming() {
  return !!document.querySelector('[data-is-streaming="true"]');
}

// Историю, которая уже есть на странице, не читаем.
function markExistingAsSpoken() {
  for (const el of findMessages()) spoken.set(el, extractText(el));
}

function checkForNewText() {
  if (!settings.autoRead) return;
  if (isStreaming()) return schedule(); // ещё пишет — подождём
  for (const el of findMessages()) {
    const text = extractText(el);
    const before = spoken.get(el) ?? "";
    if (!text || text === before) continue;
    // если элемент дописался — читаем только добавку
    const fresh = text.startsWith(before) ? text.slice(before.length) : text;
    spoken.set(el, text);
    if (fresh.trim()) {
      chrome.runtime.sendMessage({ type: "speak", text: fresh, interrupt: false });
    }
  }
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(checkForNewText, SETTLE_MS);
}

new MutationObserver(schedule).observe(document.body, {
  childList: true,
  subtree: true,
  characterData: true,
});

// При переходе в другой чат не зачитываем его историю.
let lastUrl = location.href;
setInterval(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    setTimeout(markExistingAsSpoken, 2000);
  }
}, 500);

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "get-selection") sendResponse({ text: window.getSelection().toString() });
  if (msg.type === "read-last") {
    const last = findMessages().pop();
    if (last) chrome.runtime.sendMessage({ type: "speak", text: extractText(last) });
  }
});
