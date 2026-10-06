#!/usr/bin/env python3
"""Titolo automatico del tab iTerm2 di una sessione Claude Code.

- Stop          → in background, Haiku su Vertex legge gli ultimi scambi del transcript,
                  propone un titolo e lo scrive nella variabile `user.titolo` del tab
                  (trovato con ITERM_SESSION_ID). Il title provider di iTerm2
                  (~/.local/share/cc-titolo/provider.py) lo mostra subito.
- SessionStart  → azzera `user.titolo` del tab, o rimette l'ultimo titolo se la
                  sessione è ripresa (--resume).

Un /rename fatto a mano vince: se l'ultimo custom-title del transcript non è uno di
quelli messi da versioni precedenti di questo script, il titolo non viene toccato.

Stato in ~/.claude/cc-titoli/<session_id>.json. Non blocca mai Claude Code:
ogni errore finisce in ~/.claude/cc-titoli/errori.log e l'hook esce pulito.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

STATE_DIR = os.path.expanduser("~/.claude/cc-titoli")
MODEL = "claude-haiku-4-5"
GCLOUD_PATHS = ["/opt/homebrew/share/google-cloud-sdk/bin/gcloud", "/opt/homebrew/bin/gcloud",
                "/usr/local/bin/gcloud", os.path.expanduser("~/google-cloud-sdk/bin/gcloud")]


def log(msg):
    try:
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        with open(os.path.join(STATE_DIR, "errori.log"), "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def state_path(session_id):
    return os.path.join(STATE_DIR, f"{session_id}.json")


def load_state(session_id):
    try:
        with open(state_path(session_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pending": "", "applied": "", "ours": []}


def save_state(session_id, state):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = state_path(session_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, state_path(session_id))


def read_transcript(path):
    entries = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return entries


def renamed_by_hand(entries, ours):
    """True se l'ultimo custom-title non l'ha messo questo script (/rename manuale)."""
    titles = [e.get("customTitle", "") for e in entries if e.get("type") == "custom-title"]
    return bool(titles) and titles[-1] not in ours


def current_title(entries):
    for e in reversed(entries):
        if e.get("type") == "custom-title":
            return e.get("customTitle", "")
        if e.get("type") == "ai-title":
            return e.get("aiTitle", "")
    return ""


def text_of(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def recent_exchange(entries, user_turns=6, assistant_turns=2):
    users, assistants = [], []
    for e in entries:
        msg = e.get("message") or {}
        if e.get("type") == "user" and not e.get("isMeta"):
            t = text_of(msg).strip()
            # niente tool_result, comandi slash e promemoria di sistema
            if t and not t.startswith("<"):
                users.append(t[:600])
        elif e.get("type") == "assistant":
            t = text_of(msg).strip()
            if t:
                assistants.append(t[:800])
    return users[-user_turns:], assistants[-assistant_turns:]


def access_token():
    for g in GCLOUD_PATHS:
        if os.path.exists(g):
            out = subprocess.run([g, "auth", "application-default", "print-access-token"],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
            raise RuntimeError(f"gcloud: {out.stderr.strip()[:200]}")
    raise RuntimeError("gcloud non trovato")


def ask_haiku(prompt):
    project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
    if not project:
        raise RuntimeError("ANTHROPIC_VERTEX_PROJECT_ID non impostato (va nell'env di Claude Code)")
    region = os.environ.get("CLOUD_ML_REGION", "global")
    host = "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{project}/locations/{region}"
           f"/publishers/anthropic/models/{MODEL}:rawPredict")
    body = {"anthropic_version": "vertex-2023-10-16", "max_tokens": 40,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def own_tty():
    """Terminale della sessione Claude Code: il primo antenato di questo processo che ne ha uno.

    È più affidabile di ITERM_SESSION_ID, che dopo un riavvio di iTerm2 resta quello
    vecchio nell'ambiente di Claude Code mentre il tab ripristinato ha un id nuovo.
    """
    pid = os.getppid()
    for _ in range(6):
        out = subprocess.run(["/bin/ps", "-o", "tty=,ppid=", "-p", str(pid)], capture_output=True, text=True)
        fields = out.stdout.split()
        if len(fields) < 2:
            return ""
        if fields[0] not in ("??", "-"):
            return "/dev/" + fields[0]
        pid = int(fields[1])
    return ""


def set_tab_title(tty, title, iterm_session=""):
    """Scrive user.titolo nel tab iTerm2 con quel tty (riserva: l'uuid di ITERM_SESSION_ID)."""
    uuid = iterm_session.split(":")[-1]
    if not re.fullmatch(r"/dev/ttys\d+", tty or ""):
        tty = ""
    if not re.fullmatch(r"[0-9A-Fa-f-]+", uuid):
        uuid = ""
    if not tty and not uuid:
        return
    value = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application id "com.googlecode.iterm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (tty of s is "{tty}" and "{tty}" is not "") or unique id of s is "{uuid}" then
                    tell s to set variable named "user.titolo" to "{value}"
                    return
                end if
            end repeat
        end repeat
    end repeat
end tell'''
    out = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        raise RuntimeError(f"osascript: {out.stderr.strip()[:200]}")


def clean(title):
    t = title.strip().splitlines()[0] if title.strip() else ""
    t = t.strip().strip('"\'«»`*').rstrip(".").strip()
    if t.lower().startswith("titolo:"):
        t = t[7:].strip()
    return t[:60]


def generate(transcript_path, session_id, tty, iterm_session):
    """Processo in background lanciato dallo Stop: calcola il titolo e lo mette nel tab."""
    entries = read_transcript(transcript_path)
    state = load_state(session_id)
    if renamed_by_hand(entries, state["ours"]):
        set_tab_title(tty, "", iterm_session)
        return
    users, assistants = recent_exchange(entries)
    if not users:
        return
    now = state.get("applied") or current_title(entries)
    earlier, latest = users[:-1], users[-1]
    prompt = (
        "Scrivi il titolo del tab del terminale per una sessione di lavoro con un assistente "
        "di programmazione: da 3 a 6 parole, in italiano, niente virgolette né punto finale, "
        "solo il titolo.\n"
        "Il titolo deve dire su che cosa si sta lavorando ADESSO, cioè l'argomento dell'ULTIMA "
        "richiesta. Le richieste precedenti servono solo a capire il contesto. "
        "Tieni il titolo attuale solo se l'ultima richiesta è sullo stesso argomento; "
        "se l'argomento è cambiato, il titolo deve cambiare.\n\n"
        f"Titolo attuale: {now or '(nessuno)'}\n\n"
        + ("Richieste precedenti (contesto):\n- " + "\n- ".join(earlier) + "\n\n" if earlier else "")
        + f"ULTIMA richiesta:\n{latest}\n\n"
        + "Ultime risposte dell'assistente:\n- " + "\n- ".join(assistants)
    )
    title = clean(ask_haiku(prompt))
    if title:
        set_tab_title(tty, title, iterm_session)
        state = load_state(session_id)
        state["applied"] = title
        save_state(session_id, state)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == "--genera":
        try:
            generate(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        except Exception as e:  # noqa: BLE001 — in background, mai rumore
            log(f"genera {sys.argv[3][:8]}: {e}")
        return
    if len(sys.argv) == 5 and sys.argv[1] == "--imposta":
        try:
            set_tab_title(sys.argv[2], sys.argv[4], sys.argv[3])
        except Exception as e:  # noqa: BLE001
            log(f"imposta: {e}")
        return

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    event = payload.get("hook_event_name", "")
    session_id = payload.get("session_id", "")
    transcript = payload.get("transcript_path", "")
    iterm_session = os.environ.get("ITERM_SESSION_ID", "")
    if not session_id or not iterm_session:
        return  # non è un tab iTerm2
    tty = own_tty()  # calcolato qui: il processo in background non ha più Claude Code come antenato

    def background(*args):
        subprocess.Popen([sys.executable, os.path.abspath(__file__), *args],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    if event == "Stop" and transcript and not payload.get("stop_hook_active"):
        background("--genera", transcript, session_id, tty, iterm_session)
    elif event == "SessionStart":
        # sessione nuova: niente titolo; ripresa: l'ultimo titolo che aveva
        state = load_state(session_id)
        manual = renamed_by_hand(read_transcript(transcript), state["ours"])
        background("--imposta", tty, iterm_session, "" if manual else state.get("applied", ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — un hook non deve mai rompere Claude Code
        log(f"hook: {e}")
