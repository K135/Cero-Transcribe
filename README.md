# Cero-Transcribe

### Your Mac. Your voice. Full keyboard — hands optional. (open source)

**Cero-Transcribe** turns speech into live typing in any app — Chrome, Notes, Slack, Mail, Cursor — fully offline. No cloud. No laggy web demo. Just you talking, and text landing where your cursor already is.

Powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp). Menu-bar only. Tap to talk. Say *Hey Cero* when you want hands-free.

---

## Download

**👉 [Download Cero-Transcribe-Install.dmg](https://github.com/K135/Cero-Transcribe/releases/latest)**

Fully self-contained macOS app. No Homebrew, Python, or other installs.

1. Open the DMG → drag **Cero-Transcribe** into **Applications**.
2. Launch it (Right-click → **Open** the first time).
3. Grant **Microphone**, **Accessibility**, and **Input Monitoring** when prompted.
4. Click into a text field → click **🎙️** (or press **Right Option**) → speak.

**Install → permissions → use.** Everything runs offline after that.

<details>
<summary>Developer install (from source)</summary>

```bash
brew install portaudio whisper-cpp
git clone https://github.com/K135/Cero-Transcribe.git
cd Cero-Transcribe
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/download_model.sh
python run.py
```

</details>

---

## Why Cero-Transcribe

| | |
|---|---|
| **Fully offline** | Audio never uploads. Models run on your Mac. |
| **Live typing** | Phrases paste into the focused app as you pause. |
| **Warm Whisper** | Keeps `whisper-server` loaded so the last sentence doesn’t stall on a cold model load. |
| **Voice edits** | Say *delete*, *delete the last sentence*, *comma*, *period*… |
| **Polished output** | Stutter collapse, ratio fixes (`3 is to 2` → `3:2`), spacing, spoken punctuation. |
| **Immersive glow** | Right-edge glow only while you’re actively dictating. |

---

## Permissions (required)

Cero-Transcribe needs three macOS privacy permissions. On first launch it **prompts** and **opens System Settings** for anything missing. You can also use the menu:

**🎙️ → Grant Permissions…**

| Permission | Why | Where |
|---|---|---|
| **Microphone** | Capture your voice | System Settings → Privacy & Security → Microphone |
| **Accessibility** | Paste / type into other apps | System Settings → Privacy & Security → Accessibility |
| **Input Monitoring** | Global hotkeys (Right Option, etc.) | System Settings → Privacy & Security → Input Monitoring |

Enable the toggle for **Cero-Transcribe** (or **Python** / **Terminal** if you run `python run.py` from a terminal).

After granting Accessibility, **quit and reopen** the app (or the Terminal) so macOS applies the trust.

If dictation starts but nothing appears in Chrome/Notes, Accessibility is almost always the missing piece.

---

## How to use

1. Click into a text field.
2. Click **🎙️** (or tap **Right Option**) — icon turns 🔴, right-edge glow appears.
3. Speak. After a short pause, text is pasted.
4. Click **🎙️** again to stop — glow disappears.
5. **Right-click** the icon for models, vocabulary, wake word, login item, permissions.

| Control | Action |
|---------|--------|
| Click 🎙️ | Start / Stop |
| Right Option | Start / Stop |
| Shift+F3 | Start / Stop (alternate) |
| ⌘⇧U | Undo last dictated phrase |
| Right-click 🎙️ | Full menu |

### Voice commands

Say these as their **own phrase** (pause before/after):

| Say | Result |
|-----|--------|
| `delete` / `scratch that` / `undo` | Remove last phrase |
| `delete the last sentence` | Remove last sentence |
| `delete last word` / `word delete` | Remove last word |
| `clear everything` | Clear session dictation |
| `comma` `period` `full stop` `question mark` | Insert `,` `.` `?` |
| `new line` / `new paragraph` | Insert line breaks |

### Models

| Model | Best for |
|-------|----------|
| **Base EN (default)** | Best accuracy — clean emails, docs, code notes |
| **Tiny EN** | Maximum speed on older Macs |

Menu → pick a model. Cero-Transcribe keeps a local `whisper-server` warm so phrases land fast without reloading the model.

### Vocabulary

Menu → **Edit Vocabulary…** opens:

`~/Library/Application Support/cerotrans/vocabulary.txt`

```
# Prompt hints (one per line)
Cero-Transcribe
# Corrections (wrong=right)
cerotrans=Cero-Transcribe
myname=Karthik
```

### Wake word

Menu → **Hey Cero** — say *Hey Cero* / *Hey Sero* to start dictation hands-free.

Menu → **Clear Context (new email)** — reset capitalization/history when starting a fresh document.

---

## What’s built (architecture)

```
Cero-Transcribe/
  run.py                      # entrypoint
  requirements.txt
  LICENSE                     # MIT
  scripts/
    download_model.sh         # fetch ggml-tiny.en (+ base.en)
    build_mac_dmg.sh          # self-contained .app + DMG
    build_icons.sh
  mac/
    Info.plist                # LSUIElement + Mic / Apple Events usage strings
    launcher.sh               # bundled app launcher
  models/                     # ggml binaries (downloaded; not in git)
  cerotrans/                  # Python package (internal module name)
    app.py                    # menu bar, click toggle, permissions
    live_engine.py            # pause-based phrase commit + voice commands
    transcriber.py            # warm whisper-server + CLI fallback
    textproc.py               # junk filter, punctuation, polish
    commands.py               # voice delete / undo parsing
    output.py                 # clipboard paste + typed history
    recorder.py               # PortAudio capture
    hotkey.py                 # Right Option / undo
    wakeword.py               # Hey Cero (energy-gated)
    glow.py                   # right-edge wavy glow (live only)
    permissions.py            # Mic / Accessibility / Input Monitoring
    focus.py                  # restore frontmost app
    login_item.py             # Launch at Login
    config.py                 # paths + timing knobs
```

### Runtime flow

1. Mic buffer fills while you’re speaking.
2. After ~0.22s of silence (and ≥ ~0.45s of audio), a phrase is cut.
3. Audio is sent to a **local** `whisper-server` that already has the model loaded.
4. Transcript is polished (`textproc`) and checked for voice commands.
5. Text is pasted into the focused app via clipboard + ⌘V (Accessibility).

Logs: `~/Library/Application Support/cerotrans/app.log`

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Nothing types into apps | Enable **Accessibility** for the app/Terminal; relaunch |
| Hotkeys don’t work | Enable **Input Monitoring** |
| Mic error on start | Enable **Microphone**; check System Settings |
| Last phrase feels slow | Use **Tiny EN**; ensure `whisper-server` is installed (`brew install whisper-cpp`) |
| macOS blocks the DMG app | Right-click → **Open**; or `xattr -cr /Applications/Cerotrans.app` |
| Gatekeeper / “damaged” | Ad-hoc signed — Right-click → Open, or rebuild with your own signing identity |

---

## Contributing

PRs welcome. Keep changes focused. For latency work, prefer warm-server paths over cold `whisper-cli` per phrase.

```bash
source .venv/bin/activate
python run.py
```

---

## License

MIT — see [LICENSE](LICENSE).

Whisper models and whisper.cpp are subject to their own licenses (MIT / model cards).

---

## Author

Built by **Karthik** — [LinkedIn](https://in.linkedin.com/in/kmzak)

---

## Credits

- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — local ASR  
- [rumps](https://github.com/jaredks/rumps) — macOS menu bar  
- **Cero-Transcribe** — fully voice-type on macOS
