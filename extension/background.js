// Фоновый service worker: вся озвучка идёт через chrome.tts,
// которому не нужен клик пользователя (в отличие от speechSynthesis на странице).

const DEFAULTS = {
  autoRead: true,
  skipCode: true,
  voiceName: "",
  rate: 1.0,
  pitch: 1.0,
  volume: 1.0,
};

async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
}

// Онлайн-голоса Google обрываются на длинных фразах, поэтому режем на куски.
function splitText(text, maxLen = 200) {
  const sentences = text.match(/[^.!?…\n]+[.!?…]*\s*|\n+/g) || [text];
  const chunks = [];
  let current = "";
  for (const s of sentences) {
    if ((current + s).length > maxLen && current) {
      chunks.push(current.trim());
      current = "";
    }
    if (s.length > maxLen) {
      for (const word of s.split(/\s+/)) {
        if ((current + " " + word).length > maxLen && current) {
          chunks.push(current.trim());
          current = "";
        }
        current += " " + word;
      }
    } else {
      current += s;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(Boolean);
}

// Если голос не выбран — берём лучший женский: нейронные голоса Edge,
// затем Google, затем любой подходящий по языку.
const PREFERRED_VOICES = {
  ru: ["Svetlana Online", "Dariya Online", "Google русский", "Irina"],
  en: ["Ava Online", "Jenny Online", "Aria Online", "Google US English", "Zira"],
};

async function pickVoice(lang) {
  const voices = await chrome.tts.getVoices();
  for (const name of PREFERRED_VOICES[lang]) {
    const v = voices.find((v) => v.voiceName?.includes(name));
    if (v) return v.voiceName;
  }
  return voices.find((v) => v.lang?.startsWith(lang))?.voiceName;
}

async function speak(text, { interrupt = true } = {}) {
  text = (text || "").trim();
  if (!text) return;
  const s = await getSettings();
  const lang = /[а-яё]/i.test(text) ? "ru" : "en";
  const voiceName = s.voiceName || (await pickVoice(lang));
  const chunks = splitText(text);
  chunks.forEach((chunk, i) => {
    const opts = {
      rate: Number(s.rate),
      pitch: Number(s.pitch),
      volume: Number(s.volume),
      enqueue: !(interrupt && i === 0),
    };
    if (voiceName) opts.voiceName = voiceName;
    else opts.lang = lang === "ru" ? "ru-RU" : "en-US";
    chrome.tts.speak(chunk, opts);
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "read-selection",
    title: "🔊 Прочитать вслух",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "stop",
    title: "⏹ Остановить озвучку",
    contexts: ["all"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "read-selection") speak(info.selectionText);
  if (info.menuItemId === "stop") chrome.tts.stop();
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command === "stop-speaking") return chrome.tts.stop();
  if (command === "read-selection" && tab?.id) {
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => window.getSelection().toString(),
      });
      speak(result);
    } catch {
      // нет доступа к вкладке — просим контент-скрипт
      chrome.tabs.sendMessage(tab.id, { type: "get-selection" }, (r) => speak(r?.text));
    }
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "speak") speak(msg.text, { interrupt: msg.interrupt !== false });
  if (msg.type === "stop") chrome.tts.stop();
  if (msg.type === "get-voices") {
    chrome.tts.getVoices((voices) => sendResponse(voices));
    return true;
  }
});
