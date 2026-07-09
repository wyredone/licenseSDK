# LicenseSDK

A self-contained software licensing system for Python apps. Ed25519-signed keys,
fuzzy hardware binding, free trials, encrypted backup/restore, hardware-transfer
reissue, tamper-evident logging, a popup License Manager, and a guided wizard that
injects licensing into any app for you.

Works offline-first. No server required.

---

## What's in here

**Ship these inside your app** (the injector copies them for you):
- `license_sdk.py` — core license check, hardware ID, trials, export/import, logging
- `license_dialog.py` — popup License Manager (activate / deactivate / import / export / transfer / status)
- `help_tips.py` — tooltips and "?" help buttons

**Vendor tools — keep private, never ship:**
- `license_generator.py` — creates your keys, issues customer license keys, reissues transfers, keeps history
- `license_injector.py` — guided wizard that adds licensing to any `main.py`
- `build_app.py` — compiles/obfuscates your app to a single-file executable

**Docs:** `docs/TUTORIAL.md` (start here), `docs/DOCUMENTATION.md` (developer reference), `docs/USER_MANUAL.md` (for your customers).

**Example:** `examples/demo_app.py`.

> ⚠ Never commit `vendor_keys.json` (your private signing key) or any generated
> `*.licx`, `*.key`, or `issued_licenses.json`. The included `.gitignore` blocks them.

---

## Quick start (vendor, one time)

```bash
python license_generator.py          # first run creates vendor_keys.json (back it up!)
# Settings tab -> Copy Public Key
```

Then run the wizard and let it wire the key + inject licensing:

```bash
python license_injector.py           # Setup Wizard: checks everything, then injects
```

Or add the gate by hand (top of your app):

```python
# console / CustomTkinter / PyQt / Tkinter all get the popup activation window:
from license_dialog import gui_require_license
lm, info = gui_require_license(app_name="MyApp", trial_days=14)
```

## Issuing a customer key

1. Customer clicks **Copy Request Code** in the app's License window (a `REQ-` code).
2. You paste it into the generator's **Generate** tab, pick duration + tier, click **Generate**.
3. Send back the `LIC-` key. They paste it into **Activate**. Done — it launches straight to the app every run after that.

## Build a protected executable

```bash
python build_app.py myapp.py --name MyApp --mode nuitka --gui --icon app.ico
```

---

## Security notes

- The **private** signing key lives only in `vendor_keys.json` on your machine.
  Apps ship the **public** key, so licenses can't be forged from app source.
- This is client-side licensing: it enforces expiry, tiers, trials, and hardware
  binding, and deters casual copying. For central revocation, per-key activation
  counts, and renewals, add an activation server (see `docs/DOCUMENTATION.md`).

## Requirements

Python 3.9+. `cryptography` and `requests` auto-install on first run (and get
bundled when you build with `build_app.py`).

## License

MIT — see `LICENSE`.
