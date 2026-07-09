"""
license_generator.py - VENDOR-SIDE license generator (keep private, do not ship).

v2: Ed25519 keypair (auto-created on first run -> vendor_keys.json next to this
script). Copy the PUBLIC key from the Settings tab into license_sdk.PUBLIC_KEY_HEX.
Generates tiered licenses with feature flags, verifies transfer requests,
reissues keys, keeps issued-license history with CSV export.
"""

import subprocess, sys
def _ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
_ensure("cryptography")

import os
import csv
import json
import base64
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
try:
    from help_tips import tip, help_btn
except ImportError:
    def tip(*a, **k): pass
    def help_btn(parent, *a, **k): return ttk.Frame(parent)
from datetime import datetime, timezone, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(_DIR, "vendor_keys.json")
HISTORY_PATH = os.path.join(_DIR, "issued_licenses.json")
KEY_PREFIX = "LIC-"

DURATIONS = {
    "30 days":  timedelta(days=30),
    "90 days":  timedelta(days=90),
    "6 months": timedelta(days=182),
    "1 year":   timedelta(days=365),
    "Lifetime": None,
}

TIERS = {
    "Basic":      [],
    "Pro":        ["pro", "export"],
    "Enterprise": ["pro", "export", "api", "multiuser"],
    "Custom":     [],
}

def _b64e(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _b64d(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

# ----------------------------------------------------------------------
# KEYPAIR
# ----------------------------------------------------------------------
def load_or_create_keys():
    """Returns (private_key, public_hex, just_created: bool)."""
    if os.path.exists(KEYS_PATH):
        d = json.load(open(KEYS_PATH))
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(d["private"]))
        return priv, d["public"], False
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()).hex()
    pub_hex = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    json.dump({"private": priv_hex, "public": pub_hex,
               "created": datetime.now(timezone.utc).isoformat()},
              open(KEYS_PATH, "w"), indent=1)
    try:
        os.chmod(KEYS_PATH, 0o600)
    except Exception:
        pass
    return priv, pub_hex, True

PRIVATE_KEY, PUBLIC_KEY_HEX, KEYS_JUST_CREATED = load_or_create_keys()

def _sign(payload_b64: str) -> str:
    return _b64e(PRIVATE_KEY.sign(payload_b64.encode()))

def _verify_license_sig(key: str) -> dict:
    if not key.startswith(KEY_PREFIX):
        raise ValueError("Malformed license")
    pb, sig = key[len(KEY_PREFIX):].rsplit(".", 1)
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    try:
        pub.verify(_b64d(sig), pb.encode())
    except InvalidSignature:
        raise ValueError("License signature invalid")
    return json.loads(_b64d(pb))

# ----------------------------------------------------------------------
# GENERATION
# ----------------------------------------------------------------------
def parse_request_code(text: str):
    """Accepts a REQ- code or a raw HWID. Returns (hwid, hw_components_or_None)."""
    text = text.strip()
    if text.startswith("REQ-"):
        d = json.loads(_b64d(text[4:]))
        return d["hwid"].strip().upper(), d.get("hw") or None
    return text.upper(), None

def generate_license(hwid_or_req: str, duration_label: str, tier: str = "Basic",
                     features=None, customer: str = "") -> str:
    hwid, hw = parse_request_code(hwid_or_req)
    now = datetime.now(timezone.utc)
    delta = DURATIONS[duration_label]
    payload = {
        "ver": 3,
        "hwid": hwid,
        "hw": hw,
        "issued": now.isoformat(),
        "expires": (now + delta).isoformat() if delta else None,
        "duration": duration_label,
        "tier": tier,
        "features": sorted({f.strip().lower() for f in (features or []) if f.strip()}),
    }
    if hw is None:
        payload.pop("hw")
    b = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    key = f"{KEY_PREFIX}{b}.{_sign(b)}"
    _record_issue(payload, key, customer, kind="issue")
    return key

def _record_issue(payload, key, customer="", kind="issue"):
    try:
        hist = json.load(open(HISTORY_PATH)) if os.path.exists(HISTORY_PATH) else []
    except Exception:
        hist = []
    hist.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "customer": customer,
        "hwid": payload["hwid"],
        "tier": payload.get("tier", ""),
        "features": ",".join(payload.get("features", [])),
        "duration": payload["duration"],
        "issued": payload["issued"],
        "expires": payload["expires"] or "lifetime",
        "key": key,
    })
    json.dump(hist, open(HISTORY_PATH, "w"), indent=1)

def load_history():
    try:
        return json.load(open(HISTORY_PATH)) if os.path.exists(HISTORY_PATH) else []
    except Exception:
        return []

