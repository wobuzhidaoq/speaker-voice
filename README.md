# 🔊 Speaker Voice

Озвучивает работу Claude приятным женским голосом: промежуточные статусы
(«Сначала смотрю Roadmap…»), итоговые отчёты и уведомления. Ещё умеет читать
вслух любой выделенный текст в браузере.

- Бесплатно, без регистрации и API-ключей.
- Голос — нейронная **Светлана** от Microsoft (тот же, что в браузере Edge).
  Без интернета автоматически включается голос системы.
- Статусы звучат сразу, как только Claude их написал, фразы не накладываются друг на друга.

## Что выбрать

| Где вы работаете с Claude | Что ставить |
|---|---|
| **Claude Code** на своём компьютере: терминал, десктоп-приложение Claude, VS Code, JetBrains | [Хук для Claude Code](#-хук-для-claude-code) |
| **claude.ai** в браузере или нужно читать любой текст на сайтах | [Расширение для браузера](#-расширение-для-браузера) |

> Хуки работают только для Claude Code, запущенного **на вашем компьютере**.
> Облачные сессии (claude.ai/code в браузере) их не видят — для них ставьте расширение.

---

## 🎧 Хук для Claude Code

### Windows — одна команда

1. Откройте **PowerShell**: Пуск → наберите `PowerShell` → Enter.
2. Вставьте и нажмите Enter:
   ```powershell
   irm https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main/install.ps1 | iex
   ```
3. В конце прозвучит «Привет! Я буду читать статусы и отчёты Claude».
4. **Перезапустите Claude Code** — готово.

Установщик сам:
- поставит Python, если его нет (через `winget`);
- установит голосовой пакет `edge-tts`;
- скачает `speak.py` в `C:\Users\ВАШЕ_ИМЯ\.claude\speaker-voice\`;
- добавит хуки в `C:\Users\ВАШЕ_ИМЯ\.claude\settings.json`, не трогая ваши настройки
  (резервная копия — `settings.json.bak`).

### macOS и Linux — одна команда

```bash
curl -fsSL https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main/install.sh | sh
```
Нужен Python 3 (на macOS: `brew install python` или https://www.python.org/downloads/).
На Linux для воспроизведения ещё нужен плеер: `sudo apt install mpv`.
После установки перезапустите Claude Code.

### Как это работает

Claude Code сам запускает `speak.py` на событиях (хуки):

| Событие | Что происходит |
|---|---|
| `UserPromptSubmit` | вы отправили сообщение — запускается фоновый «слушатель», который читает каждый новый текст Claude сразу, как только тот дописан |
| `PreToolUse` | запасной путь: перед каждым действием Claude дочитывает статусы, если слушатель их пропустил |
| `Stop` | Claude закончил — дочитывает итоговый отчёт |
| `Notification` | уведомления, например «Claude ждёт вашего разрешения» |

Блоки кода и ссылки не зачитываются: вместо них звучит «(блок кода)» и «ссылка».
Новое сообщение от вас отменяет недочитанные старые фразы.

### Настройки

Добавьте раздел `"env"` в `~/.claude/settings.json` (на Windows `C:\Users\ВАШЕ_ИМЯ\.claude\settings.json`),
рядом с `"hooks"`, внутри общих фигурных скобок:
```json
"env": { "SPEAKER_EDGE_VOICE": "ru-RU-DariyaNeural", "SPEAKER_EDGE_RATE": "+15%" },
```

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `SPEAKER_EDGE_VOICE` | `ru-RU-SvetlanaNeural` | голос: `ru-RU-DariyaNeural` (женский), `ru-RU-DmitryNeural` (мужской), `en-US-AvaNeural`… |
| `SPEAKER_EDGE_RATE` | `+0%` | скорость: `+20%`, `-10%` |
| `SPEAKER_STATUSES` | `1` | `0` — читать только итог, без промежуточных статусов |
| `SPEAKER_ENGINE` | `edge` | `system` — всегда голос системы (работает без интернета) |
| `SPEAKER_MAX_CHARS` | `1500` | длиннее — обрезается |
| `SPEAKER_RATE`, `SPEAKER_VOICE` | — | скорость и голос для системного синтезатора |

После изменения настроек перезапустите Claude Code.

### Ручная установка (если установщик не подошёл)

1. Установите Python 3 и пакет голоса: `py -m pip install edge-tts` (macOS/Linux: `python3 -m pip install edge-tts`).
2. Скачайте [`claude-code-hook/speak.py`](claude-code-hook/speak.py) в `~/.claude/speaker-voice/`.
3. Проверьте: `py ~/.claude/speaker-voice/speak.py "Проверка голоса"`.
4. Добавьте блок `hooks` из [`claude-code-hook/settings.example.json`](claude-code-hook/settings.example.json)
   в `~/.claude/settings.json` — **внутрь** существующих фигурных скобок, а не отдельным блоком после них.
   На Windows замените `python3 ~/.claude/...` на `py C:/Users/ВАШЕ_ИМЯ/.claude/speaker-voice/speak.py`.
5. Перезапустите Claude Code.

### Если не работает

| Проблема | Решение |
|---|---|
| `python` выводит просто слово `Python` | это заглушка Microsoft Store: используйте `py` вместо `python` |
| Тишина при `py speak.py "текст"` | проверьте громкость и устройство вывода; запустите ещё раз — скрипт напишет причину |
| Говорит голос Windows, а не Светлана | нет интернета или не установлен `edge-tts`: `py -m pip install edge-tts` |
| Claude Code молчит, а ручная проверка работает | в `settings.json` ошибка JSON (часто — два блока `{ }` подряд). Проверка: `Get-Content $HOME\.claude\settings.json -Raw \| ConvertFrom-Json`. Ещё наберите в Claude Code `/hooks` — там должны быть `Stop` и `PreToolUse` |
| Часть статусов пропускается или звучит с задержкой | посмотрите журнал: Windows — `Get-Content $env:TEMP\speaker-voice\speaker.log -Tail 50`, macOS/Linux — `tail -50 "${TMPDIR:-/tmp}/speaker-voice/speaker.log"` |
| Молчит в облачной сессии claude.ai/code | облачные сессии не видят локальные хуки — используйте расширение |

### Удаление

Удалите папку `~/.claude/speaker-voice` и записи с `speak.py` из раздела `hooks` в `~/.claude/settings.json`.

---

## 🌐 Расширение для браузера

Для Chrome, Edge, Яндекс.Браузера, Brave, Opera.

**Что умеет**
- Само читает новые ответы Claude на claude.ai, когда тот закончил писать (историю чата не перечитывает).
- Читает выделенный текст на любом сайте: правый клик → «🔊 Прочитать вслух» или **Alt+Shift+S**.
- **Alt+Shift+X** — остановить.
- В меню расширения: голос, скорость, тон, громкость, пропуск блоков кода, кнопка «Последний ответ».

**Установка**
1. Скачайте архив: https://github.com/wobuzhidaoq/speaker-voice/archive/refs/heads/main.zip и распакуйте.
2. Откройте страницу расширений: `chrome://extensions` (Edge — `edge://extensions`, Яндекс — `browser://extensions`).
3. Включите **Режим разработчика** (переключатель справа вверху).
4. Нажмите **Загрузить распакованное** и выберите папку **`extension`** внутри распакованного архива.
5. Закрепите иконку 🔊 через значок пазла 🧩 на панели.
6. Обновите вкладку claude.ai (F5).

Голос выбирается сам — лучший доступный женский. Самые красивые — в **Edge**
(«Microsoft Svetlana Online (Natural)»), в Chrome — «Google русский».

> Если claude.ai поменял вёрстку и автоозвучка перестала срабатывать, впишите в настройках
> расширения свой CSS-селектор блока ответа (найти его можно через правый клик → «Просмотреть код»).

---

## Структура репозитория

```
install.ps1                             установщик для Windows
install.sh                              установщик для macOS / Linux
claude-code-hook/speak.py               хук для Claude Code (очередь, слушатель, синтез речи)
claude-code-hook/settings.example.json  пример настроек хуков
extension/                              расширение для браузера (Manifest V3)
```
