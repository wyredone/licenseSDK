"""
help_tips.py - Hover tooltips and "?" help buttons for Tkinter apps.

Usage:
    from help_tips import tip, help_btn
    tip(entry_widget, "Paste the customer's REQ- code here")
    help_btn(parent_frame, "generator_generate").pack(side="left")
"""
import tkinter as tk
from tkinter import ttk


class Tooltip:
    """Hover tooltip. Appears after a short delay, follows standard styling."""

    def __init__(self, widget, text, delay=500, wrap=320):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wrap = wrap
        self._id = None
        self._tw = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None

    def _show(self):
        if self._tw:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tw = tk.Toplevel(self.widget)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tw, text=self.text, justify="left", wraplength=self.wrap,
                 background="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=4).pack()

    def _hide(self, _=None):
        self._cancel()
        if self._tw:
            self._tw.destroy()
            self._tw = None


def tip(widget, text, **kw):
    """Attach a hover tooltip to any widget."""
    return Tooltip(widget, text, **kw)


# ----------------------------------------------------------------------
# HELP TOPICS (shown by "?" buttons)
# ----------------------------------------------------------------------
HELP = {
    "generator_generate": (
        "Generating a license\n\n"
        "1. Ask the customer for their License Request Code (they get it from the\n"
        "   app's License window — 'Copy License Request Code' — or by running\n"
        "   'python license_sdk.py'). A raw Hardware ID also works, but exact-match\n"
        "   only (no tolerance for hardware changes).\n"
        "2. Paste it into 'HWID or REQ- code'.\n"
        "3. Pick Duration and Tier. Tier auto-fills the feature list; choose Custom\n"
        "   to type your own comma-separated features.\n"
        "4. Click Generate, then Copy or Save to File and send the key to the customer.\n\n"
        "Every key is recorded in the History tab."
    ),
    "generator_transfer": (
        "Transfer / Reissue (hardware upgrade)\n\n"
        "When a customer changes too much hardware, their app makes a Transfer\n"
        "Request file. Paste or load that XFER- blob here and click Verify & Reissue.\n\n"
        "The tool verifies the embedded old license signature, shows old vs new\n"
        "hardware, and reissues a key for the new machine with the SAME expiration,\n"
        "tier, and features. Reissues are logged in History as kind 'reissue'."
    ),
    "generator_history": (
        "History\n\n"
        "Every issued and reissued key is recorded in issued_licenses.json next to\n"
        "this program. Select a row and 'Copy Selected Key' to resend a lost key.\n"
        "'Export CSV' produces a spreadsheet-ready file with all columns including\n"
        "the full key."
    ),
    "generator_settings": (
        "Keys & Security\n\n"
        "vendor_keys.json holds your Ed25519 signing keypair. It is created\n"
        "automatically on first run.\n\n"
        "• BACK IT UP — without it you cannot issue keys that existing installs accept.\n"
        "• KEEP IT PRIVATE — anyone with it can mint licenses for your apps.\n"
        "• NEVER ship this program or vendor_keys.json to customers.\n\n"
        "Copy the public key and paste it into PUBLIC_KEY_HEX at the top of\n"
        "license_sdk.py before distributing your app."
    ),
    "dialog_status": (
        "License status\n\n"
        "LICENSED — key is valid for this machine; tier, features, and days\n"
        "remaining are shown.\n"
        "TRIAL — running on the one-time free trial.\n"
        "NOT LICENSED — see the error text; usually you need to activate.\n\n"
        "Time source 'online' means expiry was checked against internet time.\n"
        "'LOCAL CLOCK' means you're offline — the app keeps working for a grace\n"
        "period (shown), then needs an internet connection once to revalidate."
    ),
    "dialog_activate": (
        "Activating\n\n"
        "1. Click 'Copy License Request Code' and send it to the vendor.\n"
        "2. The vendor sends back a key starting with LIC-.\n"
        "3. Paste the whole key in the box and click Activate License.\n\n"
        "The key is bound to this computer's hardware."
    ),
    "dialog_tools": (
        "Tools\n\n"
        "Export License — saves an encrypted backup (.licx) of your key. It can\n"
        "only be imported on this same machine (e.g. after reinstalling Windows\n"
        "or the app).\n\n"
        "Import License — restores a previously exported .licx backup.\n\n"
        "Transfer Request — use after a major hardware upgrade or when moving to\n"
        "a new PC. It creates a file to send to the vendor, who reissues your\n"
        "license for the new hardware with the same expiration.\n\n"
        "View Logs — shows license activity. The header reports whether the log's\n"
        "integrity chain is intact."
    ),
}


def show_help(parent, topic_key, title="Help"):
    """Open a help window for a topic from HELP."""
    text = HELP.get(topic_key, "No help available for this topic.")
    w = tk.Toplevel(parent)
    w.title(title)
    w.resizable(False, False)
    tk.Label(w, text=text, justify="left", wraplength=520,
             padx=14, pady=12).pack()
    ttk.Button(w, text="Close", command=w.destroy).pack(pady=(0, 10))
    w.transient(parent)
    w.grab_set()


def help_btn(parent, topic_key, title="Help"):
    """Small '?' button that opens the given help topic."""
    b = ttk.Button(parent, text="?", width=2,
                   command=lambda: show_help(parent.winfo_toplevel(), topic_key, title))
    tip(b, "Click for help")
    return b
