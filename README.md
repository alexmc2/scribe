# Scribe

Live meeting transcription that runs on your own computer. It uses OpenAI's
Whisper speech model on your NVIDIA graphics card, so nothing is uploaded and
no account or API key is needed.

Start it, and text appears as people speak. Each meeting is saved as one text
file that keeps itself up to date.

## Install

Scribe runs on Linux (tested on Ubuntu; Linux Mint works the same way). It
needs:

- an NVIDIA graphics card with its driver installed (Linux Mint: **Driver
  Manager**). Without one, Scribe still works on the CPU, but slowly.
- Python 3.10 or newer, and PipeWire or PulseAudio. Both come with Mint and
  Ubuntu.
- Node.js 18 or newer, used once by the installer to build the interface.

In a terminal, in this folder:

```bash
./install.sh
```

The installer checks your computer first and tells you exactly what to
install if anything's missing (usually `sudo apt install python3-venv
pulseaudio-utils nodejs npm`). It then sets up Scribe's Python packages (about 2.5 GB),
adds the `scribe` command, and downloads the speech model (about 1.6 GB). No
system-wide changes are made; everything stays in this folder and your home
folder.

## Use

```bash
scribe
```

Scribe loads the model (a few seconds), starts recording, and opens its
window: its own window if Chrome or Chromium is installed, otherwise a browser
tab at <http://127.0.0.1:8787>. The window is only reachable from your own
computer. Running `scribe` again while it's open just brings the window back.

**Check it can hear you:** next to "Recording" at the top there's a chip for
each input with small level bars. They should move when you talk.

### Recording a call

Open **Details** (the panel button, top right) and set:

- **Microphone**: your voice. "System default" uses your system's input,
  falling back to the built-in microphone if that isn't a microphone.
- **Computer audio**: what your computer plays, i.e. the other people on a
  Zoom, Teams or Meet call. Set it to "System default" for calls; leave it
  "Off" for meetings in a room.

With both on, paragraphs are labelled **You** or **Others**. Choices are
remembered.

### In the window

- **Pause / Resume** keeps the same meeting and file. **Stop** finishes it;
  **New meeting** finishes it and starts another.
- Click any paragraph to correct it. Enter saves, Escape cancels, and
  clearing a paragraph removes it.
- **Names and terms** (in Details): names, acronyms and jargon, so they're
  spelt right.
- **Transcript** (in Details): where the file is, copy, download, and delete
  (deleted meetings go to the Trash).
- The sidebar lists past meetings and searches their text. The switch at its
  bottom picks a light or dark look.

### In the terminal

The transcript also prints in the terminal. Keys: **p** pause/resume, **n**
new meeting, **s** stop, **q** quit (Scribe saves first; so does closing the
terminal or Ctrl+C).

### Options

```
scribe --title "Weekly sync"          title for the meeting that starts now
scribe --no-autostart                 wait for Start instead of recording at once
scribe --mic default|off|NAME         choose the microphone
scribe --computer-audio default|off|NAME
scribe --list-inputs                  show the device names you can use above
scribe --model distil-large-v3.5      another Whisper model (default large-v3-turbo)
scribe --language auto                detect the language (default English)
scribe --folder ~/somewhere/else      where transcripts are saved
scribe --open tab|none                browser tab instead of a window, or neither
scribe --no-web                       terminal only
```

## Where things are kept

| What | Where |
| --- | --- |
| Transcripts, one `.txt` per meeting | `~/Documents/Transcripts` |
| Scribe's own copy of each meeting (for history and search) | `~/Documents/Transcripts/.scribe` |
| Settings | `~/.config/scribe/settings.json` |
| Log | `~/.local/state/scribe/scribe.log` |
| Speech model | `~/.cache/huggingface` |

A transcript file is rewritten every few seconds while there's new text, and
when you pause, stop, rename or quit. Saving replaces the file in one step, so
a crash can't leave half a transcript. A meeting where nobody spoke leaves no
file.

## Troubleshooting

- **Nothing appears when I talk.** Look at the microphone chip's bars. If they
  don't move, pick your microphone in Details → Microphone (or run
  `scribe --list-inputs`).
- **"on CPU" in the Details panel.** The GPU couldn't be used. Check the NVIDIA
  driver is installed (`nvidia-smi` should list your card), then run
  `./install.sh` again.
- **`scribe` says its environment is broken.** This happens after a system
  upgrade replaces Python. Run `./install.sh` again.

## Uninstall

```bash
rm ~/.local/bin/scribe
rm -rf <this folder> ~/.config/scribe ~/.local/state/scribe
```

Transcripts in `~/Documents/Transcripts` are left alone; delete them yourself
if you want them gone.

## Developing

```
scribe/            the Python app: audio capture, transcription, saving, web server
scribe/web/        the page: index.html and css/ (dist/ is built from frontend/)
frontend/src/      the page's TypeScript source, compiled into scribe/web/dist/
tests/             Python tests
```

Run the tests with `.venv/bin/python -m unittest discover -s tests`.

The interface is written in TypeScript; browsers only run JavaScript, so
`install.sh` compiles it into `scribe/web/dist/` (generated, not in git). To
change the interface, edit `frontend/src/` and rebuild:

```bash
cd frontend
npm install          # once
npm run build        # or: npm run watch
```

Then reload the Scribe window (Ctrl+R). Python changes need Scribe restarted.
