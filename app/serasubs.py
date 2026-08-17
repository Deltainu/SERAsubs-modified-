#oh my god/// why are you looking at my code omg BBBBAKA you're looking through
# a girl's personal things KYAAAA omgg/////

#okay i'm kidding but im so anxious about others looking at my code so
#if you've found your way here i guess i'll show you around
#because im an anxious wreck and also i love my script baby

#basically here we're importing the stuff we need like the language model
#and thing to create this user friendly ui and stuff
import sys
import site
import os
import glob
import queue
import shutil
import subprocess
import threading
from collections import deque
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from languages import language_choices, language_name
from subtitles import cues_from_segments, DEFAULT_STYLE, STYLES

__version__ = "2.0"


# This cat was original placed by Sera.
# Don't touch her, for she lives here and watches over this code.
# I had to add the "r" because my console didn't like those escaped slashes.

cat = r"""
 /\_/\
( °w° )
 )   (  )
(__(__)__)
"""

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

# selectable models and what each one costs to download
MODELS = [
    ("Fastest (Lower accuracy)", "base", "142 MB"),
    ("Balanced (Recommended)", "small", "464 MB"),
    ("Slowest (Higher accuracy)", "large-v3", "2.9 GB"),
]

# pre-converted CTranslate2 builds of the Whisper weights
MODEL_REPO = "Systran/faster-whisper-{}"
MODEL_PATTERNS = ("*.bin", "*.json", "*.txt", "*.model")
MODEL_PATTERNS_SUFFIX = tuple(p.lstrip("*") for p in MODEL_PATTERNS)

def time_format(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def write_srt_entry(f, index, start, end, text):
    f.write(f"{index}\n")
    f.write(f"{time_format(start)} --> {time_format(end)}\n")
    f.write(text.strip() + "\n\n")

# files that ship with the code, such as the icon
def resource_path(relative_path):
    base = getattr(sys, '_MEIPASS', APP_DIR)
    return os.path.join(base, relative_path)

# python, ffmpeg and models, one level above app/
def project_path(relative_path):
    base = getattr(sys, '_MEIPASS', ROOT_DIR)
    return os.path.join(base, relative_path)

# audio decoding happens in python, so ffmpeg is only needed for burning in
def add_ffmpeg_to_path():
    ffmpeg_bin = project_path(os.path.join("ffmpeg", "bin"))
    if os.path.isdir(ffmpeg_bin):
        os.environ["PATH"] += os.pathsep + ffmpeg_bin

add_ffmpeg_to_path()

# bundled copy first, then whatever is on PATH
def find_ffmpeg():
    local = project_path(os.path.join("ffmpeg", "bin", "ffmpeg.exe"))
    if os.path.isfile(local):
        return local
    return shutil.which("ffmpeg")

# containers that can have subtitles burned into them
VIDEO_TYPES = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts")


def is_video(path):
    return path.lower().endswith(VIDEO_TYPES)


# stops a console window appearing for every ffmpeg call
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_nvenc_cache = {}


# NVENC encodes much faster than libx264 where card and build support it
def has_nvenc(ffmpeg):
    if ffmpeg not in _nvenc_cache:
        try:
            done = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                                  capture_output=True, text=True, timeout=30,
                                  creationflags=NO_WINDOW)
            _nvenc_cache[ffmpeg] = "h264_nvenc" in done.stdout
        except (OSError, subprocess.SubprocessError):
            _nvenc_cache[ffmpeg] = False
    return _nvenc_cache[ffmpeg]


# runs ffmpeg, reports progress and keeps the last error lines on failure
def run_ffmpeg(command, work_dir, duration, progress_cb):
    process = subprocess.Popen(
        command, cwd=work_dir, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )

    tail = deque(maxlen=6)

    # stderr must be drained in its own thread or the pipe buffer fills up
    # and the process blocks
    def drain():
        for line in process.stderr:
            line = line.strip()
            if line:
                tail.append(line)

    drainer = threading.Thread(target=drain, daemon=True)
    drainer.start()

    for line in process.stdout:
        if line.startswith("out_time_us=") and duration:
            try:
                micros = int(line.split("=", 1)[1])
            except ValueError:
                continue
            progress_cb(min(100, micros / 1_000_000 / duration * 100))

    process.wait()
    drainer.join(timeout=2)

    if process.returncode == 0:
        return True, ""
    return False, " | ".join(tail) or f"ffmpeg stopped with code {process.returncode}"


