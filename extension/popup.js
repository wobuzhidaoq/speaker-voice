const DEFAULTS = {
  autoRead: true,
  skipCode: true,
  voiceName: "",
  rate: 1.0,
  pitch: 1.0,
  volume: 1.0,
  customSelector: "",
};

const $ = (id) => document.getElementById(id);

chrome.storage.sync.get(DEFAULTS, (s) => {
  $("autoRead").checked = s.autoRead;
  $("skipCode").checked = s.skipCode;
  $("customSelector").value = s.customSelector;
  for (const k of ["rate", "pitch", "volume"]) {
    $(k).value = s[k];
    $(k + "Val").textContent = s[k];
  }

  chrome.runtime.sendMessage({ type: "get-voices" }, (voices = []) => {
    const select = $("voiceName");
    select.add(new Option("Авто (лучший женский голос)", ""));
    // русские голоса — наверх
    voices
      .sort((a, b) => (b.lang?.startsWith("ru") ? 1 : 0) - (a.lang?.startsWith("ru") ? 1 : 0))
      .forEach((v) => select.add(new Option(`${v.voiceName} (${v.lang || "?"})`, v.voiceName)));
    select.value = s.voiceName;
  });
});

const save = (key, value) => chrome.storage.sync.set({ [key]: value });

$("autoRead").onchange = (e) => save("autoRead", e.target.checked);
$("skipCode").onchange = (e) => save("skipCode", e.target.checked);
$("voiceName").onchange = (e) => save("voiceName", e.target.value);
$("customSelector").onchange = (e) => save("customSelector", e.target.value.trim());
for (const k of ["rate", "pitch", "volume"]) {
  $(k).oninput = (e) => {
    $(k + "Val").textContent = e.target.value;
    save(k, Number(e.target.value));
  };
}

$("test").onclick = () => chrome.runtime.sendMessage({ type: "speak", text: $("testText").value });
$("stop").onclick = () => chrome.runtime.sendMessage({ type: "stop" });
$("last").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "read-last" }).catch(() => {});
};
