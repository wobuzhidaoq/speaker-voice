#!/usr/bin/env python3
"""Хук Claude Code: озвучивает статусы и итоговые ответы Claude.

События:
  UserPromptSubmit — вы отправили сообщение: запускается фоновый процесс,
                     который следит за журналом Claude и читает каждый новый
                     текст сразу, как только Claude его дописал
  PreToolUse       — запасной путь: перед каждым действием Claude дочитывает
                     статусы, если слушатель их пропустил
  Stop             — ход закончен: дочитывает всё, что ещё не прозвучало (итог)
  Notification     — уведомления («Claude ждёт разрешения»)

Хуки только кладут фразы в очередь и сразу возвращают управление Claude.
Читает их по одной фоновый процесс (speak.py --worker): пока звучит одна
фраза, следующая уже синтезируется, поэтому паузы между ними короткие.

Голоса:
  edge   — нейронные голоса Microsoft (Светлана, Дарья…), бесплатно, нужен
           интернет и пакет edge-tts:  py -m pip install edge-tts
  system — голос системы (Windows: System.Speech, macOS: say, Linux: spd-say/espeak)
Если edge недоступен, автоматически используется system.

Переменные окружения:
  SPEAKER_ENGINE     — edge (по умолчанию) или system
  SPEAKER_EDGE_VOICE — голос edge, по умолчанию ru-RU-SvetlanaNeural
                       (ещё: ru-RU-DariyaNeural, ru-RU-DmitryNeural, en-US-AvaNeural)
  SPEAKER_EDGE_RATE  — скорость edge, например +20% или -10% (по умолчанию +0%)
  SPEAKER_STATUSES   — 1 читать промежуточные статусы (по умолчанию), 0 только итог
  SPEAKER_MAX_CHARS  — максимум символов в одном сообщении (по умолчанию 1500)
  SPEAKER_RATE       — скорость system: macOS слов/мин, Windows -10..10, Linux -100..100
  SPEAKER_VOICE      — голос system (например, Milena на macOS)

Проверка вручную:  py speak.py "Привет, я буду читать твои отчёты"
"""

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

MAX_CHARS = int(os.environ.get("SPEAKER_MAX_CHARS", "1500"))
STATUSES = os.environ.get("SPEAKER_STATUSES", "1") != "0"
STATE_DIR = os.path.join(tempfile.gettempdir(), "speaker-voice")
QUEUE = os.path.join(STATE_DIR, "queue.jsonl")
LOCK = os.path.join(STATE_DIR, "queue.lock")
HEARTBEAT = os.path.join(STATE_DIR, "worker.alive")
WATCH = os.path.join(STATE_DIR, "watch.json")
LOG = os.path.join(STATE_DIR, "speaker.log")
SYNTH_TIMEOUT = 15  # секунд на синтез одной фразы, дольше — читаем системным голосом
IDLE_EXIT = 180  # секунд без новых фраз и без изменений журнала — воркер выходит
WIN = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WIN else 0


# ---------- журнал и файлы ----------

def log(msg):
    """Журнал для диагностики: %TEMP%\\speaker-voice\\speaker.log"""
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 300_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def retry(fn, *args, **kwargs):
    """Антивирус на Windows ненадолго блокирует свежие файлы — пробуем ещё раз."""
    for _ in range(40):
        try:
            return fn(*args, **kwargs)
        except PermissionError:
            time.sleep(0.05)
    return fn(*args, **kwargs)


def write_file(path, text, mode="w"):
    def _write():
        with open(path, mode, encoding="utf-8") as f:
            f.write(text)
    retry(_write)


# ---------- текст из транскрипта ----------

def is_user_prompt(entry):
    """Сообщение, которое написал человек (а не результат инструмента)."""
    if entry.get("type") != "user":
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return False


def current_turn_texts(transcript_path):
    """Тексты Claude после последнего сообщения человека: [(ключ, текст), …]."""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    result = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # строка ещё дописывается
        if is_user_prompt(entry):
            break
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text").strip()
        if text:
            key = entry.get("uuid") or hashlib.md5(text.encode()).hexdigest()
            result.append((key, text))
    return list(reversed(result))