def burn_subtitles(ffmpeg, video_path, srt_path, out_path, duration,
                   progress_cb, use_gpu):
    # the subtitles filter needs windows paths escaped, so ffmpeg is run from
    # the output folder with a plain filename instead
    work_dir = os.path.dirname(os.path.abspath(srt_path))
    temp_name = "serasubs_burn.srt"
    temp_srt = os.path.join(work_dir, temp_name)
    shutil.copyfile(srt_path, temp_srt)

    if use_gpu:
        video_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
    else:
        video_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]

    problem = ""
    try:
        # copying the audio is instant but not every format allows it,
        # so fall back to re-encoding
        for audio_args in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
            command = [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-i", os.path.abspath(video_path),
                "-vf", f"subtitles={temp_name}",
                *video_args, *audio_args,
                "-progress", "pipe:1",
                os.path.abspath(out_path),
            ]
            ok, problem = run_ffmpeg(command, work_dir, duration, progress_cb)
            if ok:
                return
    finally:
        try:
            os.remove(temp_srt)
        except OSError:
            pass

    raise RuntimeError(problem)

if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
    site_packages_path = os.path.join(sys._MEIPASS, 'Lib', 'site-packages')
    sys.path.append(site_packages_path)
    os.environ["PATH"] += os.pathsep + sys._MEIPASS
else:
    base_path = APP_DIR

# the CUDA DLLs come from pip wheels inside site-packages, which windows does
# not search on its own, so they are registered before ctranslate2 is imported
def register_cuda_dlls():
    if not hasattr(os, "add_dll_directory"):
        return
    for packages in site.getsitepackages() + [os.path.dirname(os.__file__)]:
        nvidia_root = os.path.join(packages, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for dll in glob.glob(os.path.join(nvidia_root, "**", "*.dll"),
                             recursive=True):
            folder = os.path.dirname(dll)
            try:
                os.add_dll_directory(folder)
            except OSError:
                continue
            os.environ["PATH"] += os.pathsep + folder

register_cuda_dlls()

# report a missing setup as a message instead of a traceback
try:
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    from faster_whisper.tokenizer import _LANGUAGE_CODES
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "SERAsubs",
        "SERAsubs isn't set up yet.\n\n"
        "Please run SERAsubs.bat first, it installs everything this needs.",
    )
    sys.exit(1)


# float16 on the GPU, int8 on the CPU
def cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def device_settings(choice):
    if choice.startswith("GPU"):
        return "cuda", "float16"
    if choice.startswith("CPU"):
        return "cpu", "int8"
    # "Auto" prefers the GPU when there is one
    if cuda_available():
        return "cuda", "float16"
    return "cpu", "int8"


# where a model lives, and how to tell it downloaded completely
def model_dir(model_name):
    return project_path(os.path.join("models", f"faster-whisper-{model_name}"))


def model_is_ready(model_name):
    return os.path.isfile(os.path.join(model_dir(model_name), "model.bin"))


# total download size taken from the hub so the progress bar is accurate.
# returns 0 when it cannot be queried, and then no percentage is shown
def expected_download_size(model_name):
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(MODEL_REPO.format(model_name),
                                  files_metadata=True)
        return sum(f.size or 0 for f in info.siblings
                   if f.rfilename.endswith(MODEL_PATTERNS_SUFFIX))
    except Exception:
        return 0


def folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# models are fetched on first use instead of being shipped with the app
def download_model(model_name, progress_cb):
    from huggingface_hub import snapshot_download

    target = model_dir(model_name)
    expected = expected_download_size(model_name)

    # not every hub download backend reports progress through tqdm, so
    # progress is measured by watching the target folder grow
    stop = threading.Event()

    def watch():
        while not stop.wait(0.5):
            progress_cb(min(99, folder_size(target) / expected * 100))

    watcher = None
    if expected:
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()

    try:
        snapshot_download(
            repo_id=MODEL_REPO.format(model_name),
            local_dir=target,
            allow_patterns=list(MODEL_PATTERNS),
        )
    finally:
        stop.set()

    progress_cb(100)


