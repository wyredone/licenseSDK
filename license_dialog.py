"""
license_dialog.py - License Manager window for license_sdk (v4).

Two roles, same window:
  • Activation gate (blocks an app until licensed):
        from license_dialog import gui_require_license
        lm, info = gui_require_license(app_name="MyApp", trial_days=14)

  • In-app manager (open any time from a menu/button — does NOT block):
        from license_dialog import open_license_window
        open_license_window("MyApp")              # standalone
        open_license_window("MyApp", root_window) # from an existing Tk app

The window has: live status, Activate, Deactivate, Import, Export, Transfer
Request, Copy Request Code / HWID, Start Trial, and View Logs.
"""
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from help_tips import tip
except ImportError:
    def tip(*a, **k):
        pass

from license_sdk import (LicenseManager, LicenseError, get_license_request,
                         license_summary, DEFAULT_TRIAL_DAYS)

HELP = {
    "status": ("This shows whether you're licensed, on a trial, or not yet activated, "
               "plus your plan, days remaining, and features. 'Time source' tells you "
               "if expiry was checked online or against your local clock (offline)."),
    "activate": ("Paste the license key your vendor sent (starts with LIC-) and click "
                 "Activate. The key is tied to this computer."),
    "request": ("Send your Request Code (starts with REQ-) to the vendor so they can "
                "create a key for your machine. It contains only a hardware fingerprint."),
    "deactivate": ("Removes the license from THIS computer so you can move it to another "
                   "one. You'll be offered an encrypted backup first. The app will need a "
                   "license (or trial) again afterward."),
    "backup": ("Export saves an encrypted backup (.licx) that restores only on this same "
               "machine. Import restores it. Use these for OS or app reinstalls."),
    "transfer": ("Changed computers or upgraded hardware? This creates a file to send to "
                 "the vendor, who reissues your license for the new machine with the same "
                 "expiration."),
    "trial": ("A one-time free trial on this computer. It cannot be restarted once used."),
    "logs": ("A record of license activity. The banner at the top says whether the log's "
             "integrity is intact (it's tamper-evident)."),
}


def _help(parent, key, title="Help"):
    text = HELP.get(key, "")
    w = tk.Toplevel(parent)
    w.title(title)
    w.resizable(False, False)
    tk.Label(w, text=text, justify="left", wraplength=420, padx=14, pady=12).pack()
    ttk.Button(w, text="Close", command=w.destroy).pack(pady=(0, 10))
    w.transient(parent)
    w.grab_set()


def _hbtn(parent, key, title="Help"):
    b = ttk.Button(parent, text="?", width=2,
                   command=lambda: _help(parent.winfo_toplevel(), key, title))
    tip(b, "Click for help")
    return b


