# First-run setup. Detects whether an NVIDIA card is present and installs
# only the parts this machine can use, so a laptop without one does not have
# to download two gigabytes of CUDA libraries.
#
# SERAsubs.bat runs this on the first launch. To decide manually:
#   SERAsubs.bat --cpu            CPU only, keeps the install small
#   SERAsubs.bat --gpu            install the CUDA libraries anyway
#   SERAsubs.bat --model small    download a model now instead of on first use

import argparse
import os
import shutil
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

# pip and the hub library both keep a cache in the user profile by default,
# and the graphics card libraries alone would leave two gigabytes there.
# both are pointed inside the folder, so deleting it removes everything
PIP_CACHE = os.path.join(ROOT_DIR, "python", "pip-cache")
os.environ.setdefault("HF_HOME", os.path.join(ROOT_DIR, "models", ".hub"))

MODEL_NAMES = ["base", "small", "large-v3"]

# kept in step with APP_NAME in serasubs.py
NAME = "SERAsubs-modified-"

# pip output that means nothing to someone who just wants subtitles
PIP_NOISE = (
    "Requirement already satisfied",
    "WARNING: The script",
    "WARNING: The scripts",
    "Consider adding this directory to PATH",
    "[notice]",
    "Collecting",
    "Successfully installed",
)


# rewrites a line of pip output, or drops it
def friendly(output):
    output = output.strip()
    if not output or output.startswith(PIP_NOISE):
        return None

    # the full wheel filename is noise, but staying silent through a two
    # gigabyte download looks like a crash, so keep the line and shorten it
    for prefix in ("Downloading ", "Using cached "):
        if output.startswith(prefix):
            rest = output[len(prefix):]
            # pip fetches a small metadata file before the wheel itself, and
            # reporting "nvidia_cudnn (1.9 kB)" right before the 737 MB file
            # of the same name looks broken
            if ".metadata" in rest:
                return None
            package = rest.split("-")[0].split(".whl")[0]
            size = rest[rest.rfind("("):] if rest.endswith(")") else ""
            return f"getting {package} {size}".strip()

    if output.startswith("Installing collected packages"):
        return "putting it all in place"

    return output


def line(text=""):
    print(text, flush=True)


NVIDIA_SMI = [
    "nvidia-smi",
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "nvidia-smi.exe"),
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]

# the smallest model needs about a gigabyte of video memory on top of what
# windows itself is already using. below this the CUDA libraries are two
# gigabytes downloaded for nothing
MIN_USEFUL_VRAM_MB = 2000

# what the largest model needs, kept in step with MODEL_VRAM_MB in serasubs.py
LARGE_MODEL_VRAM_MB = 4600


