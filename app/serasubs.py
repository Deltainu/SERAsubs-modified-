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
import gc
import glob
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from languages import language_choices, language_name
from subtitles import cues_from_segments, DEFAULT_STYLE, STYLES

__version__ = "1.0"

# what this fork is called, everywhere it shows: the window, the taskbar,
# the task manager and the runtime it starts under
APP_NAME = "SERAsubs-modified-"


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

# roughly how much video memory a model needs, weights plus the run itself.
# a card with less takes the app down instead of reporting anything
MODEL_VRAM_MB = {
    "base": 1100,
    "small": 1700,
    "large-v3": 4600,
}

# pre-converted CTranslate2 builds of the Whisper weights
MODEL_REPO = "Systran/faster-whisper-{}"
MODEL_PATTERNS = ("*.bin", "*.json", "*.txt", "*.model")
MODEL_PATTERNS_SUFFIX = tuple(p.lstrip("*") for p in MODEL_PATTERNS)

# int8 is the fastest a processor runs these weights, and this is where the
# gain from batching flattens out
CPU_COMPUTE_TYPE = "int8"
CPU_BATCH_SIZE = 8

# below this share of the file becoming subtitles, the voice filter is the
# likely reason rather than silence
MIN_COVERAGE = 0.5

LOG_FILE = "serasubs.log"
LOG_MAX_BYTES = 512 * 1024


# raised when the user presses Stop, so a cancelled run can be told apart
# from one that actually broke
class Cancelled(Exception):
    pass


# a download that did not finish. its own type, because retrying it on the
# processor would download the same thing again
class DownloadFailed(Exception):
    pass

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

# the status line is gone once the window closes, so a run also leaves a
# note next to the app. it is all there is to go on when a report comes in
def log(text):
    path = project_path(LOG_FILE)
    try:
        mode = "a"
        if os.path.isfile(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            mode = "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
    except OSError:
        pass


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

# sound only, all of these decode but there is no picture to burn into
AUDIO_TYPES = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma")


def is_video(path):
    return path.lower().endswith(VIDEO_TYPES)


# one list feeds both the file dialog and what the app says it accepts
def type_filter():
    return " ".join(f"*{suffix}" for suffix in VIDEO_TYPES + AUDIO_TYPES)


def type_summary():
    return (f"Video:  {', '.join(s.lstrip('.') for s in VIDEO_TYPES)}\n"
            f"Audio:  {', '.join(s.lstrip('.') for s in AUDIO_TYPES)}\n\n"
            "Subtitles can only be burned into video.")


# stops a console window appearing for every ffmpeg call
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_nvenc_cache = {}

# nvidia-smi ships with every driver and answers without loading any CUDA
# library, which is what makes it safe to ask before anything heavy runs
NVIDIA_SMI = (
    "nvidia-smi",
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "nvidia-smi.exe"),
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
)

_gpu_cache = {}