class LicenseDialog(tk.Toplevel):
    def __init__(self, parent, app_name="App", on_valid=None, gating=True):
        super().__init__(parent)
        self.title(f"{app_name} — License Manager")
        self.geometry("600x560")
        self.resizable(False, False)
        self.lm = LicenseManager(app_name)
        self.app_name = app_name
        self.on_valid = on_valid
        self.gating = gating
        self.valid = False
        self.grab_set()

        pad = {"padx": 10, "pady": 4}

        # ---------- Status ----------
        sf = ttk.LabelFrame(self, text="Status")
        sf.pack(fill="x", **pad)
        top = ttk.Frame(sf); top.pack(fill="x")
        self.status_var = tk.StringVar()
        ttk.Label(top, textvariable=self.status_var, justify="left",
                  font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=8, pady=6)
        _hbtn(top, "status", "License Status").pack(side="right", padx=4)
        self.detail_var = tk.StringVar()
        ttk.Label(sf, textvariable=self.detail_var, justify="left",
                  foreground="#555").pack(anchor="w", padx=8, pady=(0, 6))

        ttk.Label(sf, text=f"Hardware ID:  {self.lm.hwid}", foreground="#555").pack(anchor="w", padx=8)
        idrow = ttk.Frame(sf); idrow.pack(anchor="w", padx=8, pady=(2, 8))
        b = ttk.Button(idrow, text="Copy Request Code", command=self._copy_req)
        b.pack(side="left", padx=(0, 6))
        tip(b, "Send this to the vendor to buy/receive a key")
        b = ttk.Button(idrow, text="Copy HWID", command=self._copy_hwid)
        b.pack(side="left", padx=(0, 6))
        tip(b, "Raw hardware fingerprint (usually use the Request Code instead)")
        _hbtn(idrow, "request", "Request Code").pack(side="left")

        # ---------- Activate ----------
        af = ttk.LabelFrame(self, text="Activate")
        af.pack(fill="x", **pad)
        arow = ttk.Frame(af); arow.pack(fill="x")
        ttk.Label(arow, text="Paste your license key (LIC-…):").pack(side="left", padx=8, pady=(6, 0))
        _hbtn(arow, "activate", "Activate").pack(side="right", padx=4)
        self.key_txt = tk.Text(af, width=64, height=3, wrap="char")
        self.key_txt.pack(padx=8, pady=6)
        tip(self.key_txt, "The whole LIC- key from the vendor")
        ttk.Button(af, text="Activate License", command=self._activate).pack(anchor="w", padx=8, pady=(0, 8))

        # ---------- Manage ----------
        mf = ttk.LabelFrame(self, text="Manage")
        mf.pack(fill="x", **pad)
        grid = ttk.Frame(mf); grid.pack(anchor="w", padx=8, pady=8)

        def cell(r, c, text, cmd, tiptext, helpkey):
            sub = ttk.Frame(grid)
            sub.grid(row=r, column=c, sticky="w", padx=(0, 16), pady=3)
            btn = ttk.Button(sub, text=text, width=18, command=cmd)
            btn.pack(side="left")
            tip(btn, tiptext)
            if helpkey:
                _hbtn(sub, helpkey, text).pack(side="left", padx=(4, 0))
            return btn

        self.trial_btn = cell(0, 0, "Start Free Trial", self._start_trial,
                              "One-time free trial on this computer", "trial")
        cell(0, 1, "Deactivate", self._deactivate,
             "Remove the license from this PC so you can move it", "deactivate")
        cell(1, 0, "Export Backup", self._export,
             "Save an encrypted backup (restores on this PC only)", "backup")
        cell(1, 1, "Import Backup", self._import,
             "Restore a previously exported backup", "backup")
        cell(2, 0, "Transfer Request", self._transfer,
             "Move your license to a new PC / new hardware", "transfer")
        cell(2, 1, "View Logs", self._logs,
             "License activity with tamper-detection status", "logs")

        # ---------- Footer ----------
        foot = ttk.Frame(self)
        foot.pack(fill="x", **pad)
        self.continue_btn = ttk.Button(foot, text="Continue", command=self._continue)
        self.continue_btn.pack(side="right")
        self.close_btn = ttk.Button(foot, text="Close", command=self._on_close)
        self.close_btn.pack(side="right", padx=6)

        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- status ----
    def _refresh(self):
        self.trial_btn.state(["!disabled"])
        ok, info = self.lm.validate()
        if not ok:
            t_ok, t_info = self.lm.validate_trial()
            if t_ok:
                ok, info = t_ok, t_info
        self.valid = ok

        if ok:
            self.status_var.set("✔  " + license_summary(info))
            tt = "online" if info.get("time_trusted") else "local clock (offline)"
            extra = f"Time source: {tt}"
            if info.get("offline_days_used") is not None:
                extra += f" · grace {info['offline_days_used']}/{info['offline_grace_days']}d"
            self.detail_var.set(extra)
            self.trial_btn.state(["disabled"])
        else:
            self.status_var.set("✘  Not licensed")
            self.detail_var.set(info.get("error", ""))
            ts = self.lm.trial_status()
            if ts["state"] != "available":
                self.trial_btn.state(["disabled"])

        # gating: Continue only enabled when valid; non-gating hides Continue
        if self.gating:
            self.continue_btn.state(["!disabled"] if self.valid else ["disabled"])
            self.close_btn.pack_forget()
        else:
            self.continue_btn.pack_forget()

    # ---- actions ----
    def _copy_hwid(self):
        self.clipboard_clear(); self.clipboard_append(self.lm.hwid)

    def _copy_req(self):
        self.clipboard_clear(); self.clipboard_append(get_license_request())
        messagebox.showinfo("Copied", "Request code copied. Send it to the vendor to "
                            "receive your license key.", parent=self)

    def _start_trial(self):
        try:
            self.lm.start_trial(DEFAULT_TRIAL_DAYS)
        except Exception as e:
            messagebox.showerror("Trial", str(e), parent=self)
        self._refresh()

    def _activate(self):
        key = self.key_txt.get("1.0", "end").strip()
        if not key:
            return
        try:
            self.lm.install_license(key)
        except LicenseError as e:
            messagebox.showerror("Invalid Key", str(e), parent=self)
            return
        self.key_txt.delete("1.0", "end")
        self._refresh()
        if self.valid:
            messagebox.showinfo("Activated", "License activated successfully.", parent=self)

    def _deactivate(self):
        if not self.lm.load_license():
            messagebox.showinfo("Nothing to do", "No license is installed on this computer.",
                                parent=self)
            return
        if not messagebox.askyesno(
                "Deactivate license",
                "Remove the license from THIS computer so it can be moved elsewhere?\n\n"
                "The app will need a license (or trial) again afterward.", parent=self):
            return
        backup = None
        if messagebox.askyesno("Backup first?",
                               "Save an encrypted backup of the license before removing it?\n"
                               "(Recommended — lets you restore it on this machine.)",
                               parent=self):
            backup = filedialog.asksaveasfilename(
                defaultextension=".licx", initialfile="license_backup.licx",
                filetypes=[("License backup", "*.licx")], parent=self)
        try:
            self.lm.deactivate_license(export_path=backup or None)
            msg = "License removed from this computer."
            if backup:
                msg += f"\nBackup saved to:\n{backup}"
            messagebox.showinfo("Deactivated", msg, parent=self)
        except LicenseError as e:
            messagebox.showerror("Deactivate failed", str(e), parent=self)
        self._refresh()

    def _export(self):
        if not self.lm.load_license():
            messagebox.showinfo("Nothing to export", "No license is installed.", parent=self)
            return
        p = filedialog.asksaveasfilename(defaultextension=".licx", initialfile="license_export.licx",
                                         filetypes=[("License export", "*.licx")], parent=self)
        if not p:
            return
        try:
            self.lm.export_license(p)
            messagebox.showinfo("Exported", f"Saved to {p}", parent=self)
        except LicenseError as e:
            messagebox.showerror("Export Failed", str(e), parent=self)

    def _import(self):
        p = filedialog.askopenfilename(filetypes=[("License export", "*.licx"), ("All", "*.*")],
                                       parent=self)
        if not p:
            return
        try:
            ok, info = self.lm.import_license(p)
            self._refresh()
            if not ok:
                messagebox.showwarning("Imported", f"Imported but invalid: {info.get('error')}",
                                       parent=self)
            else:
                messagebox.showinfo("Imported", "License restored successfully.", parent=self)
        except LicenseError as e:
            messagebox.showerror("Import Failed", str(e), parent=self)

    def _transfer(self):
        if not self.lm.load_license():
            messagebox.showinfo("No license", "Install a license before requesting a transfer.",
                                parent=self)
            return
        p = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="transfer_request.txt",
                                         filetypes=[("Transfer request", "*.txt")], parent=self)
        if not p:
            return
        try:
            self.lm.create_transfer_request(p)
            messagebox.showinfo("Transfer Request",
                                f"Saved to {p}\n\nSend this file to the vendor to reissue "
                                "your license for this machine.", parent=self)
        except LicenseError as e:
            messagebox.showerror("Failed", str(e), parent=self)

    def _logs(self):
        w = tk.Toplevel(self)
        w.title("License Logs")
        w.geometry("720x420")
        t = tk.Text(w, wrap="none")
        t.pack(fill="both", expand=True)
        v = self.lm.verify_logs()
        head = ("[CHAIN OK — log integrity verified]\n\n" if v["ok"] else
                f"[CHAIN BROKEN at line {v['first_bad_line']} — log was edited or truncated]\n\n")
        t.insert("1.0", head + self.lm.review_logs(200))
        t.config(state="disabled")

    def _continue(self):
        if self.valid:
            self.destroy()
            if self.on_valid:
                self.on_valid()
        else:
            messagebox.showwarning("Not Licensed", "A valid license or trial is required.",
                                   parent=self)

    def _on_close(self):
        self.destroy()