def take_unspoken(session_id, texts):
    """Отбирает ещё не озвученные тексты и запоминает их как озвученные."""
    safe_id = re.sub(r"[^\w-]", "", session_id or "default")
    path = os.path.join(STATE_DIR, f"spoken-{safe_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            spoken = json.load(f)
    except (OSError, ValueError):
        spoken = []
    fresh = [(k, t) for k, t in texts if k not in spoken]
    if fresh:
        spoken = (spoken + [k for k, _ in fresh])[-300:]
        write_file(path, json.dumps(spoken))
    return [t for _, t in fresh]


def clean(text):
    text = re.sub(r"```.*?```", " (блок кода) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [текст](ссылка)
    text = re.sub(r"https?://\S+", " ссылка ", text)
    text = re.sub(r"[*_#>|~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "… и так далее."
    return text


def split_phrases(text, min_len=60, max_len=300):
    """Режем на предложения: первое прозвучит быстрее, пока синтезируется остальное."""
    phrases, current = [], ""
    for sentence in re.findall(r"[^.!?…]+[.!?…]*", text):
        if current and len(current) + len(sentence) > max_len:
            phrases.append(current.strip())
            current = ""
        current += sentence
        if len(current) >= min_len:
            phrases.append(current.strip())
            current = ""
    if current.strip():
        phrases.append(current.strip())
    return [p for p in phrases if p]


# ---------- очередь ----------

class QueueLock:
    def __enter__(self):
        deadline = time.time() + 5
        while True:
            try:
                os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL))
                return self
            except FileExistsError:
                try:  # замок, брошенный упавшим процессом
                    if time.time() - os.path.getmtime(LOCK) > 10:
                        os.remove(LOCK)
                except OSError:
                    pass
                if time.time() > deadline:
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.remove(LOCK)
        except OSError:
            pass


def touch(path):
    with open(path, "a"):
        os.utime(path, None)


def remove(*paths):
    for p in paths:
        try:
            retry(os.remove, p)
        except OSError:
            pass


def append_queue(texts):
    """Вызывать под QueueLock."""
    phrases = [p for t in texts for p in split_phrases(clean(t))]
    if phrases:
        write_file(QUEUE, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in phrases), "a")
        log(f"в очередь +{len(phrases)}: {phrases[0][:60]}")


def queue_transcript(transcript_path, session_id, only_last=False):
    """Ставит в очередь новые тексты текущего хода. Вызывать под QueueLock."""
    texts = current_turn_texts(transcript_path)
    if only_last:
        texts = texts[-1:]
    fresh = take_unspoken(session_id, texts)
    try:
        append_queue(fresh)
    except OSError:
        # не смогли поставить в очередь — не считаем озвученным, подхватим в следующий раз
        forget_spoken(session_id, len(fresh))
        raise
    return bool(texts)


def forget_spoken(session_id, count):
    if not count:
        return
    safe_id = re.sub(r"[^\w-]", "", session_id or "default")
    path = os.path.join(STATE_DIR, f"spoken-{safe_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            spoken = json.load(f)
        write_file(path, json.dumps(spoken[:-count]))
    except (OSError, ValueError):
        pass


def ensure_worker():
    with QueueLock():
        try:
            if time.time() - os.path.getmtime(HEARTBEAT) < 10:
                return
        except OSError:
            pass
        touch(HEARTBEAT)  # сразу, чтобы второй хук не запустил ещё одного
    log("запускаю фоновый процесс")
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--worker"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if WIN else 0,
        start_new_session=not WIN,
    )


def read_queue():
    try:
        with open(QUEUE, encoding="utf-8") as f:
            return [l for l in f if l.strip()]
    except OSError:
        return []


# ---------- фоновый процесс ----------

