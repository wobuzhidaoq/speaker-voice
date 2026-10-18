#!/bin/sh
# Установка Speaker Voice для Claude Code на macOS и Linux.
# Запуск в терминале:
#   curl -fsSL https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main/install.sh | sh
set -e

REPO="https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main"
DIR="$HOME/.claude/speaker-voice"
SETTINGS="$HOME/.claude/settings.json"

command -v python3 >/dev/null || { echo "Нужен Python 3: https://www.python.org/downloads/"; exit 1; }

echo "1/3 Устанавливаю нейронный голос (edge-tts)..."
python3 -m pip install --user --upgrade --quiet edge-tts 2>/dev/null \
  || python3 -m pip install --user --upgrade --quiet --break-system-packages edge-tts

if [ "$(uname)" != "Darwin" ] && ! command -v mpv >/dev/null && ! command -v ffplay >/dev/null && ! command -v mpg123 >/dev/null; then
  echo "    Для воспроизведения нужен mpv, ffplay или mpg123, например: sudo apt install mpv"
fi

echo "2/3 Скачиваю speak.py в $DIR ..."
mkdir -p "$DIR"
curl -fsSL "$REPO/claude-code-hook/speak.py" -o "$DIR/speak.py"

echo "3/3 Подключаю хуки в $SETTINGS ..."
python3 - "$SETTINGS" "python3 $DIR/speak.py" <<'EOF'
import json, os, shutil, sys
path, command = sys.argv[1], sys.argv[2]
settings = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        settings = json.loads(raw) if raw else {}
    except ValueError:
        sys.exit(f"В {path} ошибка JSON — исправьте файл и запустите установку снова.")
    shutil.copy(path, path + ".bak")
hooks = settings.setdefault("hooks", {})
for event in ("UserPromptSubmit", "PreToolUse", "Stop", "Notification"):
    groups = [g for g in hooks.get(event, [])
              if not any("speak.py" in h.get("command", "") for h in g.get("hooks", []))]
    group = {"hooks": [{"type": "command", "command": command}]}
    if event == "PreToolUse":
        group["matcher"] = "*"
    hooks[event] = groups + [group]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)
EOF

echo ""
echo "Готово! Проверка голоса..."
python3 "$DIR/speak.py" "Привет! Я буду читать статусы и отчёты Claude."
echo "Перезапустите Claude Code — и он заговорит."
