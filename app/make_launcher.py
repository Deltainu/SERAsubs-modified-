# Builds python\SERAsubs-modified-.exe, the runtime the app itself runs under.
#
# A plain copy of python.exe is enough to get the right name into the task
# manager's details, but its "Processes" tab shows the description held in the
# file's version resource, and a copy still says "Python" there. So the copy
# gets a version resource of its own written into it.
#
# SERAsubs.bat calls this when the launcher is missing. If anything about the
# rewrite fails, the plain copy stays behind and everything still works.

import ctypes
import os
import shutil
import struct
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

NAME = "SERAsubs-modified-"

SOURCE = os.path.join(ROOT_DIR, "python", "python.exe")
TARGET = os.path.join(ROOT_DIR, "python", f"{NAME}.exe")

# an earlier version of this went by a shorter name
OUTDATED = os.path.join(ROOT_DIR, "python", "SERAsubs.exe")

VERSION = (1, 0, 0, 0)

RT_VERSION = 16
LANGUAGE = 0x0409          # us english, the language python.exe itself uses
CODE_PAGE = 0x04B0         # unicode


def line(text=""):
    print(text, flush=True)


# every block in a version resource starts on a four byte boundary
def _pad(data):
    return data + b"\0" * (-len(data) % 4)


def _text(value):
    return value.encode("utf-16-le") + b"\0\0"


# one node of the tree: header, key, value, then whatever hangs below it.
# the padding is counted from the start of the block, so the length field
# has to be in place before it is worked out
def _block(key, value=b"", is_text=False, children=b""):
    counted = len(value) // 2 if is_text else len(value)
    head = struct.pack("<HHH", 0, counted, 1 if is_text else 0) + _text(key)
    block = bytearray(_pad(head))
    if value:
        block += _pad(value)
    block += children
    block[0:2] = struct.pack("<H", len(block))
    return bytes(block)


def _entry(key, value):
    return _pad(_block(key, _text(value), is_text=True))


# VS_FIXEDFILEINFO, the numeric half of the resource
def _fixed_info():
    major, minor, patch, build = VERSION
    return struct.pack(
        "<LLLLLLLLLLLLL",
        0xFEEF04BD,                    # signature
        0x00010000,                    # struct version
        (major << 16) | minor,         # file version, high and low
        (patch << 16) | build,
        (major << 16) | minor,         # product version
        (patch << 16) | build,
        0x3F,                          # which flag bits are valid
        0,                             # flags
        0x00040004,                    # VOS_NT_WINDOWS32
        1,                             # VFT_APP
        0,                             # subtype
        0, 0,                          # creation date
    )


def version_resource():
    strings = b"".join([
        _entry("CompanyName", NAME),
        _entry("FileDescription", NAME),
        _entry("FileVersion", ".".join(str(part) for part in VERSION)),
        _entry("InternalName", NAME),
        _entry("OriginalFilename", f"{NAME}.exe"),
        _entry("ProductName", NAME),
        _entry("ProductVersion", ".".join(str(part) for part in VERSION)),
    ])

    table = _pad(_block(f"{LANGUAGE:04X}{CODE_PAGE:04X}", children=strings))
    string_info = _pad(_block("StringFileInfo", children=table))

    translation = _pad(_block("Translation",
                              struct.pack("<HH", LANGUAGE, CODE_PAGE)))
    var_info = _pad(_block("VarFileInfo", children=translation))

    return _block("VS_VERSION_INFO", _fixed_info(),
                  children=string_info + var_info)


# windows takes resource types and names either as strings or as small
# numbers pretending to be pointers
def _as_id(number):
    return ctypes.cast(ctypes.c_void_p(number), ctypes.c_wchar_p)


def write_version_resource(path, data):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.restype = ctypes.c_void_p
    kernel32.UpdateResourceW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_ushort, ctypes.c_void_p, ctypes.c_ulong,
    ]
    kernel32.EndUpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_bool]

    # False keeps everything else in the file, the icon and the manifest above all
    handle = kernel32.BeginUpdateResourceW(path, False)
    if not handle:
        raise OSError(ctypes.get_last_error(), "could not open the copy")

    ok = kernel32.UpdateResourceW(handle, _as_id(RT_VERSION), _as_id(1),
                                  LANGUAGE, data, len(data))
    if not ok:
        kernel32.EndUpdateResourceW(handle, True)
        raise OSError(ctypes.get_last_error(), "could not write the version")

    if not kernel32.EndUpdateResourceW(handle, False):
        raise OSError(ctypes.get_last_error(), "could not save the copy")


# a launcher that does not start is worse than one with the wrong name
def runs(path):
    try:
        done = subprocess.run([path, "-c", "import sys"], capture_output=True,
                              timeout=60)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    if not os.path.isfile(SOURCE):
        line("No python runtime here to copy.")
        return 1

    # an installation that already has the old name gets it cleaned up
    if os.path.isfile(OUTDATED):
        try:
            os.remove(OUTDATED)
        except OSError:
            pass

    shutil.copy2(SOURCE, TARGET)
    if not runs(TARGET):
        line("The copied runtime doesn't start, staying with python.exe.")
        try:
            os.remove(TARGET)
        except OSError:
            pass
        return 1

    try:
        write_version_resource(TARGET, version_resource())
    except OSError as problem:
        # the plain copy is already in place and works, so this is not fatal
        line(f"Kept the plain copy, naming it failed: {problem}")
        return 0

    if not runs(TARGET):
        line("Naming it broke the copy, putting the plain one back.")
        shutil.copy2(SOURCE, TARGET)

    return 0


if __name__ == "__main__":
    sys.exit(main())
