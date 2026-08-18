# Builds the zip that gets published. The point is that the bundled python
# is stripped of every installed package first, otherwise the release carries
# the whole dependency tree and ends up several gigabytes large.
#
#   python\python.exe tools\make_release.py               normal release
#   python\python.exe tools\make_release.py --no-ffmpeg   smaller, no burn-in
#   python\python.exe tools\make_release.py --keep-folder keep the staging copy

import argparse
import os
import re
import shutil
import sys
import zipfile

# this file lives in tools\, so the project root is one level up
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the only files a user should see when opening the folder
ROOT_FILES = [
    "SERAsubs.bat",
    "README.md",
]

# the folder everything else lives in. tools\ is deliberately left out,
# nobody downloading the release needs the script that built it
CODE_FOLDERS = [
    "app",
]

OPTIONAL_FILES = ["LICENSE", "LICENSE.txt", "LICENSE.md"]

# the only packages shipped with the release, everything else is installed
# on the user's machine by install.py
KEEP_PACKAGES = {
    "pip",
    "pkg_resources",
    "setuptools",
    "_distutils_hack",
    "distutils-precedence.pth",
}

# parts of the python folder the app never uses. the renamed launcher is
# left out on purpose: it is a rewritten copy of python.exe and belongs on
# the machine that runs it, made by make_launcher.py on the first start
SKIP_IN_PYTHON = {
    os.path.join("Doc"),
    os.path.join("Lib", "test"),
    os.path.join("Lib", "idlelib"),
    "SERAsubs-modified-.exe",
    "pip-cache",
}

# ffmpeg ships three large executables and only one of them is used.
# the licence files have to come along
FFMPEG_FILES = [
    os.path.join("bin", "ffmpeg.exe"),
    "LICENSE",
    "README.txt",
]


def line(text=""):
    print(text, flush=True)


def human(num_bytes):
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / 1024 ** 3:.2f} GB"
    return f"{num_bytes / 1024 ** 2:.0f} MB"


def folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# the version is read from serasubs.py, so there is only one place to change
def read_version():
    source = os.path.join(APP_DIR, "app", "serasubs.py")
    with open(source, encoding="utf-8") as f:
        found = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.M)
    return found.group(1) if found else "0"


def is_package_wanted(name):
    if name in KEEP_PACKAGES:
        return True
    # the .dist-info folders belonging to the packages that are kept
    base = name.split("-")[0]
    return base in KEEP_PACKAGES


# copies the python runtime without the installed packages, so the release
# ships a bare python that install.py fills in on the user's machine
def copy_python(target):
    source = os.path.join(APP_DIR, "python")
    site_packages = os.path.join(source, "Lib", "site-packages")

    def ignore(directory, names):
        skipped = set()
        relative = os.path.relpath(directory, source)

        for name in names:
            if name == "__pycache__" or name.endswith(".pdb"):
                skipped.add(name)

        # the installed packages, which are nearly all of the weight
        if os.path.normpath(directory) == os.path.normpath(site_packages):
            for name in names:
                if not is_package_wanted(name):
                    skipped.add(name)

        for name in names:
            candidate = os.path.normpath(os.path.join(relative, name))
            if candidate in SKIP_IN_PYTHON:
                skipped.add(name)

        return skipped

    shutil.copytree(source, target, ignore=ignore)


def copy_ffmpeg(target):
    source = os.path.join(APP_DIR, "ffmpeg")
    for relative in FFMPEG_FILES:
        origin = os.path.join(source, relative)
        if not os.path.isfile(origin):
            continue
        destination = os.path.join(target, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(origin, destination)


def zip_folder(folder, archive_path):
    root_name = os.path.basename(folder)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        for root, _, files in os.walk(folder):
            for name in files:
                full = os.path.join(root, name)
                inside = os.path.join(root_name, os.path.relpath(full, folder))
                archive.write(full, inside)


def main():
    parser = argparse.ArgumentParser(description="Build a SERAsubs release.")
    parser.add_argument("--out", default="dist",
                        help="where to put the release (default: dist)")
    parser.add_argument("--no-ffmpeg", action="store_true",
                        help="leave ffmpeg out, which disables burning subtitles in")
    parser.add_argument("--keep-folder", action="store_true",
                        help="don't delete the unzipped copy afterwards")
    args = parser.parse_args()

    version = read_version()
    name = f"SERAsubs-modified-{version}"
    out_dir = os.path.join(APP_DIR, args.out)
    staging = os.path.join(out_dir, name)

    line(f"Building {name}")
    line("=" * 40)

    missing = [f for f in ROOT_FILES
               if not os.path.isfile(os.path.join(APP_DIR, f))]
    missing += [f for f in CODE_FOLDERS
                if not os.path.isdir(os.path.join(APP_DIR, f))]
    if missing:
        line("Can't build, these are missing: " + ", ".join(missing))
        return 1

    if not os.path.isfile(os.path.join(APP_DIR, "python", "python.exe")):
        line("Can't build, there's no python folder to ship.")
        return 1

    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)

    line("Copying the app ...")
    for relative in ROOT_FILES:
        shutil.copy2(os.path.join(APP_DIR, relative),
                     os.path.join(staging, relative))
    for folder in CODE_FOLDERS:
        shutil.copytree(os.path.join(APP_DIR, folder),
                        os.path.join(staging, folder),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for relative in OPTIONAL_FILES:
        origin = os.path.join(APP_DIR, relative)
        if os.path.isfile(origin):
            shutil.copy2(origin, os.path.join(staging, relative))

    line("Copying the python runtime (without the installed packages) ...")
    copy_python(os.path.join(staging, "python"))

    if args.no_ffmpeg:
        line("Skipping ffmpeg, this release can't burn subtitles in.")
    elif os.path.isdir(os.path.join(APP_DIR, "ffmpeg")):
        line("Copying ffmpeg (just the one executable it uses) ...")
        copy_ffmpeg(os.path.join(staging, "ffmpeg"))
    else:
        line("No ffmpeg folder here, so this release can't burn subtitles in.")

    unpacked = folder_size(staging)
    line(f"Unpacked: {human(unpacked)}")

    line("Zipping, this is the slow part ...")
    archive_path = os.path.join(out_dir, f"{name}.zip")
    if os.path.isfile(archive_path):
        os.remove(archive_path)
    zip_folder(staging, archive_path)

    if not args.keep_folder:
        shutil.rmtree(staging)

    line()
    line(f"Done: {os.path.relpath(archive_path, APP_DIR)}")
    line(f"      {human(os.path.getsize(archive_path))} zipped, "
         f"{human(unpacked)} unpacked")
    line()
    line("Users extract it and run SERAsubs.bat. That's the whole thing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
