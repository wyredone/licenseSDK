"""
license_injector.py - Guided tool to add the licensing framework to any Python app.

Two ways to use it:
  • Setup Wizard  — step-by-step, checks everything for you, great for first time.
  • Quick Inject  — one screen, for when you've done it before.

Run:  python license_injector.py

Keep these next to this tool (your private vendor folder):
  license_sdk.py   license_dialog.py   help_tips.py   license_generator.py
"""

import subprocess
import sys


def _ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


import os
import ast
import json
import shutil
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from help_tips import tip
except ImportError:
    def tip(*a, **k):
        pass

BEGIN = "# === BEGIN LICENSE GATE (auto-inserted by license_injector) ==="
END = "# === END LICENSE GATE ==="

GUI_FILES = ["license_sdk.py", "license_dialog.py", "help_tips.py"]
CONSOLE_FILES = ["license_sdk.py"]
VENDOR_FILES = ["license_sdk.py", "license_dialog.py", "help_tips.py", "license_generator.py"]
PLACEHOLDER = "PASTE-PUBLIC-KEY-FROM-GENERATOR-HERE"
HERE = os.path.dirname(os.path.abspath(__file__))


# ======================================================================
# CODE TRANSFORM (detect / inject)
# ======================================================================
def detect_app_type(src: str) -> str:
    low = src.lower()
    if "customtkinter" in low:
        return "customtkinter"
    if "pyqt" in low or "pyside" in low:
        return "pyqt"
    if "import tkinter" in low or "from tkinter" in low or "tkinter as tk" in low:
        return "tkinter"
    return "console"


def gate_block(app_type, app_name, trial_days, features, show_status=True):
    tdays = f", trial_days={int(trial_days)}" if trial_days else ""
    feat = ""
    if features:
        flist = ", ".join(repr(f.strip()) for f in features if f.strip())
        feat = f", require_features=[{flist}]"

    # All app types get the popup activation window (no terminal typing).
    # Falls back to console require_license only if tkinter isn't available.
    status = ""
    if show_status:
        status = f"\nprint('[{app_name}] ' + _lsum(_license_info))"
    manage_hint = ""
    if app_type == "tkinter":
        manage_hint = (
            "\n# Let users open the License Manager from your app anytime:\n"
            "#   from license_dialog import open_license_window\n"
            f"#   open_license_window({app_name!r}, your_root_window)"
        )
    else:
        manage_hint = (
            "\n# Open the License Manager from your app anytime:\n"
            "#   from license_dialog import open_license_window\n"
            f"#   open_license_window({app_name!r})"
        )

    body = (
        "import sys as _sys\n"
        "from license_sdk import require_license, LicenseError, license_summary as _lsum\n"
        "try:\n"
        "    from license_dialog import gui_require_license as _gate\n"
        f"    _lm, _license_info = _gate(app_name={app_name!r}{tdays})\n"
        "except Exception:\n"
        "    # tkinter unavailable -> fall back to console activation\n"
        "    try:\n"
        f"        _lm, _license_info = require_license(app_name={app_name!r}{tdays}{feat})\n"
        "    except LicenseError as _e:\n"
        "        print('License error:', _e); _sys.exit(1)\n"
    )
    # feature enforcement (the GUI gate doesn't take require_features, so check after)
    if features:
        flist = ", ".join(repr(f.strip()) for f in features if f.strip())
        body += (
            f"_missing = [_f for _f in [{flist}] if not _lm.has_feature(_f)]\n"
            "if _missing:\n"
            f"    print('[{app_name}] License missing required features:', ', '.join(_missing))\n"
            "    _sys.exit(1)\n"
        )
    body += status.lstrip("\n") + ("\n" if status else "")
    return f"{BEGIN}\n{body}{manage_hint}\n{END}\n"


def find_insert_line(src: str) -> int:
    lines = src.splitlines()
    insert = 0
    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or
                              (lines[i].lstrip().startswith("#") and "coding" in lines[i][:40])):
        i += 1
        insert = i
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return insert
    body = tree.body
    idx = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        insert = body[0].end_lineno
        idx = 1
    while idx < len(body) and isinstance(body[idx], ast.ImportFrom) and body[idx].module == "__future__":
        insert = body[idx].end_lineno
        idx += 1
    return insert


def strip_existing_gate(src: str) -> str:
    if BEGIN not in src:
        return src
    out, skipping = [], False
    for ln in src.splitlines(keepends=True):
        if ln.strip() == BEGIN:
            skipping = True
            continue
        if skipping and ln.strip() == END:
            skipping = False
            continue
        if not skipping:
            out.append(ln)
    return "".join(out)


