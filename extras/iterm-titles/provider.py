#!/usr/bin/env python3
"""Title provider di iTerm2 per i tab con Claude Code.

Il titolo del tab diventa «<simbolo di stato di Claude> <user.titolo>», dove
`user.titolo` è la variabile che l'hook ~/.claude/hooks/cc-titolo.py scrive a
fine turno (riassunto di Haiku su Vertex di cosa si sta facendo adesso).

- nessun user.titolo → il titolo che scrive Claude Code (o il programma in esecuzione);
- Claude Code non in esecuzione → titolo normale di iTerm2 (autoName, di solito il nome del profilo).

Gira fuori da iTerm2 (venv suo, avviato da launchd: io.github.i87ce.cc-titolo) e si
collega all'API di iTerm2. Il provider va scelto a mano nel profilo (vedi main).
"""
import re

import iterm2

PROVIDER_ID = "io.github.i87ce.cc-titolo"
PROVIDER_NAME = "Claude Code — titolo automatico"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")  # il binario di Claude Code si chiama come la sua versione


def is_claude(job):
    return job == "claude" or bool(VERSION_RE.match(job or ""))


def compose(auto_name, terminal, job, titolo):
    auto_name, terminal, titolo = auto_name or "", terminal or "", (titolo or "").strip()
    if not is_claude(job):
        return terminal or auto_name
    if not titolo:
        return terminal or auto_name
    first = terminal[:1]
    glyph = first if first and not first.isalnum() and first not in "\"'([«" else ""
    return f"{glyph} {titolo}" if glyph else titolo


async def main(connection):
    @iterm2.TitleProviderRPC
    async def cc_titolo(auto_name=iterm2.Reference("autoName?"),
                        terminal=iterm2.Reference("terminalWindowName?"),
                        job=iterm2.Reference("jobName?"),
                        titolo=iterm2.Reference("user.titolo?")):
        return compose(auto_name, terminal, job, titolo)

    await cc_titolo.async_register(connection, display_name=PROVIDER_NAME, unique_identifier=PROVIDER_ID)

    # Niente async_set_title_function: con iTerm2 3.7.3 la libreria 2.25 scrive
    # «Title Function» in un formato che iTerm2 non sa rileggere, e iTerm2 va in crash
    # a ogni avvio (05/10/2026). Il provider si sceglie a mano: Settings → Profiles →
    # General → Title → «Claude Code — titolo automatico».


if __name__ == "__main__":
    iterm2.run_forever(main)