def worker():
    def heartbeat():
        while True:
            try:
                touch(HEARTBEAT)
            except OSError:
                pass
            time.sleep(2)

    threading.Thread(target=heartbeat, daemon=True).start()
    engine = Engine()
    ready = queue.Queue()  # синтезированные фразы, ждущие воспроизведения
    threading.Thread(target=player, args=(engine, ready), daemon=True).start()

    log("фоновый процесс запущен, голос: " + ("edge" if engine.edge else "system"))
    state = {"last_activity": time.time(), "last_mtime": None}
    while True:
        try:
            text = worker_step(engine, ready, state)
        except Exception:
            log("ошибка в фоновом процессе:\n" + traceback.format_exc())
            time.sleep(0.5)
            continue
        if text is StopIteration:
            log("фоновый процесс завершён (тишина)")
            return
        if text is None:
            time.sleep(0.2)
            continue
        state["last_activity"] = time.time()
        ready.put(engine.synth(text))  # синтез идёт, пока player читает предыдущую
        while ready.qsize() > 1:  # не убегать далеко вперёд
            time.sleep(0.1)


def worker_step(engine, ready, state):
    """Одна итерация: проверить журнал Claude и взять фразу из очереди.
    -> текст, None (пусто) или StopIteration (пора завершаться)."""
    with QueueLock():
        # слушатель: читаем журнал Claude, как только он изменился
        watch = None
        if STATUSES:
            try:
                with open(WATCH, encoding="utf-8") as f:
                    watch = json.load(f)
            except (OSError, ValueError):
                pass
        if watch:
            try:
                mtime = os.path.getmtime(watch["transcript_path"])
            except OSError:
                mtime = None
            if mtime != state["last_mtime"]:
                state["last_activity"] = time.time()
                queue_transcript(watch["transcript_path"], watch.get("session_id"))
                state["last_mtime"] = mtime  # после успеха — иначе повторим

        lines = read_queue()
        if lines:
            write_file(QUEUE, "".join(lines[1:]))
            return json.loads(lines[0])
        idle = time.time() - state["last_activity"] > IDLE_EXIT
        if idle and ready.unfinished_tasks == 0:
            remove(QUEUE, HEARTBEAT)
            return StopIteration
        return None


def player(engine, ready):
    while True:
        item = ready.get()
        try:
            engine.play(item)
        except Exception:
            log("ошибка воспроизведения:\n" + traceback.format_exc())
        finally:
            ready.task_done()


# ---------- синтез и воспроизведение ----------

class Engine:
    def __init__(self, no_window=True):
        self.no_window = no_window
        self.edge = None
        if os.environ.get("SPEAKER_ENGINE", "edge") == "edge":
            try:
                import edge_tts
                self.edge = edge_tts
            except ImportError as e:
                self.warn(f"пакет edge-tts не установлен ({e})")

    def warn(self, msg):
        log(msg)
        if not self.no_window:
            print(f"speaker-voice: {msg}, читаю системным голосом", file=sys.stderr)

    def synth(self, text):
        """-> ("mp3", путь, текст) или ("text", None, текст) для системного голоса."""
        if self.edge:
            import asyncio

            has_ru = re.search(r"[а-яё]", text, re.I)
            voice = os.environ.get("SPEAKER_EDGE_VOICE") or ("ru-RU-SvetlanaNeural" if has_ru else "en-US-AvaNeural")
            rate = os.environ.get("SPEAKER_EDGE_RATE", "+0%")
            fd, path = tempfile.mkstemp(suffix=".mp3", dir=STATE_DIR)
            os.close(fd)
            started = time.time()
            try:
                communicate = self.edge.Communicate(text, voice, rate=rate)
                asyncio.run(asyncio.wait_for(communicate.save(path), SYNTH_TIMEOUT))
                log(f"синтез {time.time() - started:.1f} с: {text[:60]}")
                return ("mp3", path, text)
            except Exception as e:
                remove(path)
                self.warn(f"голос edge недоступен ({type(e).__name__}: {e})")
        return ("text", None, text)

    def play(self, item):
        kind, path, text = item
        if kind == "mp3":
            try:
                play_mp3(path)
                return
            except Exception as e:
                # фразу не теряем: читаем системным голосом
                self.warn(f"не удалось проиграть mp3 ({type(e).__name__}: {e})")
            finally:
                remove(path)
        say_system(text, self.no_window)

    def say(self, text):
        self.play(self.synth(text))


