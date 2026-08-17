# SERAsubs-modified-

Offline auto-transcription for Windows. Give it a video or audio file, get a timed `.srt`
back, optionally burned into the video. Made for clipping workflows.

This is a fork of [seraotonin/SERAsubs](https://github.com/seraotonin/SERAsubs).

## Formats

    Video   mp4, mkv, mov, webm, avi, m4v, ts
    Audio   mp3, wav, m4a, flac, ogg, opus, aac, wma

The same list sits behind the ⓘ next to **Select file** in the window. Subtitles can only be
burned into video, so with an audio file that checkbox switches itself off.

## Install

Download `SERAsubs-modified-x.x.zip` from Releases, extract it properly (right click, Extract All,
don't drag the files out), and run **SERAsubs.bat**. That is the only file to click.

The first launch sets itself up: it checks for an NVIDIA card, installs only the parts your
machine can use, and downloads a speech model the first time you press Start. The window
shows a progress bar for the model download, the transcription and the burn-in, so you can
see what it is doing. Nothing is ever uploaded, your clips stay on your machine.

ffmpeg is included in the release, you do not need to install anything else.

## What this fork changes

- Runs on the GPU through faster-whisper instead of CPU-only PyTorch
- Cuts subtitles to readable length using word timings, with a size setting for burn-in
- Burns subtitles into the video
- All 100 Whisper languages, pick several for clips that switch mid-sentence
- One start file, dependencies and models fetched on demand (Instead of downloading from Google Drive, directly via Hugging Face)
- A Stop button that ends the run, the model download or the encode behind it
- A music mode for singing, which the speech filter would otherwise throw away
- Checks the card before starting, size and what is free right now, and falls back to
  the processor with a reason instead of dying halfway through

## Music and singing

The speech filter that skips silence also treats singing over instruments as noise, and on a
song it can drop more than half the track before the model ever hears it. Tick **Music or
singing** for those. It goes through the whole file instead, which is slower, and the largest
model is worth picking here.

Expect fewer correct words than on speech either way. Whisper is a speech model, and sung
vocals, especially in an invented or heavily stylised language, are close to its limit.

## When something goes wrong

Every run writes a line to `serasubs.log` next to `SERAsubs.bat`: which file, which model,
which device, how many subtitles came out, and the reason if it stopped. That file is what
to attach when reporting a problem.

## Without an NVIDIA card

Everything still works, it is just slower. Transcription runs on the processor, and burning
subtitles in uses ffmpeg's normal x264 encoder instead of the card's, which is the slow part.
The setup skips the GPU libraries in that case, which also makes the install about 2 GB smaller.

A card with very little memory is treated the same way: the setup says so and skips the GPU
libraries rather than downloading two gigabytes for something that cannot hold a model.
`--gpu` installs them anyway. If a card is big enough but busy with other programs, the run
falls back to the processor and the window names the programs sitting on it.

## Options

    SERAsubs.bat --cpu            skip the GPU libraries, about 2 GB smaller
    SERAsubs.bat --gpu            install them even without a detected card
    SERAsubs.bat --model small    download a model now instead of on first use

Models: base (142 MB) · small (464 MB, default) · large-v3 (2.9 GB). Only the one you pick
is downloaded, and only once. They come from the
[Systran](https://huggingface.co/Systran) repositories on Hugging Face, which are the
CTranslate2 conversions of OpenAI's Whisper weights, and land in the `models` folder.

## Development

    app\      serasubs.py (window + transcription), subtitles.py (cue splitting),
              languages.py, install.py (first-run setup),
              make_launcher.py (names the runtime copy)
    tools\    make_release.py, builds the release zip

faster-whisper asks for Python 3.9 or newer; the release ships 3.13. With your own Python
and tkinter: `pip install -r app\requirements.txt`, then `python app\serasubs.py`.

`SERAsubs.bat` runs the app through `python\SERAsubs-modified-.exe`, a copy of the runtime with its
version resource rewritten, so the task manager shows the app instead of a python. The copy
is made on the machine it runs on, never shipped. Started directly with `python`, the app
behaves the same, it just keeps the name of whatever started it and leaves your terminal
alone.

### ffmpeg

Not in the repository, but bundled into the release and required for burning subtitles in.
It comes from [GyanD/codexffmpeg](https://github.com/GyanD/codexffmpeg/releases), the release
repo for the gyan.dev Windows builds. Take any `ffmpeg-*-essentials_build.zip`.

The build currently bundled is
[2026-03-26-git-fd9f1e9c52](https://github.com/GyanD/codexffmpeg/releases/tag/2026-03-26-git-fd9f1e9c52).

Extract it so that `ffmpeg\bin\ffmpeg.exe` sits next to `SERAsubs.bat`, or have ffmpeg on your
PATH. Only `ffmpeg.exe` is used, `ffplay` and `ffprobe` can go. It has to be built with
**libass** (the `subtitles` filter) and, for GPU encoding, **nvenc** — the essentials builds
have both, check with `ffmpeg -buildconf | findstr libass`.

## Credits

SERAsubs was created by [seraotonin](https://github.com/seraotonin). The idea, the original
implementation and the name are theirs, and this fork is only built on top of that work.

Speech recognition uses OpenAI's Whisper models, run through faster-whisper (CTranslate2).

Created in Collab with Claude Opus 5.