class Main:
    def __init__(self, root):
        #initialization of the main process script
        self.root = root
        self.root.iconbitmap(resource_path("logo_256.ico"))
        self.root.title("SERAsubs (modified)")
        self.root.geometry("380x820")
        self.root.minsize(380, 700)

        self.input_path = None
        self.output_path = None

        # keep the loaded model so a second run does not reload it from disk
        self.model = None
        self.loaded_key = None
        self.running = False

        # worker threads post UI updates here
        self.ui_queue = queue.Queue()

        # selected language codes, empty means auto-detect
        self.selected_codes = []
        self.all_codes = language_choices(_LANGUAGE_CODES)
        self.has_cuda = cuda_available()
        self.ffmpeg = find_ffmpeg()

        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_languages())
        self.model_choice = tk.StringVar(value=MODELS[1][0])
        self.device_choice = tk.StringVar(
            value="Auto" if self.has_cuda else "CPU")
        self.subtitle_style = tk.StringVar(value=DEFAULT_STYLE)
        self.burn = tk.BooleanVar()

        tk.Label(root, text="SERAsubs (modified)",
                 font=("Arial", 13, "bold")).pack(pady=8)

        tk.Button(root, text="Select file",
                  command=self.select_input).pack()
        self.input_label = tk.Label(root, text="File not selected")
        self.input_label.pack(pady=4)

        tk.Button(root, text="Select Output Folder",
                  command=self.select_output).pack()
        self.output_label = tk.Label(self.root, text="Output folder not selected")
        self.output_label.pack(pady=4)

        self.build_language_picker(root)
        self.build_settings(root)

        self.start_button = tk.Button(
            root,
            text="Start",
            command=self.process,
        )
        self.start_button.pack(pady=10)

        #just so u know this is the part that got me struggling
        self.status = tk.Label(root, text="")
        self.status.pack(pady=4)

        # progress for downloading, transcribing and burning in
        self.progress = ttk.Progressbar(root, length=300, maximum=100)
        self.progress.pack(pady=2)

        # shows which device the next run will use
        self.device_note = tk.Label(root, font=("Arial", 8), fg="grey")
        self.device_note.pack(side="bottom", pady=6)
        self.update_device_note()

        self.refresh_languages()
        self.pump()

    # all 100 whisper languages with a search box, several can be ticked
    def build_language_picker(self, root):
        frame = tk.LabelFrame(root, text="Language")
        frame.pack(fill="both", expand=True, padx=12, pady=6)

        top = tk.Frame(frame)
        top.pack(fill="x", padx=6, pady=4)
        tk.Entry(top, textvariable=self.search).pack(
            side="left", fill="x", expand=True)
        tk.Button(top, text="Clear", command=self.clear_languages).pack(
            side="left", padx=4)

        listing = tk.Frame(frame)
        listing.pack(fill="both", expand=True, padx=6)

        scroll = tk.Scrollbar(listing, orient="vertical")
        scroll.pack(side="right", fill="y")

        # the selection is tracked manually so it survives filtering,
        # tkinter's own selection would be cleared when the list is refilled
        self.language_box = tk.Listbox(
            listing,
            height=8,
            activestyle="none",
            selectmode="none",
            exportselection=False,
            yscrollcommand=scroll.set,
        )
        self.language_box.pack(side="left", fill="both", expand=True)
        self.language_box.bind("<Button-1>", self.toggle_language)
        scroll.config(command=self.language_box.yview)

        self.language_summary = tk.Label(frame, text="", fg="grey",
                                         font=("Arial", 8), wraplength=330,
                                         justify="left")
        self.language_summary.pack(fill="x", padx=6, pady=4)

    def build_settings(self, root):
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=12)

        tk.Label(frame, text="Model").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.model_choice,
            values=[label for label, _, _ in MODELS],
            state="readonly",
            width=24,
        ).grid(row=1, column=0, padx=(0, 8), pady=2)

        # the GPU entry is only offered when a card was actually found
        tk.Label(frame, text="Device").grid(row=0, column=1, sticky="w")
        devices = ["Auto", "GPU (CUDA)", "CPU"] if self.has_cuda else ["CPU"]
        ttk.Combobox(
            frame,
            textvariable=self.device_choice,
            values=devices,
            state="readonly",
            width=12,
        ).grid(row=1, column=1, pady=2)

        self.device_choice.trace_add(
            "write", lambda *_: self.update_device_note())

        # how much text may be on screen at once, see STYLES in subtitles.py
        tk.Label(frame, text="Subtitle size").grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            frame,
            textvariable=self.subtitle_style,
            values=list(STYLES),
            state="readonly",
            width=24,
        ).grid(row=3, column=0, padx=(0, 8), pady=2, sticky="w")

        self.burn_check = tk.Checkbutton(
            frame,
            text="Burn subtitles into the video",
            variable=self.burn,
        )
        self.burn_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # without ffmpeg burning cannot work, so disable it visibly
        if not self.ffmpeg:
            self.burn.set(False)
            self.burn_check.config(state="disabled")
            tk.Label(frame, text="(needs the ffmpeg folder next to this app)",
                     font=("Arial", 8), fg="grey").grid(
                row=5, column=0, columnspan=2, sticky="w")
            
    def refresh_languages(self):
        needle = self.search.get().strip().lower()
        self.visible_codes = [
            code for code in self.all_codes
            if not needle
            or needle in language_name(code).lower()
            or needle == code
        ]

        self.language_box.delete(0, tk.END)
        for code in self.visible_codes:
            tick = "✓ " if code in self.selected_codes else "   "
            self.language_box.insert(tk.END, f"{tick}{language_name(code)} ({code})")

        self.update_language_summary()

    def toggle_language(self, event):
        if not self.visible_codes:
            return "break"

        index = self.language_box.nearest(event.y)
        if index < 0 or index >= len(self.visible_codes):
            return "break"

        code = self.visible_codes[index]
        if code in self.selected_codes:
            self.selected_codes.remove(code)
        else:
            self.selected_codes.append(code)

        tick = "✓ " if code in self.selected_codes else "   "
        self.language_box.delete(index)
        self.language_box.insert(index, f"{tick}{language_name(code)} ({code})")
        self.update_language_summary()
        return "break"

    def clear_languages(self):
        self.selected_codes = []
        self.search.set("")
        self.refresh_languages()

    def update_language_summary(self):
        if not self.selected_codes:
            text = "Nothing picked → the language gets detected automatically."
        elif len(self.selected_codes) == 1:
            text = f"Forced to {language_name(self.selected_codes[0])}."
        else:
            names = ", ".join(language_name(c) for c in self.selected_codes)
            text = (f"Mixed mode ({names}) → the language is detected per "
                    "segment, so switching mid-sentence is fine.")
        self.language_summary.config(text=text)

    def update_device_note(self):
        device, compute = device_settings(self.device_choice.get())
        note = f"Will run on {device.upper()} ({compute})"
        if not self.has_cuda:
            note += "  •  no NVIDIA GPU found"
        self.device_note.config(text=note)

    def select_input(self):
        path = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mkv *.mov *.webm *.wav *.mp3 *.m4a *.flac *.ogg")])
        if path:
            self.input_path = path
            self.input_label.config(text=os.path.basename(path))

    def select_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output_path = path
            self.output_label.config(text=path)

    def set_status(self, text):
        self.ui_queue.put(("status", text))

    def set_progress(self, percent):
        self.ui_queue.put(("progress", percent))

    def set_busy(self, busy):
        self.ui_queue.put(("busy", busy))

    # empties that queue, always from the main thread
    def pump(self):
        latest = {}
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()
                latest[kind] = value
        except queue.Empty:
            pass

        if "status" in latest:
            self.status.config(text=latest["status"])
        if "progress" in latest:
            self.progress.config(value=latest["progress"])
        if "busy" in latest:
            self.start_button.config(
                state="disabled" if latest["busy"] else "normal")

        self.root.after(80, self.pump)

    def normalize(self, path):
        return os.path.abspath(os.path.normpath(path))

    def process(self):
        if self.running:
            return
        self.set_status("Ready...")
        if not self.input_path:
            self.set_status("Select a video first.")
            return
        if not self.output_path:
            self.set_status("Select an output folder.")
            return

        self.running = True
        self.start_button.config(state="disabled")
        self.set_progress(0)
        threading.Thread(target=self.deeper_process, daemon=True).start()

    # downloads the model on first use, then loads it unless it is cached
    def get_model(self, model_name, size_hint, device, compute_type):
        if not model_is_ready(model_name):
            self.set_status(f"Downloading model ({size_hint}), one time only...")
            download_model(model_name, self.set_progress)
            self.set_progress(0)

        key = (model_name, device, compute_type)
        if self.model is not None and self.loaded_key == key:
            return self.model

        self.model = None
        self.loaded_key = None
        self.set_status("Loading model...")
        model = WhisperModel(
            model_dir(model_name),
            device=device,
            compute_type=compute_type,
            cpu_threads=os.cpu_count() or 4,
        )
        self.model = model
        self.loaded_key = key
        return model

    def burn_step(self, name, srt_path, duration, device):
        if not self.ffmpeg:
            return "Subtitles saved. Burning needs ffmpeg, which I can't find."
        if not is_video(self.input_path):
            return "Subtitles saved. Nothing to burn them onto, that's audio."

        use_gpu = device == "cuda" and has_nvenc(self.ffmpeg)
        where = "GPU" if use_gpu else "CPU"
        self.set_status(f"Burning subtitles into the video ({where})...")
        self.set_progress(0)

        burned = os.path.join(self.output_path, f"{name}_subbed.mp4")
        burn_subtitles(self.ffmpeg, self.input_path, srt_path, burned,
                       duration, self.set_progress, use_gpu)

        self.set_progress(100)
        return f"Completed! Subtitles burned into {os.path.basename(burned)}"

    def deeper_process(self):
        try:
            os.makedirs(self.output_path, exist_ok=True)

            name = os.path.splitext(os.path.basename(self.input_path))[0]
            srt_path = os.path.join(self.output_path, f"{name}_subs.srt")

            choice = self.model_choice.get()
            model_name, size_hint = next(
                (short, size) for label, short, size in MODELS if label == choice)

            device, compute_type = device_settings(self.device_choice.get())
            model = self.get_model(model_name, size_hint, device, compute_type)

            self.set_status("Processing audio...")

            # none = auto-detect, one = forced, several = detected per segment
            codes = self.selected_codes
            language = codes[0] if len(codes) == 1 else None
            multilingual = len(codes) > 1

            # batching only pays off on the GPU, on the CPU it just costs memory
            if device == "cuda":
                engine = BatchedInferencePipeline(model=model)
                extra = {"batch_size": 16}
            else:
                engine = model
                extra = {}

            # vad_filter drops silence before it reaches the model, and
            # condition_on_previous_text=False avoids repetition loops
            # word_timestamps is what the cue splitting in subtitles.py needs,
            # without it whisper returns half a minute of speech as one block
            segments, info = engine.transcribe(
                self.input_path,
                language=language,
                multilingual=multilingual,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                word_timestamps=True,
                **extra,
            )

            self.set_status("Writing subtitles...")

            # segments stream in, so cues are cut and written as they arrive
            total = info.duration or 0
            with open(srt_path, "w", encoding="utf-8") as f:
                cues = cues_from_segments(segments, self.subtitle_style.get())
                for i, cue in enumerate(cues, 1):
                    write_srt_entry(f, i, cue["start"], cue["end"], cue["text"])
                    if total:
                        self.set_progress(min(100, cue["end"] / total * 100))

            self.set_progress(100)

            done = "Completed!"
            if not codes:
                done += f"  (detected: {language_name(info.language)})"

            if self.burn.get():
                done = self.burn_step(name, srt_path, info.duration, device)

            self.set_status(done)

        except Exception as e:
            # show the reason in the status line instead of failing silently
            self.set_status(f"Failed: {e}")

        finally:
            self.running = False
            self.set_busy(False)

if __name__ == "__main__":
    root = tk.Tk()
    Main(root)
    root.mainloop()