def ask_nvidia_smi(fields):
    for exe in NVIDIA_SMI:
        try:
            done = subprocess.run(
                [exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout.strip():
            return [part.strip()
                    for part in done.stdout.strip().splitlines()[0].split(",")]
    return None


# nvidia-smi ships with every driver, so if it reports a GPU there is one.
# how much memory it has decides whether the CUDA parts are worth installing
def find_nvidia_gpu():
    answer = ask_nvidia_smi("name,memory.total")
    if not answer or len(answer) < 2:
        return None
    try:
        memory = int(float(answer[1]))
    except ValueError:
        return None

    card = {"name": answer[0], "memory_mb": memory, "compute": None}

    # older drivers fail the whole query on this field, so it is asked for
    # on its own and simply left out when it isn't known
    capability = ask_nvidia_smi("compute_cap")
    if capability:
        try:
            card["compute"] = float(capability[0])
        except ValueError:
            pass
    return card


def describe(card):
    text = f"{card['name']}, {card['memory_mb'] / 1024:.1f} GB"
    if card["compute"]:
        text += f", compute {card['compute']:g}"
    return text


# runs pip quietly, and on failure shows the last few lines, which are the
# ones that say what actually went wrong
def pip_install(requirements):
    command = [sys.executable, "-m", "pip", "install", "--no-input",
               "--disable-pip-version-check", "--cache-dir", PIP_CACHE,
               "-r", requirements]

    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    kept = []
    for output in process.stdout:
        output = output.rstrip()
        kept.append(output)
        readable = friendly(output)
        if readable:
            line(f"   {readable}")
    process.wait()

    if process.returncode != 0:
        line()
        line("   That didn't work. Here's what it said:")
        for output in kept[-6:]:
            line(f"   {output}")
    return process.returncode == 0


# a successful install is not proof the card can be used, so ask directly.
# a driver that is too old surfaces here instead of mid-transcription
def cuda_really_works():
    check = subprocess.run(
        [sys.executable, "-c",
         "import os, site, glob\n"
         "for packages in site.getsitepackages():\n"
         "    root = os.path.join(packages, 'nvidia')\n"
         "    if not os.path.isdir(root):\n"
         "        continue\n"
         "    for dll in glob.glob(os.path.join(root, '**', '*.dll'), recursive=True):\n"
         "        try:\n"
         "            os.add_dll_directory(os.path.dirname(dll))\n"
         "        except OSError:\n"
         "            pass\n"
         "import ctranslate2\n"
         "print(ctranslate2.get_cuda_device_count())\n"],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        problems = check.stderr.strip().splitlines()[-1:]
        return False, problems or ["couldn't load the CUDA libraries"]
    try:
        return int(check.stdout.strip() or 0) > 0, []
    except ValueError:
        return False, [check.stdout.strip()]


def download_model(model_name):
    from huggingface_hub import snapshot_download

    target = os.path.join(ROOT_DIR, "models", f"faster-whisper-{model_name}")
    line(f"Downloading the '{model_name}' model, this one takes a while ...")
    snapshot_download(
        repo_id=f"Systran/faster-whisper-{model_name}",
        local_dir=target,
        allow_patterns=["*.bin", "*.json", "*.txt", "*.model"],
    )
    line("   got it")


def main():
    parser = argparse.ArgumentParser(description=f"Set up {NAME}.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gpu", action="store_true",
                       help="install the CUDA libraries even without a detected GPU")
    group.add_argument("--cpu", action="store_true",
                       help="skip the CUDA libraries entirely (~2 GB smaller)")
    parser.add_argument("--model", choices=MODEL_NAMES,
                        help="download this model now instead of on first use")
    args = parser.parse_args()

    line()
    line(f"  Setting up {NAME}")
    line("  This only happens once. Grab a drink, it takes a few minutes.")
    line("  " + "-" * 56)
    line()

    gpu = find_nvidia_gpu()
    if args.cpu:
        want_gpu = False
        line("Graphics card: skipping it, you asked for the CPU version")
    elif args.gpu:
        want_gpu = True
        line("Graphics card: " + (describe(gpu) if gpu else
                                  "none found, installing the GPU parts anyway"))
    elif not gpu:
        want_gpu = False
        line("Graphics card: none found, so this will run on your processor")
    else:
        line(f"Graphics card: {describe(gpu)}")
        # a card this small cannot hold a model, and finding that out after
        # a two gigabyte download helps nobody
        want_gpu = gpu["memory_mb"] >= MIN_USEFUL_VRAM_MB
        if not want_gpu:
            line()
            line("   That card has too little memory to run the transcription")
            line(f"   on ({gpu['memory_mb'] / 1024:.1f} GB, at least "
                 f"{MIN_USEFUL_VRAM_MB / 1024:.1f} GB is needed). The two")
            line("   gigabytes of CUDA libraries are being skipped,")
            line(f"   {NAME} will use your processor instead.")
            line("   Run  SERAsubs.bat --gpu  to install them anyway.")

    if want_gpu and gpu and gpu["compute"] and gpu["compute"] < 7.0:
        line()
        line(f"   Note: this card is older than the ones float16 needs, so it")
        line(f"   runs in a slower mode. It still works.")

    line()

    line("Installing the transcription engine ...")
    if not pip_install(os.path.join(APP_DIR, "requirements.txt")):
        line()
        line("Setup failed. Check that you're online and try again.")
        return 1
    line("   done")

    if want_gpu:
        line()
        line("Installing the graphics card support (about 2 GB, be patient) ...")
        if not pip_install(os.path.join(APP_DIR, "requirements-gpu.txt")):
            line(f"   couldn't install it, {NAME} uses the processor instead")
            want_gpu = False
        else:
            line("   done")

    line()
    if want_gpu:
        works, problems = cuda_really_works()
        if works:
            line("Checked the graphics card: it works, transcription will be fast.")
            # the largest model is the one that will not fit on a small card,
            # better said now than when a run dies halfway through
            if gpu and gpu["memory_mb"] < LARGE_MODEL_VRAM_MB:
                line(f"   The 'Slowest (Higher accuracy)' model needs about "
                     f"{LARGE_MODEL_VRAM_MB / 1024:.1f} GB and won't fit,")
                line(f"   {NAME} will quietly use your processor for that one.")
        else:
            line("Checked the graphics card: it can't be used, falling back to the")
            line("processor. This usually means the NVIDIA driver is too old.")
            for problem in problems:
                line(f"   {problem}")
    else:
        line("All set for the processor. It works, it's just slower than a card.")

    if args.model:
        line()
        download_model(args.model)

    # kept until here so a second attempt after a failure is quick, and
    # dropped once there is nothing left to retry
    shutil.rmtree(PIP_CACHE, ignore_errors=True)

    line()
    line("  " + "-" * 56)
    line(f"  Ready. {NAME} is starting.")
    line()
    return 0


if __name__ == "__main__":
    sys.exit(main())
