# Automatic iTerm2 tab titles for Claude Code

Not part of the app: two small scripts that keep each iTerm2 tab running Claude Code
titled after what you are working on *right now*, so the tab bar (and Coucou's pills,
which read the tab titles) tell sessions apart at a glance.

- **`cc-titolo.py`** — a Claude Code hook. On `Stop` it asks Claude Haiku on Vertex AI
  for a 3–6 word title from the last exchanges of the transcript, in the background, and
  writes it to the tab's `user.titolo` variable via AppleScript. On `SessionStart` it
  clears it, or restores the last title of a resumed session. A manual `/rename` wins.
- **`provider.py`** — an iTerm2 *title provider* (Python API). It shows
  `<Claude's status glyph> <user.titolo>`, or Claude Code's own title when there is none.

Titles are generated in Italian; change the prompt in `generate()` for another language.

## Why not `sessionTitle` or `set name`

- A `UserPromptSubmit` hook can return `hookSpecificOutput.sessionTitle`, but Claude Code
  regenerates its own title right after and wins, and the hook can only act when a prompt
  is sent, one turn late.
- Setting the session name from outside is overwritten at once by the title Claude Code
  and the shell keep writing.

A title provider decides the title inside iTerm2, so nothing overwrites it.

## Setup

1. Claude Code on Vertex AI: `ANTHROPIC_VERTEX_PROJECT_ID` (and optionally `CLOUD_ML_REGION`,
   default `global`) in Claude Code's env, `gcloud auth application-default login`, and
   `claude-haiku-4-5` enabled in the project.
2. Hook: copy `cc-titolo.py` to `~/.claude/hooks/` and add it to `~/.claude/settings.json`
   on `Stop` and `SessionStart`:
   ```json
   {"hooks": [{"type": "command", "command": "/usr/bin/python3 ~/.claude/hooks/cc-titolo.py", "timeout": 5}]}
   ```
3. Provider: iTerm2 → Settings → General → Magic → *Enable Python API*; then
   ```bash
   mkdir -p ~/.local/share/cc-titolo && cp provider.py ~/.local/share/cc-titolo/
   python3 -m venv ~/.local/share/cc-titolo/venv
   ~/.local/share/cc-titolo/venv/bin/pip install iterm2
   sed "s#HOME#$HOME#g" io.github.i87ce.cc-titolo.plist > ~/Library/LaunchAgents/io.github.i87ce.cc-titolo.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.i87ce.cc-titolo.plist
   ```
4. In iTerm2 → Settings → Profiles → *your profile* → General → Title, pick
   **Claude Code — titolo automatico**.

## Pitfalls (iTerm2 3.7.3)

- **Do not write profile settings through the Python API** (`async_set_title_function`,
  `async_set_title_components`, …): iTerm2 3.7.3 crashes, and keeps crashing on every new
  tab while the value is there. Pick the provider by hand in Settings (step 4).
- After an iTerm2 restart the restored tabs get **new** session ids, while running
  programs keep the old `ITERM_SESSION_ID` in their environment. The hook finds its tab by
  **tty** instead, which survives the restart.
- Hooks run without a controlling terminal (`/dev/tty` fails): the tty is found by
  walking up the parent processes.