def _nvidia_smi_rows(query):
    for exe in NVIDIA_SMI:
        try:
            done = subprocess.run(
                [exe, query, "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=30,
                creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout.strip():
            return [[part.strip() for part in line.split(",")]
                    for line in done.stdout.strip().splitlines()]
    return None


def _ask_nvidia_smi(fields):
    rows = _nvidia_smi_rows(f"--query-gpu={fields}")
    # only the first card is used, which is the one CUDA takes too
    return rows[0] if rows else None


# name and video memory of the card, and its compute capability where the
# driver is new enough to report it
def gpu_info():
    if "info" in _gpu_cache:
        return _gpu_cache["info"]

    info = None
    answer = _ask_nvidia_smi("name,memory.total")
    if answer and len(answer) >= 2:
        try:
            info = {"name": answer[0], "memory_mb": int(float(answer[1])),
                    "compute": None}
        except ValueError:
            info = None

    if info:
        # older drivers don't know this field and fail the whole query,
        # so it is asked for separately
        capability = _ask_nvidia_smi("compute_cap")
        if capability:
            try:
                info["compute"] = float(capability[0])
            except ValueError:
                pass

    _gpu_cache["info"] = info
    return info


# batching multiplies the memory a run needs, so a small card gets smaller
# batches instead of running out
def gpu_batch_size():
    info = gpu_info()
    memory = info["memory_mb"] if info else 0
    if memory >= 10000:
        return 16
    if memory >= 6000:
        return 8
    return 4


# free memory is asked for fresh every time, another program can take it at
# any moment and a cached answer would be worthless
def gpu_free_memory():
    answer = _ask_nvidia_smi("memory.free")
    if not answer:
        return None
    try:
        return int(float(answer[0]))
    except ValueError:
        return None


# windows keeps these on the card at all times. they use next to nothing and
# cannot be closed, so naming them as culprits would only mislead
SYSTEM_GPU_APPS = frozenset({
    "explorer.exe", "dwm.exe", "sihost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "shellhost.exe",
    "textinputhost.exe", "applicationframehost.exe", "lockapp.exe",
    "phoneexperiencehost.exe", "crossdeviceresume.exe", "widgets.exe",
    "systemsettings.exe", "nvcontainer.exe", "nvidia overlay.exe",
    "nvidia share.exe", "nvidia web helper.exe",
})


# which programs are holding the card. windows does not report how much each
# one takes, so on most machines this is names only
def gpu_memory_users(most=3):
    rows = _nvidia_smi_rows("--query-compute-apps=process_name,used_gpu_memory")
    if not rows:
        return []

    mine = os.path.basename(sys.executable).lower()
    users = []
    for row in rows:
        if not row or not row[0]:
            continue
        name = os.path.basename(row[0])
        # the driver writes [N/A] or [Insufficient Permissions] in place of
        # values it will not hand out
        if name.startswith("[") or name.lower() in SYSTEM_GPU_APPS:
            continue
        if name.lower() == mine:
            continue
        try:
            used = int(float(row[1])) if len(row) > 1 else None
        except ValueError:
            used = None
        users.append((name, used))

    users.sort(key=lambda user: user[1] or 0, reverse=True)
    return users[:most]


# returns why this model cannot run on this card, or None if it can.
# live=False skips asking about free memory, which costs a moment
def vram_problem(model_name, live=True):
    info = gpu_info()
    needed = MODEL_VRAM_MB.get(model_name)
    if not info or not needed:
        return None

    if info["memory_mb"] < needed:
        return (f"the {info['name']} has {info['memory_mb'] / 1024:.1f} GB, "
                f"this model needs about {needed / 1024:.1f} GB")

    # the card is big enough, but something else may be sitting on it
    free = gpu_free_memory()
    if not live or free is None or free >= needed:
        return None

    problem = (f"only {free / 1024:.1f} GB of the card's "
               f"{info['memory_mb'] / 1024:.1f} GB are free right now, "
               f"this model needs about {needed / 1024:.1f} GB")

    users = gpu_memory_users()
    if users:
        listed = ", ".join(f"{name} ({used / 1024:.1f} GB)" if used else name
                           for name, used in users)
        problem += f" — closing one of these frees some: {listed}"
    return problem


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


# runs ffmpeg, reports progress and keeps the last error lines on failure.
# register hands the process out so Stop can end it
def run_ffmpeg(command, work_dir, duration, progress_cb, register=None):
    process = subprocess.Popen(
        command, cwd=work_dir, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    if register:
        register(process)

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
                   progress_cb, use_gpu, register=None, stopped=None):
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
            ok, problem = run_ffmpeg(command, work_dir, duration, progress_cb,
                                     register)
            if ok:
                return
            # a killed ffmpeg looks like a failed one, so the audio fallback
            # must not start a second encode after Stop was pressed
            if stopped and stopped():
                raise Cancelled()
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
        APP_NAME,
        f"{APP_NAME} isn't set up yet.\n\n"
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


# float16 needs a card of the last few generations. asking the library beats
# guessing, so an older card gets a type it can actually run
def cuda_compute_type():
    if "compute" in _gpu_cache:
        return _gpu_cache["compute"]

    chosen = "float16"
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cuda")
        for candidate in ("float16", "int8_float16", "int8_float32", "float32"):
            if candidate in supported:
                chosen = candidate
                break
    except Exception as problem:
        log(f"could not ask which compute types the card supports: {problem}")

    _gpu_cache["compute"] = chosen
    return chosen


# more threads than physical cores makes this slower, not faster, and past
# sixteen it drops off sharply
def cpu_threads():
    logical = os.cpu_count() or 4
    return max(1, min(16, logical // 2 if logical > 4 else logical))


def device_settings(choice):
    if choice.startswith("GPU"):
        return "cuda", cuda_compute_type()
    if choice.startswith("CPU"):
        return "cpu", CPU_COMPUTE_TYPE
    # "Auto" prefers the GPU when there is one
    if cuda_available():
        return "cuda", cuda_compute_type()
    return "cpu", CPU_COMPUTE_TYPE


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


# the download runs in its own process purely so that Stop can end it, since
# the hub library cannot be interrupted from the outside
DOWNLOAD_SCRIPT = (
    "import sys\n"
    "from huggingface_hub import snapshot_download\n"
    "snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2],\n"
    "                  allow_patterns=sys.argv[3:])\n"
)


# models are fetched on first use instead of being shipped with the app
def download_model(model_name, progress_cb, register=None):
    target = model_dir(model_name)
    expected = expected_download_size(model_name)

    # not every hub download backend reports progress through tqdm, so
    # progress is measured by watching the target folder grow
    stop = threading.Event()

    def watch():
        while not stop.wait(0.5):
            progress_cb(min(99, folder_size(target) / expected * 100))

    if expected:
        threading.Thread(target=watch, daemon=True).start()

    process = subprocess.Popen(
        [sys.executable, "-c", DOWNLOAD_SCRIPT,
         MODEL_REPO.format(model_name), target, *MODEL_PATTERNS],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=NO_WINDOW,
    )
    if register:
        register(process)

    try:
        _, problem = process.communicate()
    finally:
        stop.set()

    if process.returncode != 0:
        # the hub library draws progress bars on the same stream, and one of
        # those as an error message tells nobody anything
        useful = [l.strip() for l in problem.splitlines()
                  if l.strip() and "%|" not in l]
        raise DownloadFailed(useful[-1] if useful else
                             "the download stopped before it was finished")

    progress_cb(100)


# tkinter has no tooltips, so this is one: a small window that appears while
# the pointer rests on a widget, and on a click as well
class Bubble:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.window = None
        self.timer = None
        widget.bind("<Enter>", lambda _: self.schedule())
        widget.bind("<Leave>", lambda _: self.hide())
        widget.bind("<Button-1>", lambda _: self.toggle())

    def schedule(self):
        self.cancel()
        self.timer = self.widget.after(300, self.show)

    def cancel(self):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None

    def show(self):
        if self.window:
            return

        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        tk.Label(self.window, text=self.text, justify="left",
                 background="#ffffe0", relief="solid", borderwidth=1,
                 font=("Arial", 8), padx=6, pady=4, wraplength=210).pack()

        # below the widget, pulled back onto the screen if it would hang off
        self.window.update_idletasks()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        room = self.widget.winfo_screenwidth() - self.window.winfo_width() - 8
        self.window.wm_geometry(f"+{max(8, min(x, room))}+{y}")

    def hide(self):
        self.cancel()
        if self.window:
            self.window.destroy()
            self.window = None

    def toggle(self):
        self.hide() if self.window else self.show()


class Main:
    def __init__(self, root):
        #initialization of the main process script
        self.root = root
        self.root.iconbitmap(resource_path("logo_256.ico"))
        self.root.title(APP_NAME)
        self.root.geometry("380x820")
        self.root.minsize(380, 700)

        self.input_path = None
        self.output_path = None

        # keep the loaded model so a second run does not reload it from disk
        self.model = None
        self.loaded_key = None
        self.running = False

        # set by Stop, read by the worker thread between steps
        self.cancel = threading.Event()

        # whichever of the killable processes is running right now
        self.child = None
        self.child_lock = threading.Lock()

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
        self.music = tk.BooleanVar()

        # set by a run that found much less speech than the file is long
        self.hint = ""

        tk.Label(root, text=APP_NAME,
                 font=("Arial", 13, "bold")).pack(pady=8)

        picker = tk.Frame(root)
        picker.pack()
        tk.Button(picker, text="Select file",
                  command=self.select_input).pack(side="left")

        # what can be dropped in here, without cluttering the window
        info = tk.Label(picker, text=" ⓘ", fg="#1a5fb4", cursor="hand2",
                        font=("Arial", 11))
        info.pack(side="left")
        Bubble(info, type_summary())

        self.input_label = tk.Label(root, text="File not selected")
        self.input_label.pack(pady=4)

        tk.Button(root, text="Select Output Folder",
                  command=self.select_output).pack()
        self.output_label = tk.Label(self.root, text="Output folder not selected")
        self.output_label.pack(pady=4)

        self.build_language_picker(root)
        self.build_settings(root)

        buttons = tk.Frame(root)
        buttons.pack(pady=10)

        self.start_button = tk.Button(
            buttons,
            text="Start",
            command=self.process,
        )
        self.start_button.pack(side="left", padx=4)

        # ends the run, including the download or the encode behind it
        self.stop_button = tk.Button(
            buttons,
            text="Stop",
            command=self.stop,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=4)

        #just so u know this is the part that got me struggling
        # wrapped, because saying which program is holding the card takes
        # more than a few words
        self.status = tk.Label(root, text="", wraplength=340,
                               justify="center")
        self.status.pack(pady=4, fill="x", padx=12)

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
        self.model_choice.trace_add(
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
        # the voice filter is trained on speech and drops singing, so music
        # needs it switched off. it costs speed, which is why it is a choice
        # and not the default
        tk.Checkbutton(
            frame,
            text="Music or singing (slower, keeps everything)",
            variable=self.music,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.burn_check.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # says why the checkbox is greyed out, otherwise it just looks broken
        self.burn_note = tk.Label(frame, text="", font=("Arial", 8), fg="grey",
                                  wraplength=330, justify="left")
        self.burn_note.grid(row=6, column=0, columnspan=2, sticky="w")

        self.update_burn_state()

    # burning needs ffmpeg and something to burn into, so for an audio file
    # the checkbox is switched off rather than left on to fail later
    def update_burn_state(self):
        if not self.ffmpeg:
            self.burn.set(False)
            self.burn_check.config(state="disabled")
            self.burn_note.config(text="(needs the ffmpeg folder next to this app)")
            return

        if self.input_path and not is_video(self.input_path):
            self.burn.set(False)
            self.burn_check.config(state="disabled")
            self.burn_note.config(
                text="(that's an audio file, there is no picture to burn into)")
            return

        self.burn_check.config(state="normal")
        self.burn_note.config(text="")


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

    def chosen_model(self):
        choice = self.model_choice.get()
        return next((short, size) for label, short, size in MODELS
                    if label == choice)

    def update_device_note(self):
        device, compute = device_settings(self.device_choice.get())
        note = f"Will run on {device.upper()} ({compute})"

        if not self.has_cuda:
            note += "  •  no NVIDIA GPU found"
        elif device == "cuda":
            # only the size of the card is judged here. what is free right now
            # is asked at the start of a run, it changes by the second
            short = vram_problem(self.chosen_model()[0], live=False)
            if short:
                note += f"\nToo small for this model ({short}), it will use the CPU"

        self.device_note.config(text=note)

    def select_input(self):
        path = filedialog.askopenfilename(
            filetypes=[("Media", type_filter()), ("All files", "*.*")])
        if path:
            self.input_path = path
            self.input_label.config(text=os.path.basename(path))
            self.update_burn_state()

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
            busy = latest["busy"]
            self.start_button.config(state="disabled" if busy else "normal")
            self.stop_button.config(state="normal" if busy else "disabled")

        self.root.after(80, self.pump)

    # Stop, and the pieces the worker thread uses to react to it

    def stop(self):
        if not self.running:
            return
        self.cancel.set()
        self.set_status("Stopping...")
        self.kill_child()

    # ending the running child is what makes Stop take effect immediately
    # instead of at the next step
    def register_child(self, process):
        with self.child_lock:
            self.child = process
        if self.cancel.is_set():
            self.kill_child()

    def kill_child(self):
        with self.child_lock:
            process = self.child
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def forget_child(self):
        with self.child_lock:
            self.child = None

    def stopped(self):
        return self.cancel.is_set()

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

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
        self.cancel.clear()
        self.forget_child()
        self.set_busy(True)
        self.set_progress(0)
        threading.Thread(target=self.deeper_process, daemon=True).start()

    # downloads the model on first use, then loads it unless it is cached
    def get_model(self, model_name, size_hint, device, compute_type):
        if not model_is_ready(model_name):
            self.set_status(f"Downloading model ({size_hint}), one time only...")
            try:
                download_model(model_name, self.set_progress,
                               self.register_child)
            except Exception:
                # a download that was killed by Stop looks exactly like one
                # that broke, and it should not be reported as a failure
                self.check_cancel()
                raise
            finally:
                self.forget_child()
            self.check_cancel()
            self.set_progress(0)

        key = (model_name, device, compute_type)
        if self.model is not None and self.loaded_key == key:
            return self.model

        self.release_model()
        self.set_status("Loading model...")
        model = WhisperModel(
            model_dir(model_name),
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads(),
        )
        self.model = model
        self.loaded_key = key
        return model

    # dropping the reference is what frees the video memory again, which
    # matters before a second attempt on a card that just ran out
    def release_model(self):
        self.model = None
        self.loaded_key = None
        gc.collect()

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
        try:
            burn_subtitles(self.ffmpeg, self.input_path, srt_path, burned,
                           duration, self.set_progress, use_gpu,
                           self.register_child, self.stopped)
        except Cancelled:
            # a half encoded video cannot be played, so it does not stay
            try:
                os.remove(burned)
            except OSError:
                pass
            raise
        finally:
            self.forget_child()

        self.set_progress(100)
        return f"Completed! Subtitles burned into {os.path.basename(burned)}"

    # everything from loading the model to the finished srt. it is one method
    # so the whole thing can be repeated on the processor when the card fails
    def transcribe_to_srt(self, model_name, size_hint, device, compute_type,
                          srt_path):
        model = self.get_model(model_name, size_hint, device, compute_type)
        self.check_cancel()

        self.set_status("Processing audio...")

        # none = auto-detect, one = forced, several = detected per segment
        codes = self.selected_codes
        language = codes[0] if len(codes) == 1 else None
        multilingual = len(codes) > 1

        # the voice filter is trained on speech and drops singing over
        # instruments before the model hears it. switching it off is the only
        # way to get all of a song, and batching needs it, so that run goes
        # through the file the slower way
        music = self.music.get()
        if music:
            engine = model
            batch_size = 0
            extra = {"vad_filter": False}
        else:
            # batching helps on both devices, only the size has to suit the
            # machine: the card gets what its memory allows, the processor a
            # fixed amount
            engine = BatchedInferencePipeline(model=model)
            batch_size = gpu_batch_size() if device == "cuda" else CPU_BATCH_SIZE
            extra = {"vad_filter": True, "batch_size": batch_size}

        # condition_on_previous_text=False avoids repetition loops, and
        # word_timestamps is what the cue splitting in subtitles.py needs,
        # without it whisper returns half a minute of speech as one block
        segments, info = engine.transcribe(
            self.input_path,
            language=language,
            multilingual=multilingual,
            beam_size=5,
            condition_on_previous_text=False,
            word_timestamps=True,
            **extra,
        )

        self.set_status("Writing subtitles...")

        # segments stream in, so cues are cut and written as they arrive
        total = info.duration or 0
        written = 0
        covered = 0.0
        with open(srt_path, "w", encoding="utf-8") as f:
            cues = cues_from_segments(segments, self.subtitle_style.get())
            for i, cue in enumerate(cues, 1):
                # the only place a long run can be stopped, and cues arrive
                # often enough that it feels immediate
                self.check_cancel()
                write_srt_entry(f, i, cue["start"], cue["end"], cue["text"])
                written = i
                covered += cue["end"] - cue["start"]
                if total:
                    self.set_progress(min(100, cue["end"] / total * 100))

        # a run that turned only a fraction of the file into subtitles was
        # filtered rather than silent, and that is worth saying
        self.hint = ""
        if not music and total and covered < total * MIN_COVERAGE:
            self.hint = (f"  Only {covered / total * 100:.0f}% of it was heard "
                         f"as speech — if there is singing in this, tick "
                         f"'Music or singing' and run it again.")

        mode = "music mode" if music else f"batch {batch_size}"
        share = f", {covered / total * 100:.0f}% covered" if total else ""
        log(f"{os.path.basename(self.input_path)}: {model_name} on {device} "
            f"({compute_type}, {mode}), {total:.0f}s audio, "
            f"{written} cues{share}")
        return info

    def deeper_process(self):
        try:
            os.makedirs(self.output_path, exist_ok=True)

            name = os.path.splitext(os.path.basename(self.input_path))[0]
            srt_path = os.path.join(self.output_path, f"{name}_subs.srt")

            model_name, size_hint = self.chosen_model()
            device, compute_type = device_settings(self.device_choice.get())

            # a card without the memory for this model ends the whole app
            # instead of reporting an error, so it never gets that far.
            # a model that is already loaded holds its memory, only a fresh
            # one has to fit alongside whatever else is on the card
            if device == "cuda":
                if self.loaded_key != (model_name, device, compute_type):
                    self.release_model()
                    short = vram_problem(model_name)
                else:
                    short = None
                if short:
                    log(f"not using the card for {model_name}: {short}")
                    self.set_status(f"Using the processor instead: {short}.")
                    device, compute_type = "cpu", CPU_COMPUTE_TYPE

            try:
                info = self.transcribe_to_srt(model_name, size_hint, device,
                                              compute_type, srt_path)
            except (Cancelled, KeyboardInterrupt, DownloadFailed):
                raise
            except Exception as problem:
                # anything the card throws is worth another try on the
                # processor, which is slower but always there
                if device != "cuda":
                    raise
                log(f"the card failed on {model_name}: {problem!r}")
                self.set_status("The graphics card couldn't do it, "
                                "starting over on the processor...")
                self.release_model()
                device, compute_type = "cpu", CPU_COMPUTE_TYPE
                info = self.transcribe_to_srt(model_name, size_hint, device,
                                              compute_type, srt_path)

            self.set_progress(100)

            done = "Completed!"
            if not self.selected_codes:
                done += f"  (detected: {language_name(info.language)})"
            done += self.hint

            if self.burn.get():
                done = self.burn_step(name, srt_path, info.duration, device)

            self.set_status(done)

        except Cancelled:
            log("stopped by the user")
            self.set_status("Stopped. What was written so far was kept.")
            self.set_progress(0)

        except DownloadFailed as problem:
            log(f"download failed: {problem}")
            self.set_status(f"Couldn't get the model, check your internet "
                            f"connection. ({problem})")
            self.set_progress(0)

        except Exception as e:
            # show the reason in the status line instead of failing silently
            log(f"failed: {e!r}")
            self.set_status(f"Failed: {e}")

        finally:
            self.forget_child()
            self.running = False
            self.set_busy(False)

# the console window belongs to the batch file. it is worth seeing while the
# app starts up, and only in the way afterwards, so it is put away once the
# window is there. SERAsubs.bat sets the variable, which means a terminal
# someone opened themselves is never touched
def set_console_visible(visible):
    if os.environ.get("SERASUBS_LAUNCHER") != "1":
        return
    try:
        import ctypes
        console = ctypes.windll.kernel32.GetConsoleWindow()
        if console:
            ctypes.windll.user32.ShowWindow(console, 5 if visible else 0)
    except Exception as problem:
        log(f"could not hide the console: {problem}")


# windows groups the taskbar button and its icon by this id. without it the
# app borrows the one belonging to the python runtime
def set_taskbar_identity():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
    except Exception as problem:
        log(f"could not set the taskbar identity: {problem}")


if __name__ == "__main__":
    set_taskbar_identity()
    # className is the name the window itself reports
    root = tk.Tk(className=APP_NAME)
    Main(root)

    # everything loaded, so the console has nothing left to show
    root.after(600, lambda: set_console_visible(False))

    try:
        root.mainloop()
    except BaseException:
        # whatever went wrong has to stay readable
        set_console_visible(True)
        raise
