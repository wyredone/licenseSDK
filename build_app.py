"""
build_app.py - Compile/obfuscate a Python app for distribution (item 8).

Modes:
  nuitka   - compile to a native single-file executable (recommended)
  pyarmor  - obfuscate bytecode, then pack to a single-file executable

Usage:
  python build_app.py myapp.py --name MyApp --mode nuitka --gui --icon icon.ico
  python build_app.py myapp.py --mode pyarmor --gui
  python build_app.py myapp.py --mode nuitka --dry-run        (print command only)

License SDK files (license_sdk.py, license_dialog.py) in the same folder are
included automatically. Output lands in ./dist.
"""

import subprocess
import sys
import os
import shutil
import argparse

def _ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
    except ImportError:
        print(f"[build] installing {pkg} ...")
        base = [sys.executable, "-m", "pip", "install", pkg]
        try:
            subprocess.check_call(base)
        except subprocess.CalledProcessError:
            subprocess.check_call(base + ["--break-system-packages"])

SDK_MODULES = ["license_sdk", "license_dialog"]


def find_sdk_modules(entry_dir):
    found = []
    for m in SDK_MODULES:
        if os.path.exists(os.path.join(entry_dir, m + ".py")):
            found.append(m)
    return found


def build_nuitka(args):
    if not args.dry_run:
        _ensure("nuitka")
    entry_dir = os.path.dirname(os.path.abspath(args.script)) or "."
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        "--remove-output",
        f"--output-dir={args.out}",
        f"--output-filename={args.name}",
    ]
    if args.gui:
        cmd += ["--enable-plugin=tk-inter"]
        if sys.platform == "win32":
            cmd += ["--windows-console-mode=disable"]
    if args.icon and sys.platform == "win32":
        cmd += [f"--windows-icon-from-ico={args.icon}"]
    for m in find_sdk_modules(entry_dir) + (args.include or []):
        cmd += [f"--include-module={m}"]
    if args.company:
        cmd += [f"--company-name={args.company}"]
    if args.version:
        cmd += [f"--product-version={args.version}"]
    cmd += [args.script]
    return cmd


def build_pyarmor(args):
    if not args.dry_run:
        _ensure("pyarmor")
    entry_dir = os.path.dirname(os.path.abspath(args.script)) or "."
    extras = [os.path.join(entry_dir, m + ".py")
              for m in find_sdk_modules(entry_dir)]
    extras += [m if m.endswith(".py") else m + ".py" for m in (args.include or [])]
    cmd = [
        sys.executable, "-m", "pyarmor", "gen",
        "--pack", "onefile",
        "-O", args.out,
        args.script, *extras,
    ]
    return cmd


def main():
    p = argparse.ArgumentParser(description="Build a protected distributable")
    p.add_argument("script", help="Entry-point .py file")
    p.add_argument("--name", default=None, help="Executable name (default: script name)")
    p.add_argument("--mode", choices=["nuitka", "pyarmor"], default="nuitka")
    p.add_argument("--gui", action="store_true", help="Tkinter GUI app (no console window)")
    p.add_argument("--icon", default=None, help=".ico file (Windows)")
    p.add_argument("--include", nargs="*", default=[], help="Extra modules to include")
    p.add_argument("--out", default="dist", help="Output directory (default: dist)")
    p.add_argument("--company", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--dry-run", action="store_true", help="Print the command, don't run")
    args = p.parse_args()

    if not os.path.exists(args.script):
        sys.exit(f"[build] not found: {args.script}")
    if not args.name:
        args.name = os.path.splitext(os.path.basename(args.script))[0]
    os.makedirs(args.out, exist_ok=True)

    cmd = build_nuitka(args) if args.mode == "nuitka" else build_pyarmor(args)
    print("[build] command:\n  " + " ".join(cmd))
    if args.dry_run:
        return

    r = subprocess.call(cmd)
    if r != 0:
        sys.exit(f"[build] FAILED (exit {r})")

    print(f"\n[build] DONE — output in ./{args.out}/")
    print("[build] Reminders:")
    print("  - Test the exe on a clean machine (no Python installed)")
    print("  - vendor_keys.json / license_generator.py must NEVER be shipped")
    print("  - Nuitka needs a C compiler (MSVC or MinGW on Windows; it can auto-download MinGW)")


if __name__ == "__main__":
    main()