def inject(src: str, app_type, app_name, trial_days, features, show_status=True):
    src = strip_existing_gate(src)
    lines = src.splitlines(keepends=True)
    at = find_insert_line(src)
    block = gate_block(app_type, app_name, trial_days, features, show_status)
    prefix = "" if at == 0 else "\n"
    return "".join(lines[:at] + [f"{prefix}{block}\n"] + lines[at:])


# ======================================================================
# CHECKS  (each returns dict: ok, msg, fix(callable|None), fix_label)
# ======================================================================
def _vendor_public_key(folder):
    p = os.path.join(folder, "vendor_keys.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p)).get("public")
    except Exception:
        return None


def _sdk_public_key(folder):
    p = os.path.join(folder, "license_sdk.py")
    if not os.path.exists(p):
        return None
    for ln in open(p, encoding="utf-8"):
        if ln.strip().startswith("PUBLIC_KEY_HEX"):
            try:
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                return None
    return None


def check_files(folder):
    missing = [f for f in VENDOR_FILES if not os.path.exists(os.path.join(folder, f))]
    if not missing:
        return {"ok": True, "msg": "All required files are in this folder.", "fix": None}
    return {"ok": False,
            "msg": "Missing from this folder:\n   • " + "\n   • ".join(missing) +
                   "\n\nCopy these files into the folder shown above, then re-check.",
            "fix": None}


def check_vendor_keys(folder):
    p = os.path.join(folder, "vendor_keys.json")
    if not os.path.exists(p):
        return {"ok": False,
                "msg": "You haven't created your signing keys yet.\n"
                       "Click 'Open Generator' — it makes the keys automatically the\n"
                       "first time it runs. Then come back and re-check.",
                "fix": lambda: _open_generator(folder), "fix_label": "Open Generator"}
    try:
        d = json.load(open(p))
        if d.get("private") and d.get("public"):
            return {"ok": True, "msg": "Signing keys found. (Keep vendor_keys.json private "
                                       "and backed up.)", "fix": None}
    except Exception:
        pass
    return {"ok": False, "msg": "vendor_keys.json exists but looks invalid. Delete it and "
                                "re-run the generator to recreate it.", "fix": None}


def check_public_key(folder):
    vpub = _vendor_public_key(folder)
    spub = _sdk_public_key(folder)
    if vpub is None:
        return {"ok": False, "msg": "Create your signing keys first (previous step).", "fix": None}
    if spub is None:
        return {"ok": False, "msg": "license_sdk.py not found in this folder.", "fix": None}
    if spub == PLACEHOLDER or not spub:
        return {"ok": False,
                "msg": "license_sdk.py still has the placeholder public key.\n"
                       "Click the button to paste your real key in automatically.",
                "fix": lambda: _patch_public_key(folder), "fix_label": "Wire Public Key Now"}
    if spub != vpub:
        return {"ok": False,
                "msg": "The public key in license_sdk.py doesn't match your signing keys.\n"
                       "Click to fix it automatically.",
                "fix": lambda: _patch_public_key(folder), "fix_label": "Fix Public Key"}
    return {"ok": True, "msg": "Public key is wired into license_sdk.py correctly.", "fix": None}


def check_deps():
    missing = []
    for mod in ("cryptography", "requests"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return {"ok": True, "msg": "Required Python packages are installed.", "fix": None}
    return {"ok": False,
            "msg": "Missing Python packages: " + ", ".join(missing) +
                   "\nClick to install them now.",
            "fix": lambda: _install_deps(missing), "fix_label": "Install Now"}


# ---- fix actions ----
def _open_generator(folder):
    gen = os.path.join(folder, "license_generator.py")
    if not os.path.exists(gen):
        messagebox.showerror("Not found", "license_generator.py is not in this folder.")
        return
    try:
        subprocess.Popen([sys.executable, gen])
        messagebox.showinfo("Generator launched",
                            "The generator opened in a new window.\n\n"
                            "On first run it shows a welcome popup and creates your keys.\n"
                            "When it's done, come back here and click 'Re-check'.")
    except Exception as e:
        messagebox.showerror("Couldn't launch", str(e))


def _patch_public_key(folder):
    vpub = _vendor_public_key(folder)
    sdk = os.path.join(folder, "license_sdk.py")
    if not vpub or not os.path.exists(sdk):
        messagebox.showerror("Can't patch", "Need both vendor_keys.json and license_sdk.py here.")
        return
    lines = open(sdk, encoding="utf-8").read().splitlines(keepends=True)
    out = []
    done = False
    for ln in lines:
        if ln.strip().startswith("PUBLIC_KEY_HEX") and not done:
            out.append(f'PUBLIC_KEY_HEX = "{vpub}"\n')
            done = True
        else:
            out.append(ln)
    if done:
        open(sdk, "w", encoding="utf-8").write("".join(out))
        messagebox.showinfo("Done", "Your public key is now wired into license_sdk.py.")
    else:
        messagebox.showerror("Not found", "Couldn't find the PUBLIC_KEY_HEX line in license_sdk.py.")


def _install_deps(missing):
    try:
        for m in missing:
            base = [sys.executable, "-m", "pip", "install", m]
            try:
                subprocess.check_call(base)
            except subprocess.CalledProcessError:
                subprocess.check_call(base + ["--break-system-packages"])
        messagebox.showinfo("Installed", "Packages installed. Click Re-check.")
    except Exception as e:
        messagebox.showerror("Install failed", str(e))


# ======================================================================
# HELP TEXT (per-step "?" buttons + a glossary)
# ======================================================================
WIZARD_HELP = {
    "intro": (
        "What this wizard does\n\n"
        "It adds a license check to your Python app so it only runs for people you\n"
        "give a key to. You don't need to understand the details — just follow the\n"
        "steps. Each step checks itself and won't let you continue until it's green.\n\n"
        "The whole process: make your signing keys → connect them to the license\n"
        "code → pick your app → click Inject → done. Most apps take under a minute."
    ),
    "step_files": (
        "Step 1 — Required files\n\n"
        "These four files must sit together in one folder on YOUR computer:\n"
        "   • license_sdk.py — the license check that ships inside your app\n"
        "   • license_dialog.py — the activation window (for GUI apps)\n"
        "   • help_tips.py — the little '?' helpers and tooltips\n"
        "   • license_generator.py — the tool you use to make customer keys\n\n"
        "If any are missing, copy them into this folder and click Re-check."
    ),
    "step_keys": (
        "Step 2 — Signing keys\n\n"
        "A 'signing key' is a secret that proves a license came from you. The\n"
        "generator creates it automatically the first time you run it, saved as\n"
        "vendor_keys.json.\n\n"
        "• Back this file up — lose it and you can't make keys your existing\n"
        "  customers will accept.\n"
        "• Keep it private — never put it in your app or send it to anyone.\n\n"
        "Click 'Open Generator', let it create the keys, then Re-check."
    ),
    "step_pubkey": (
        "Step 3 — Connect the keys to your app\n\n"
        "Your app needs the matching PUBLIC key so it can recognize the licenses\n"
        "you create. (The public key is safe to share — only the private one is\n"
        "secret.)\n\n"
        "Click 'Wire Public Key Now' and the wizard copies it into license_sdk.py\n"
        "for you. No manual editing needed."
    ),
    "step_deps": (
        "Step 4 — Python packages\n\n"
        "The license code needs two free packages: 'cryptography' (for the secure\n"
        "signatures) and 'requests' (to check the time online). If they're missing,\n"
        "click Install Now. When you later build your app into an .exe, these get\n"
        "bundled in automatically."
    ),
    "step_app": (
        "Step 5 — Choose your app\n\n"
        "Pick the main .py file of the app you want to protect (the one you run to\n"
        "start it).\n\n"
        "• App name — a unique label for this app. It keeps each app's license,\n"
        "  trial, and logs separate. Letters and numbers only.\n"
        "• Free trial days — how long people can use it free before needing a key.\n"
        "  Set 0 for no trial.\n"
        "• Require features — leave blank unless you sell tiers and want this app to\n"
        "  demand a specific one (e.g. 'pro').\n\n"
        "The wizard auto-detects whether your app is console, Tkinter, CustomTkinter,\n"
        "or PyQt, and inserts the right kind of check."
    ),
    "step_inject": (
        "Step 6 — Add the license check\n\n"
        "This inserts a few lines at the top of your app, copies the license files\n"
        "next to it, and saves a backup of your original first (a .bak file).\n\n"
        "It's safe to run again — re-running replaces the check instead of adding a\n"
        "second one. The preview shows exactly what gets added before you commit."
    ),
    "step_verify": (
        "Step 7 — Make sure it works\n\n"
        "The wizard confirms the check is in place and that the license code loads.\n\n"
        "Optional 'Run live test' (console apps): it briefly runs your app with no\n"
        "license to confirm it's blocked, then — if you choose — issues a temporary\n"
        "key, confirms the app runs, and cleans everything up. Nothing permanent is\n"
        "left behind."
    ),
    "glossary": (
        "Plain-language glossary\n\n"
        "Signing key (vendor_keys.json) — your secret stamp that makes licenses\n"
        "  valid. Private; back it up.\n"
        "Public key — the non-secret half your app uses to recognize your licenses.\n"
        "  Safe to ship.\n"
        "Hardware ID (HWID) — a fingerprint of a customer's computer, so a key only\n"
        "  works on their machine.\n"
        "REQ code — what a customer sends you (it contains their Hardware ID) so you\n"
        "  can make their key.\n"
        "LIC key — the license you generate and send back to the customer.\n"
        "Tier / features — optional plan levels (Basic/Pro/…) that unlock parts of\n"
        "  your app.\n"
        "Trial — a time-limited free run, one per computer.\n"
        "Gate — the few lines of license-check code added to the top of your app."
    ),
}


def show_help(parent, topic, title="Help"):
    text = WIZARD_HELP.get(topic, "No help for this topic.")
    w = tk.Toplevel(parent)
    w.title(title)
    w.resizable(False, False)
    tk.Label(w, text=text, justify="left", wraplength=560, padx=14, pady=12).pack()
    ttk.Button(w, text="Close", command=w.destroy).pack(pady=(0, 10))
    w.transient(parent)
    w.grab_set()


def help_button(parent, topic, title="Help"):
    b = ttk.Button(parent, text="?", width=2,
                   command=lambda: show_help(parent.winfo_toplevel(), topic, title))
    tip(b, "Click for help on this step")
    return b


# ======================================================================
# WIZARD GUI
# ======================================================================
STEPS = [
    ("Files", "step_files"),
    ("Signing keys", "step_keys"),
    ("Connect keys", "step_pubkey"),
    ("Packages", "step_deps"),
    ("Choose app", "step_app"),
    ("Add check", "step_inject"),
    ("Verify", "step_verify"),
]


class Wizard(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.folder = HERE
        self.current = 0
        self.passed = [False] * len(STEPS)
        # app config (step 5)
        self.app_path = ""
        self.app_type = "console"
        self.app_name = ""
        self.trial_days = 14
        self.features = []
        self.show_status = True
        self.injected = False

        # layout: left step list | right content
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, width=170)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        ttk.Label(left, text="Steps", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.step_lbls = []
        for i, (name, _) in enumerate(STEPS):
            lbl = ttk.Label(left, text=f"○  {i+1}. {name}")
            lbl.pack(anchor="w", pady=2)
            self.step_lbls.append(lbl)
        ttk.Separator(left).pack(fill="x", pady=8)
        gb = ttk.Button(left, text="Glossary",
                        command=lambda: show_help(self, "glossary", "Glossary"))
        gb.pack(anchor="w")
        tip(gb, "Plain-language definitions of every term")

        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True)

        # nav bar
        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(8, 0))
        self.back_btn = ttk.Button(nav, text="◀ Back", command=self.go_back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="Next ▶", command=self.go_next)
        self.next_btn.pack(side="right")
        self.recheck_btn = ttk.Button(nav, text="Re-check", command=self.render)
        self.recheck_btn.pack(side="right", padx=6)
        self.nav_hint = ttk.Label(nav, text="", foreground="#a60")
        self.nav_hint.pack(side="right", padx=8)

        self.render()

    # ---- step status icons ----
    def _update_steps(self):
        for i, lbl in enumerate(self.step_lbls):
            name = STEPS[i][0]
            if i == self.current:
                mark = "▶"
            elif self.passed[i]:
                mark = "✓"
            else:
                mark = "○"
            color = "#080" if self.passed[i] else ("#06c" if i == self.current else "#555")
            lbl.config(text=f"{mark}  {i+1}. {name}", foreground=color)

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _header(self, title, topic):
        bar = ttk.Frame(self.content)
        bar.pack(fill="x")
        ttk.Label(bar, text=title, font=("TkDefaultFont", 12, "bold")).pack(side="left")
        help_button(bar, topic, title).pack(side="right")

    def _result_box(self, res):
        ok = res["ok"]
        box = ttk.Frame(self.content)
        box.pack(fill="x", pady=8)
        icon = "✓" if ok else "✗"
        ttk.Label(box, text=icon, foreground="#080" if ok else "#c00",
                  font=("TkDefaultFont", 14, "bold")).pack(side="left", padx=(0, 8))
        ttk.Label(box, text=res["msg"], justify="left", wraplength=440).pack(side="left", anchor="w")
        if not ok and res.get("fix"):
            fb = ttk.Button(self.content, text=res.get("fix_label", "Fix"),
                            command=lambda: (res["fix"](), self.render()))
            fb.pack(anchor="w", pady=(0, 4))
        return ok

    # ---- render current step ----
    def render(self):
        self._clear_content()
        self.nav_hint.config(text="")
        i = self.current

        if i == 0:
            self._header("Step 1 — Required files", "step_files")
            ff = ttk.Frame(self.content); ff.pack(fill="x", pady=(6, 2))
            ttk.Label(ff, text="Toolkit folder:").pack(side="left")
            ttk.Label(ff, text=self.folder, foreground="#555").pack(side="left", padx=6)
            b = ttk.Button(ff, text="Change…", command=self._change_folder)
            b.pack(side="left")
            tip(b, "Folder holding license_sdk.py, the generator, etc.")
            res = check_files(self.folder)
            self.passed[i] = self._result_box(res)

        elif i == 1:
            self._header("Step 2 — Create your signing keys", "step_keys")
            res = check_vendor_keys(self.folder)
            self.passed[i] = self._result_box(res)

        elif i == 2:
            self._header("Step 3 — Connect keys to your app", "step_pubkey")
            res = check_public_key(self.folder)
            self.passed[i] = self._result_box(res)

        elif i == 3:
            self._header("Step 4 — Python packages", "step_deps")
            res = check_deps()
            self.passed[i] = self._result_box(res)

        elif i == 4:
            self._render_app_step()

        elif i == 5:
            self._render_inject_step()

        elif i == 6:
            self._render_verify_step()

        self._update_steps()
        self._update_nav()

    def _update_nav(self):
        self.back_btn.state(["!disabled"] if self.current > 0 else ["disabled"])
        last = self.current == len(STEPS) - 1
        if last:
            self.next_btn.config(text="Finish")
        else:
            self.next_btn.config(text="Next ▶")
        if not self.passed[self.current]:
            self.next_btn.state(["disabled"])
            self.nav_hint.config(text="Finish this step to continue")
        else:
            self.next_btn.state(["!disabled"])

    def go_back(self):
        if self.current > 0:
            self.current -= 1
            self.render()

    def go_next(self):
        if not self.passed[self.current]:
            return
        if self.current == len(STEPS) - 1:
            messagebox.showinfo("All done",
                                "Your app is licensed and ready.\n\n"
                                "When a customer sends you a REQ- code, open the generator's\n"
                                "Generate tab to make their key.")
            return
        self.current += 1
        self.render()

    def _change_folder(self):
        p = filedialog.askdirectory(initialdir=self.folder)
        if p:
            self.folder = p
            self.render()

    # ---- step 5: choose app ----
    def _render_app_step(self):
        self._header("Step 5 — Choose your app", "step_app")
        c = self.content
        row = ttk.Frame(c); row.pack(fill="x", pady=(8, 2))
        ttk.Label(row, text="App main .py:").pack(side="left")
        self.path_var = tk.StringVar(value=self.app_path)
        e = ttk.Entry(row, textvariable=self.path_var, width=44)
        e.pack(side="left", padx=4)
        tip(e, "The file you run to start your app")
        ttk.Button(row, text="Browse…", command=self._browse_app).pack(side="left")

        self.detect_lbl = ttk.Label(c, text="", foreground="#06c")
        self.detect_lbl.pack(anchor="w", pady=(4, 6))

        grid = ttk.Frame(c); grid.pack(fill="x")
        ttk.Label(grid, text="App name:").grid(row=0, column=0, sticky="w", pady=2)
        self.name_var = tk.StringVar(value=self.app_name)
        en = ttk.Entry(grid, textvariable=self.name_var, width=24)
        en.grid(row=0, column=1, sticky="w")
        tip(en, "Unique label — keeps this app's license/trial/logs separate")

        ttk.Label(grid, text="Free trial days (0 = none):").grid(row=1, column=0, sticky="w", pady=2)
        self.trial_var = tk.StringVar(value=str(self.trial_days))
        et = ttk.Entry(grid, textvariable=self.trial_var, width=8)
        et.grid(row=1, column=1, sticky="w")
        tip(et, "Days people can use it free before a key is needed")

        ttk.Label(grid, text="Require features (comma, optional):").grid(row=2, column=0, sticky="w", pady=2)
        self.feat_var = tk.StringVar(value=",".join(self.features))
        ef = ttk.Entry(grid, textvariable=self.feat_var, width=24)
        ef.grid(row=2, column=1, sticky="w")
        tip(ef, "Leave blank unless this app requires a paid tier (e.g. 'pro')")

        self.status_var = tk.BooleanVar(value=self.show_status)
        cbs = ttk.Checkbutton(grid, text="Show license status when the app starts (recommended)",
                              variable=self.status_var)
        cbs.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tip(cbs, "Prints e.g. 'Trial — 14 days remaining' so you and your users see it's working")

        ttk.Label(c, text="Preview of code that will be added:").pack(anchor="w", pady=(8, 2))
        self.prev = tk.Text(c, width=72, height=8, wrap="none")
        self.prev.pack(fill="x")

        for v in (self.path_var, self.name_var, self.trial_var, self.feat_var):
            v.trace_add("write", lambda *a: self._refresh_app_step())
        self.status_var.trace_add("write", lambda *a: self._refresh_app_step())
        self._refresh_app_step()

    def _browse_app(self):
        p = filedialog.askopenfilename(filetypes=[("Python", "*.py"), ("All", "*.*")])
        if p:
            self.path_var.set(p)
            if not self.name_var.get():
                self.name_var.set(os.path.splitext(os.path.basename(p))[0])
            self._refresh_app_step()

    def _refresh_app_step(self):
        p = self.path_var.get().strip()
        src = ""
        valid = False
        if p and os.path.exists(p):
            try:
                src = open(p, encoding="utf-8").read()
                ast.parse(src)
                valid = True
            except Exception:
                self.detect_lbl.config(text="⚠ This file isn't valid Python (can't parse it).",
                                       foreground="#c00")
        self.app_type = detect_app_type(src) if src else "console"
        if valid:
            already = BEGIN in src
            extra = "  —  already has a license check (will be replaced)" if already else ""
            self.detect_lbl.config(text=f"Detected app type: {self.app_type}{extra}",
                                   foreground="#06c")
        name = self.name_var.get().strip() or "MyApp"
        try:
            td = int(self.trial_var.get() or 0)
        except ValueError:
            td = 0
        feats = [f for f in self.feat_var.get().split(",") if f.strip()]
        ss = bool(self.status_var.get())
        self.prev.delete("1.0", "end")
        self.prev.insert("1.0", gate_block(self.app_type, name, td, feats, ss))

        # save + pass condition
        self.app_path = p
        self.app_name = name
        self.trial_days = td
        self.features = feats
        self.show_status = ss
        self.passed[4] = valid and bool(self.name_var.get().strip())
        self._update_steps()
        self._update_nav()

    # ---- step 6: inject ----
    def _render_inject_step(self):
        self._header("Step 6 — Add the license check", "step_inject")
        c = self.content
        ttk.Label(c, text=f"App:  {self.app_path}", wraplength=460,
                  justify="left").pack(anchor="w", pady=(8, 2))
        ttk.Label(c, text=f"Type: {self.app_type}    Name: {self.app_name}    "
                          f"Trial: {self.trial_days or 'none'}").pack(anchor="w")

        if self.injected:
            self._result_box({"ok": True, "msg": "License check added and files copied. "
                                                 "Click Next to verify.", "fix": None})
        else:
            ttk.Label(c, text="Ready. This will back up your original, insert the check, and "
                              "copy the license files next to your app.",
                      wraplength=460, justify="left").pack(anchor="w", pady=8)
            ttk.Button(c, text="Inject Licensing Now", command=self._do_inject).pack(anchor="w")
            self.passed[5] = False
            self._update_nav()

    def _do_inject(self):
        p = self.app_path
        if not (p and os.path.exists(p)):
            messagebox.showerror("Error", "Go back and choose a valid app file.")
            return
        src = open(p, encoding="utf-8").read()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(p, f"{p}.bak_{ts}")
        new_src = inject(src, self.app_type, self.app_name, self.trial_days, self.features, self.show_status)
        open(p, "w", encoding="utf-8").write(new_src)

        target = os.path.dirname(os.path.abspath(p))
        need = GUI_FILES  # popup activation needs dialog + help_tips for every app type
        missing = []
        for f in need:
            srcf = os.path.join(self.folder, f)
            if os.path.exists(srcf):
                if os.path.abspath(srcf) != os.path.join(target, f):
                    shutil.copy2(srcf, os.path.join(target, f))
            else:
                missing.append(f)
        warn = ""
        sdkf = os.path.join(target, "license_sdk.py")
        if os.path.exists(sdkf) and PLACEHOLDER in open(sdkf, encoding="utf-8").read():
            warn = "\n\n⚠ The copied license_sdk.py still has the placeholder key. " \
                   "Go to Step 3 and wire your public key, then re-inject."
        if missing:
            warn += "\n\n⚠ Missing in toolkit folder: " + ", ".join(missing)
        self.injected = True
        self.passed[5] = True
        manage = ""
        if self.app_type == "tkinter":
            manage = ("\n\nTo add a 'License' menu/button so users can check days left,\n"
                      "export, or request a transfer from inside your app:\n"
                      "    from license_dialog import open_license_window\n"
                      f"    open_license_window({self.app_name!r}, your_root_window)")
        else:
            manage = ("\n\nYour app now prints its license status on startup. To open a full\n"
                      "License Manager window from inside the app, call:\n"
                      "    from license_dialog import open_license_window\n"
                      f"    open_license_window({self.app_name!r})")
        messagebox.showinfo("Injected", f"Backup saved as {os.path.basename(p)}.bak_{ts}\n"
                                        f"License check added to your app.{warn}{manage}")
        self.render()

    # ---- step 7: verify ----
    def _render_verify_step(self):
        self._header("Step 7 — Make sure it works", "step_verify")
        c = self.content
        checks = []
        p = self.app_path
        src = open(p, encoding="utf-8").read() if (p and os.path.exists(p)) else ""
        checks.append(("License check is present in your app", BEGIN in src))
        target = os.path.dirname(os.path.abspath(p)) if p else self.folder
        sdkf = os.path.join(target, "license_sdk.py")
        checks.append(("license_sdk.py is next to your app", os.path.exists(sdkf)))
        key_ok = os.path.exists(sdkf) and PLACEHOLDER not in open(sdkf, encoding="utf-8").read()
        checks.append(("Public key is wired in (not placeholder)", key_ok))

        all_ok = all(ok for _, ok in checks)
        for label, ok in checks:
            row = ttk.Frame(c); row.pack(anchor="w", pady=2)
            ttk.Label(row, text="✓" if ok else "✗",
                      foreground="#080" if ok else "#c00",
                      font=("TkDefaultFont", 12, "bold")).pack(side="left", padx=(0, 6))
            ttk.Label(row, text=label).pack(side="left")

        self.passed[6] = all_ok

        if self.app_type == "console" and all_ok:
            ttk.Separator(c).pack(fill="x", pady=8)
            ttk.Label(c, text="Optional: run your app now and see its license status:",
                      justify="left").pack(anchor="w")
            ttk.Button(c, text="Run live test",
                       command=self._live_test).pack(anchor="w", pady=4)
            tip(c.winfo_children()[-1],
                "Runs your app once and shows the license line it prints on startup")
            self._live_out = ttk.Label(c, text="", justify="left", wraplength=460,
                                       foreground="#06c")
            self._live_out.pack(anchor="w", pady=(2, 0))

        ttk.Separator(c).pack(fill="x", pady=8)
        ttk.Label(c, text="Tip: users can manage their license (days left, export, transfer)\n"
                          "from inside the app — see the success notes after injecting.",
                  justify="left", foreground="#555").pack(anchor="w")

        if all_ok:
            ttk.Label(c, text="\nAll set. Click Finish.", foreground="#080").pack(anchor="w")
        self._update_steps()
        self._update_nav()

    def _live_test(self):
        p = self.app_path
        target = os.path.dirname(os.path.abspath(p))
        try:
            r = subprocess.run([sys.executable, p], cwd=target, input="\n",
                               capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()
            # find the status line the gate prints, e.g. "[MyApp] Trial — 14 day(s) remaining"
            status = ""
            for line in out.splitlines():
                if line.startswith(f"[{self.app_name}]"):
                    status = line
                    break
            if r.returncode != 0 and "License check failed" in out:
                verdict = "✓ App correctly BLOCKED (no license, no trial)."
                color = "#080"
            elif "Trial" in status:
                verdict = f"✓ App ran on the FREE TRIAL — licensing works.\n{status}"
                color = "#080"
            elif "Licensed" in status:
                verdict = f"✓ App ran with a LICENSE installed.\n{status}"
                color = "#080"
            elif r.returncode == 0:
                verdict = ("App ran (exit 0). If you enabled a trial, that's expected.\n"
                           + (status or "(no license status line printed — is "
                                        "'Show license status' on?)"))
                color = "#06c"
            else:
                verdict = f"App exited {r.returncode}.\n{out[:300]}"
                color = "#a60"
            self._live_out.config(text=verdict, foreground=color)
        except subprocess.TimeoutExpired:
            self._live_out.config(
                text="App didn't exit on its own (waiting for input or a window). "
                     "Skip the live test for GUI apps.", foreground="#a60")
        except Exception as e:
            self._live_out.config(text=f"Couldn't run: {e}", foreground="#c00")


# ======================================================================
# QUICK INJECT TAB (compact, for repeat use)
# ======================================================================
class QuickInject(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=12)
        r = 0
        hdr = ttk.Frame(self); hdr.grid(row=r, column=0, columnspan=3, sticky="ew")
        ttk.Label(hdr, text="Quick Inject", font=("TkDefaultFont", 12, "bold")).pack(side="left")
        help_button(hdr, "step_app", "Quick Inject").pack(side="right")

        r += 1
        ttk.Label(self, text="App main .py:").grid(row=r, column=0, sticky="w", pady=(8, 2))
        self.path_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.path_var, width=50).grid(row=r, column=1, sticky="w")
        ttk.Button(self, text="Browse…", command=self._browse).grid(row=r, column=2, padx=6)

        r += 1
        ttk.Label(self, text="App name:").grid(row=r, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.name_var, width=24).grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Label(self, text="Trial days (0=none):").grid(row=r, column=0, sticky="w")
        self.trial_var = tk.StringVar(value="14")
        ttk.Entry(self, textvariable=self.trial_var, width=8).grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Label(self, text="Require features:").grid(row=r, column=0, sticky="w")
        self.feat_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.feat_var, width=24).grid(row=r, column=1, sticky="w")

        r += 1
        self.status_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Show license status on startup",
                        variable=self.status_var).grid(row=r, column=0, columnspan=2, sticky="w")

        r += 1
        self.prev = tk.Text(self, width=74, height=8, wrap="none")
        self.prev.grid(row=r, column=0, columnspan=3, pady=8)

        r += 1
        ttk.Button(self, text="Refresh", command=self._refresh).grid(row=r, column=0, sticky="w")
        ttk.Button(self, text="Inject", command=self._inject).grid(row=r, column=1, sticky="w")

        for v in (self.path_var, self.name_var, self.trial_var, self.feat_var):
            v.trace_add("write", lambda *a: self._refresh())

    def _browse(self):
        p = filedialog.askopenfilename(filetypes=[("Python", "*.py"), ("All", "*.*")])
        if p:
            self.path_var.set(p)
            if not self.name_var.get():
                self.name_var.set(os.path.splitext(os.path.basename(p))[0])

    def _cfg(self):
        p = self.path_var.get().strip()
        src = open(p, encoding="utf-8").read() if (p and os.path.exists(p)) else ""
        t = detect_app_type(src) if src else "console"
        try:
            td = int(self.trial_var.get() or 0)
        except ValueError:
            td = 0
        feats = [f for f in self.feat_var.get().split(",") if f.strip()]
        return p, src, t, self.name_var.get().strip() or "MyApp", td, feats, bool(self.status_var.get())

    def _refresh(self):
        _, _, t, name, td, feats, ss = self._cfg()
        self.prev.delete("1.0", "end")
        self.prev.insert("1.0", gate_block(t, name, td, feats, ss))

    def _inject(self):
        p, src, t, name, td, feats, ss = self._cfg()
        if not (p and os.path.exists(p)):
            messagebox.showerror("Error", "Pick a valid .py file.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(p, f"{p}.bak_{ts}")
        open(p, "w", encoding="utf-8").write(inject(src, t, name, td, feats, ss))
        target = os.path.dirname(os.path.abspath(p))
        need = GUI_FILES  # popup activation needs dialog + help_tips for every app type
        for f in need:
            sf = os.path.join(HERE, f)
            if os.path.exists(sf) and os.path.abspath(sf) != os.path.join(target, f):
                shutil.copy2(sf, os.path.join(target, f))
        messagebox.showinfo("Done", f"Injected into {os.path.basename(p)} (backup saved).")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("License Injector — Setup Wizard")
        self.geometry("760x620")
        bar = ttk.Frame(self); bar.pack(fill="x", padx=10, pady=(8, 0))
        ttk.Label(bar, text="Add licensing to any Python app",
                  font=("TkDefaultFont", 11, "bold")).pack(side="left")
        ib = ttk.Button(bar, text="What is this?",
                        command=lambda: show_help(self, "intro", "About this wizard"))
        ib.pack(side="right")
        tip(ib, "Overview of the whole process")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=8)
        nb.add(Wizard(nb), text="Setup Wizard")
        nb.add(QuickInject(nb), text="Quick Inject")


if __name__ == "__main__":
    App().mainloop()