def play_mp3(path):
    if WIN:
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW

        def cmd(c):
            err = mci(c, None, 0, None)
            if err:
                raise OSError(f"MCI {err}: {c}")

        alias = f"sv{os.getpid()}_{int(time.time() * 1000)}"
        cmd(f'open "{path}" type mpegvideo alias {alias}')
        try:
            cmd(f"play {alias} wait")
        finally:
            mci(f"close {alias}", None, 0, None)
    elif sys.platform == "darwin":
        subprocess.run(["afplay", path], check=True)
    else:
        for player in (["mpv", "--no-video", "--really-quiet"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"]):
            if shutil.which(player[0]):
                subprocess.run(player + [path], check=True)
                return
        raise OSError("нет плеера mp3 (mpv, ffplay или mpg123)")


def say_system(text, no_window=False):
    rate = os.environ.get("SPEAKER_RATE")
    voice = os.environ.get("SPEAKER_VOICE")

    if sys.platform == "darwin":
        cmd = ["say"] + (["-v", voice] if voice else []) + (["-r", rate] if rate else [])
        subprocess.run(cmd + [text])

    elif WIN:
        # текст через временный файл — так не ломаются кавычки и кириллица
        fd, path = tempfile.mkstemp(suffix=".txt", dir=STATE_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            + (f"$s.SelectVoice('{voice}');" if voice else "")
            + f"$s.Rate = {rate or 1};"
            f"$s.Speak([IO.File]::ReadAllText('{path}', [Text.Encoding]::UTF8));"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                creationflags=NO_WINDOW if no_window else 0,
            )
        finally:
            remove(path)

    else:
        lang = "ru" if re.search(r"[а-яё]", text, re.I) else "en"
        if shutil.which("spd-say"):
            cmd = ["spd-say", "-w", "-l", lang] + (["-r", rate] if rate else []) + ["--", text]
        elif shutil.which("espeak-ng") or shutil.which("espeak"):
            cmd = [shutil.which("espeak-ng") or shutil.which("espeak"), "-v", voice or lang, text]
        else:
            print("speaker-voice: не найден spd-say / espeak-ng", file=sys.stderr)
            return
        subprocess.run(cmd)


# ---------- точка входа ----------

def main():
    os.makedirs(STATE_DIR, exist_ok=True)

    if sys.argv[1:] == ["--worker"]:
        return worker()

    # ручная проверка: py speak.py "текст" — говорим сразу, ошибки видны
    if len(sys.argv) > 1:
        return Engine(no_window=False).say(clean(" ".join(sys.argv[1:])))

    # без данных в stdin (запуск из консоли) json.load повис бы навсегда
    if sys.stdin is None or sys.stdin.isatty():
        print('Использование: speak.py "текст" или запуск хуком Claude Code', file=sys.stderr)
        return

    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except ValueError:
        data = {}

    event = data.get("hook_event_name", "")
    transcript = data.get("transcript_path", "")
    session = data.get("session_id")

    log(f"хук {event}")
    with QueueLock():
        if event == "UserPromptSubmit":
            remove(QUEUE)  # новое сообщение — недочитанное старое уже не нужно
            write_file(WATCH, json.dumps({"transcript_path": transcript, "session_id": session}))
        elif event == "Notification":
            append_queue([data.get("message", "")])
        elif event == "PreToolUse" and STATUSES:
            queue_transcript(transcript, session)
        elif event == "Stop":
            if not queue_transcript(transcript, session, only_last=not STATUSES):
                append_queue([data.get("last_assistant_message", "")])
        else:
            return
    ensure_worker()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("ошибка:\n" + traceback.format_exc())
        raise
