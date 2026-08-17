# SERAsubs

Offline auto-transcription for Windows. Give it a video or audio file, get a timed `.srt`
back, optionally burned into the video. Made for clipping workflows.

This is a fork of [seraotonin/SERAsubs](https://github.com/seraotonin/SERAsubs).

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

## Without an NVIDIA card

Everything still works, it is just slower. Transcription runs on the processor, and burning
subtitles in uses ffmpeg's normal x264 encoder instead of the card's, which is the slow part.
The setup skips the GPU libraries in that case, which also makes the install about 2 GB smaller.

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
              languages.py, install.py
    tools\    make_release.py, builds the release zip

With Python 3.11+ and tkinter: `pip install -r app\requirements.txt`, then
`python app\serasubs.py`.

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
