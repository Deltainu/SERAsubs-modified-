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
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

MODEL_NAMES = ["base", "small", "large-v3"]

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


# nvidia-smi ships with every driver, so if it reports a GPU there is one
def find_nvidia_gpu():
    candidates = [
        "nvidia-smi",
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                     "System32", "nvidia-smi.exe"),
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for exe in candidates:
        try:
            done = subprocess.run([exe, "-L"], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and "GPU 0" in done.stdout:
            # "GPU 0: NVIDIA GeForce RTX 4090 (UUID: ...)" down to the name
            first = done.stdout.strip().splitlines()[0]
            name = first.split(":", 1)[-1].split("(UUID")[0]
            return name.strip()
    return None


# runs pip quietly, and on failure shows the last few lines, which are the
# ones that say what actually went wrong
def pip_install(requirements):
    command = [sys.executable, "-m", "pip", "install", "--no-input",
               "--disable-pip-version-check", "-r", requirements]

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
    parser = argparse.ArgumentParser(description="Set up SERAsubs.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gpu", action="store_true",
                       help="install the CUDA libraries even without a detected GPU")
    group.add_argument("--cpu", action="store_true",
                       help="skip the CUDA libraries entirely (~2 GB smaller)")
    parser.add_argument("--model", choices=MODEL_NAMES,
                        help="download this model now instead of on first use")
    args = parser.parse_args()

    line()
    line("  Setting up SERAsubs")
    line("  This only happens once. Grab a drink, it takes a few minutes.")
    line("  " + "-" * 56)
    line()

    gpu = find_nvidia_gpu()
    if args.cpu:
        want_gpu = False
        line("Graphics card: skipping it, you asked for the CPU version")
    elif args.gpu:
        want_gpu = True
        line(f"Graphics card: {gpu or 'none found, installing the GPU parts anyway'}")
    else:
        want_gpu = gpu is not None
        line(f"Graphics card: {gpu or 'none found, so this will run on your processor'}")
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
            line("   couldn't install it, SERAsubs will use the processor instead")
            want_gpu = False
        else:
            line("   done")

    line()
    if want_gpu:
        works, problems = cuda_really_works()
        if works:
            line("Checked the graphics card: it works, transcription will be fast.")
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

    line()
    line("  " + "-" * 56)
    line("  Ready. SERAsubs is starting.")
    line()
    return 0


if __name__ == "__main__":
    sys.exit(main())