# ----------------------------------------------------------------------
# TRANSFER
# ----------------------------------------------------------------------
def verify_transfer_request(blob: str) -> dict:
    blob = blob.strip()
    if not blob.startswith("XFER-"):
        raise ValueError("Not a transfer request")
    req = json.loads(_b64d(blob[5:]))
    req["old_payload"] = _verify_license_sig(req["old_license"])
    return req

def reissue_license(req: dict, customer: str = "") -> str:
    old = req["old_payload"]
    now = datetime.now(timezone.utc)
    payload = {
        "ver": 3,
        "hwid": req["new_hwid"].strip().upper(),
        "issued": now.isoformat(),
        "expires": old["expires"],
        "duration": old["duration"] + " (transferred)",
        "tier": old.get("tier", "Standard"),
        "features": old.get("features", []),
    }
    if req.get("new_hw"):
        payload["hw"] = req["new_hw"]
    b = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    key = f"{KEY_PREFIX}{b}.{_sign(b)}"
    _record_issue(payload, key, customer, kind="reissue")
    return key


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class GeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("License Generator v3 (Ed25519, fuzzy HW)")
        self.geometry("800x600")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._nb = nb

        # ---------------- Tab 1: Generate ----------------
        f1 = ttk.Frame(nb, padding=12)
        nb.add(f1, text="Generate License")

        help_btn(f1, "generator_generate", "Help — Generate License").grid(row=0, column=2, sticky="ne")

        ttk.Label(f1, text="Customer (optional):").grid(row=0, column=0, sticky="w")
        self.cust_var = tk.StringVar()
        e_cust = ttk.Entry(f1, textvariable=self.cust_var, width=50)
        e_cust.grid(row=0, column=1, pady=4, sticky="w")
        tip(e_cust, "Name or email for your records only — not embedded in the key. Saved in History.")

        ttk.Label(f1, text="HWID or REQ- code:").grid(row=1, column=0, sticky="w")
        self.hwid_var = tk.StringVar()
        e_hwid = ttk.Entry(f1, textvariable=self.hwid_var, width=50)
        e_hwid.grid(row=1, column=1, pady=4, sticky="w")
        tip(e_hwid, "Paste the customer's REQ- request code (preferred — enables fuzzy "
                    "hardware matching) or their raw 32-char Hardware ID (exact match only).")

        ttk.Label(f1, text="Duration:").grid(row=2, column=0, sticky="w")
        self.dur_var = tk.StringVar(value="1 year")
        cb_dur = ttk.Combobox(f1, textvariable=self.dur_var, values=list(DURATIONS),
                              state="readonly", width=15)
        cb_dur.grid(row=2, column=1, pady=4, sticky="w")
        tip(cb_dur, "License length from today. Lifetime never expires.")

        ttk.Label(f1, text="Tier:").grid(row=3, column=0, sticky="w")
        self.tier_var = tk.StringVar(value="Pro")
        cb = ttk.Combobox(f1, textvariable=self.tier_var, values=list(TIERS),
                          state="readonly", width=15)
        cb.grid(row=3, column=1, pady=4, sticky="w")
        cb.bind("<<ComboboxSelected>>", self._tier_changed)
        tip(cb, "Tier label embedded in the key. Picking a tier auto-fills its feature "
                "flags below; pick Custom to type your own.")

        ttk.Label(f1, text="Features (comma-sep):").grid(row=4, column=0, sticky="w")
        self.feat_var = tk.StringVar(value=",".join(TIERS["Pro"]))
        e_feat = ttk.Entry(f1, textvariable=self.feat_var, width=50)
        e_feat.grid(row=4, column=1, pady=4, sticky="w")
        tip(e_feat, "Comma-separated feature flags the app can check with "
                    "lm.has_feature('name'). Lowercased and de-duplicated automatically.")

        ttk.Button(f1, text="Generate", command=self.on_generate).grid(row=5, column=1, sticky="w", pady=8)

        ttk.Label(f1, text="License Key:").grid(row=6, column=0, sticky="nw")
        self.out_txt = tk.Text(f1, width=70, height=7, wrap="char")
        self.out_txt.grid(row=6, column=1, pady=4)

        ttk.Label(f1, text="Details:").grid(row=7, column=0, sticky="nw")
        self.detail_var = tk.StringVar()
        ttk.Label(f1, textvariable=self.detail_var, justify="left").grid(row=7, column=1, sticky="w")

        btns = ttk.Frame(f1)
        btns.grid(row=8, column=1, sticky="w", pady=8)
        ttk.Button(btns, text="Copy", command=self.on_copy).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Save to File", command=self.on_save).pack(side="left")

        # ---------------- Tab 2: Transfer / Reissue ----------------
        f2 = ttk.Frame(nb, padding=12)
        nb.add(f2, text="Transfer / Reissue")

        hrow2 = ttk.Frame(f2); hrow2.pack(anchor="e")
        help_btn(hrow2, "generator_transfer", "Help — Transfer / Reissue").pack()
        ttk.Label(f2, text="Paste XFER- request blob (or Load File):").pack(anchor="w")
        self.xfer_txt = tk.Text(f2, width=88, height=6, wrap="char")
        self.xfer_txt.pack(pady=4)
        row = ttk.Frame(f2); row.pack(anchor="w", pady=4)
        ttk.Button(row, text="Load File", command=self.on_load_xfer).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Verify && Reissue", command=self.on_reissue).pack(side="left")

        ttk.Label(f2, text="Reissued Key:").pack(anchor="w", pady=(8, 0))
        self.reissue_txt = tk.Text(f2, width=88, height=6, wrap="char")
        self.reissue_txt.pack(pady=4)
        ttk.Button(f2, text="Copy Reissued Key", command=self.on_copy_reissue).pack(anchor="w")

        # ---------------- Tab 3: History ----------------
        f3 = ttk.Frame(nb, padding=12)
        nb.add(f3, text="History")

        hrow3 = ttk.Frame(f3); hrow3.pack(anchor="e")
        help_btn(hrow3, "generator_history", "Help — History").pack()
        cols = ("timestamp", "kind", "customer", "hwid", "tier", "duration", "expires")
        self.tree = ttk.Treeview(f3, columns=cols, show="headings", height=16)
        widths = {"timestamp": 140, "kind": 55, "customer": 110, "hwid": 180,
                  "tier": 70, "duration": 85, "expires": 110}
        for c in cols:
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True)

        hb = ttk.Frame(f3); hb.pack(anchor="w", pady=6)
        ttk.Button(hb, text="Refresh", command=self.load_tree).pack(side="left", padx=(0, 6))
        ttk.Button(hb, text="Copy Selected Key", command=self.on_copy_hist_key).pack(side="left", padx=(0, 6))
        ttk.Button(hb, text="Export CSV", command=self.on_export_csv).pack(side="left")

        # ---------------- Tab 4: Settings / Keys ----------------
        f4 = ttk.Frame(nb, padding=12)
        nb.add(f4, text="Settings")

        hrow4 = ttk.Frame(f4); hrow4.pack(anchor="e")
        help_btn(hrow4, "generator_settings", "Help — Keys & Security").pack()
        ttk.Label(f4, text="SDK Public Key (paste into license_sdk.PUBLIC_KEY_HEX):",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.pub_txt = tk.Text(f4, width=88, height=3, wrap="char")
        self.pub_txt.pack(pady=4)
        self.pub_txt.insert("1.0", PUBLIC_KEY_HEX)
        self.pub_txt.config(state="disabled")
        ttk.Button(f4, text="Copy Public Key", command=self.on_copy_pub).pack(anchor="w", pady=4)

        ttk.Label(f4, text=f"\nKeypair file: {KEYS_PATH}\n"
                           "BACK THIS FILE UP and keep it private — losing it means you\n"
                           "cannot issue keys for existing installs; leaking it means\n"
                           "anyone can generate licenses.",
                  justify="left", foreground="#b00").pack(anchor="w")

        self.load_tree()

        # First-run guidance: show the welcome/setup dialog after the window appears
        if KEYS_JUST_CREATED:
            self.after(300, self._first_run_welcome)

    # ---- first-run guided setup ----
    def _first_run_welcome(self):
        self._nb.select(3)  # jump to Settings tab where the public key lives
        win = tk.Toplevel(self)
        win.title("Welcome — First-Time Setup")
        win.geometry("560x440")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="✔  Your signing keys were just created",
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Saved to:  {KEYS_PATH}", foreground="#555").pack(anchor="w", pady=(2, 10))

        msg = (
            "This file (vendor_keys.json) is your private signing key — it is what\n"
            "proves a license came from you. Two rules:\n\n"
            "   •  BACK IT UP.  Lose it and you can't issue keys your existing\n"
            "      customers will accept.\n"
            "   •  KEEP IT PRIVATE.  Never email it, never ship it, never put it\n"
            "      in your app. Anyone who has it can forge your licenses.\n\n"
            "Next step — connect this generator to your app:\n\n"
            "   1.  Click 'Copy Public Key' below.\n"
            "   2.  Open license_sdk.py in your app folder.\n"
            "   3.  Replace the PASTE-PUBLIC-KEY line near the top with it.\n"
            "   4.  Save. That license_sdk.py is the file you ship inside your app.\n\n"
            "The public key is safe to share — only the private key is secret.\n\n"
            "After that you're ready: when a customer sends you a REQ- code, paste\n"
            "it into the Generate License tab to make their key."
        )
        ttk.Label(frm, text=msg, justify="left").pack(anchor="w")

        self._welcome_status = ttk.Label(frm, text="", foreground="#080")
        self._welcome_status.pack(anchor="w", pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.pack(anchor="w", pady=(12, 0))

        def copy_pub():
            self.clipboard_clear()
            self.clipboard_append(PUBLIC_KEY_HEX)
            self._welcome_status.config(
                text="Public key copied — now paste it into license_sdk.py (PUBLIC_KEY_HEX).")

        ttk.Button(btns, text="Copy Public Key", command=copy_pub).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Got it — Close", command=win.destroy).pack(side="left")
    def _tier_changed(self, _=None):
        t = self.tier_var.get()
        if t != "Custom":
            self.feat_var.set(",".join(TIERS[t]))

    def on_generate(self):
        hwid = self.hwid_var.get().strip()
        if not hwid:
            messagebox.showerror("Error", "Enter a Hardware ID")
            return
        feats = self.feat_var.get().split(",")
        key = generate_license(hwid, self.dur_var.get(), self.tier_var.get(),
                               feats, self.cust_var.get().strip())
        self.out_txt.delete("1.0", "end")
        self.out_txt.insert("1.0", key)
        payload = json.loads(_b64d(key[len(KEY_PREFIX):].rsplit(".", 1)[0]))
        exp = payload["expires"] or "Never (lifetime)"
        self.detail_var.set(f"Issued: {payload['issued']}\nExpires: {exp}\n"
                            f"Tier: {payload['tier']}  Features: {', '.join(payload['features']) or '(none)'}")
        self.load_tree()

    def on_copy(self):
        key = self.out_txt.get("1.0", "end").strip()
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)

    def on_copy_pub(self):
        self.clipboard_clear()
        self.clipboard_append(PUBLIC_KEY_HEX)

    def on_save(self):
        key = self.out_txt.get("1.0", "end").strip()
        if not key:
            return
        p = filedialog.asksaveasfilename(defaultextension=".key",
                                         initialfile="license.key",
                                         filetypes=[("License key", "*.key"), ("All", "*.*")])
        if p:
            open(p, "w").write(key)

    def on_load_xfer(self):
        p = filedialog.askopenfilename(filetypes=[("Transfer request", "*.*")])
        if p:
            self.xfer_txt.delete("1.0", "end")
            self.xfer_txt.insert("1.0", open(p).read().strip())

    def on_reissue(self):
        blob = self.xfer_txt.get("1.0", "end").strip()
        try:
            req = verify_transfer_request(blob)
        except Exception as e:
            messagebox.showerror("Invalid", str(e))
            return
        old = req["old_payload"]
        msg = (f"Old HWID: {old['hwid']}\nNew HWID: {req['new_hwid']}\n"
               f"Tier: {old.get('tier','')}\nDuration: {old['duration']}\n"
               f"Original expiry: {old['expires'] or 'Lifetime'}\n\n"
               "Reissue license to new hardware with SAME expiration?")
        if not messagebox.askyesno("Confirm Reissue", msg):
            return
        key = reissue_license(req, self.cust_var.get().strip())
        self.reissue_txt.delete("1.0", "end")
        self.reissue_txt.insert("1.0", key)
        self.load_tree()

    def on_copy_reissue(self):
        key = self.reissue_txt.get("1.0", "end").strip()
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)

    # ---- history ----
    def load_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._hist = load_history()
        for i, h in enumerate(reversed(self._hist)):
            self.tree.insert("", "end", iid=str(i), values=(
                h["timestamp"][:19], h["kind"], h.get("customer", ""),
                h["hwid"], h.get("tier", ""), h["duration"],
                h["expires"][:10] if h["expires"] != "lifetime" else "lifetime"))

    def on_copy_hist_key(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = len(self._hist) - 1 - int(sel[0])
        self.clipboard_clear()
        self.clipboard_append(self._hist[idx]["key"])

    def on_export_csv(self):
        hist = load_history()
        if not hist:
            messagebox.showinfo("Empty", "No history to export")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         initialfile="issued_licenses.csv",
                                         filetypes=[("CSV", "*.csv")])
        if not p:
            return
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "kind", "customer", "hwid",
                                              "tier", "features", "duration", "issued",
                                              "expires", "key"])
            w.writeheader()
            w.writerows(hist)
        messagebox.showinfo("Exported", f"Saved to {p}")


if __name__ == "__main__":
    GeneratorApp().mainloop()