# ----------------------------------------------------------------------
# ENTRY POINTS
# ----------------------------------------------------------------------
def gui_require_license(app_name="App", exit_on_fail=True, trial_days=None):
    """Activation gate: blocks with the manager window until licensed (or closed)."""
    lm = LicenseManager(app_name)
    ok, info = lm.validate()
    if not ok and trial_days:
        if lm.trial_status()["state"] == "available":
            try:
                lm.start_trial(trial_days)
            except LicenseError:
                pass
        ok, info = lm.validate_trial()
    if ok:
        return lm, info
    root = tk.Tk()
    root.withdraw()
    dlg = LicenseDialog(root, app_name=app_name, gating=True)
    root.wait_window(dlg)
    root.destroy()
    ok, info = lm.validate()
    if not ok:
        ok, info = lm.validate_trial()
    if not ok and exit_on_fail:
        sys.exit(1)
    return lm, info


def open_license_window(app_name="App", parent=None):
    """In-app manager: open any time from a menu/button. Does not block or exit."""
    if parent is not None:
        LicenseDialog(parent, app_name=app_name, gating=False)
        return
    root = tk.Tk()
    root.withdraw()
    dlg = LicenseDialog(root, app_name=app_name, gating=False)
    root.wait_window(dlg)
    root.destroy()


if __name__ == "__main__":
    open_license_window("DialogTest")
