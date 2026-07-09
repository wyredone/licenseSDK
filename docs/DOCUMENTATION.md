# Licensing SDK — Developer Documentation

A self-contained, offline-capable software licensing system for Python apps.
Ed25519-signed keys, fuzzy hardware binding, trials, encrypted backup/restore,
hardware-transfer reissue, tamper-evident logging, and a one-command build step.

---

## 1. Files

| File | Ships to customer? | Purpose |
|------|--------------------|---------|
| `license_sdk.py` | **Yes** | Core SDK. Validation, hardware ID, trials, export/import, logging. |
| `license_dialog.py` | Yes (GUI apps) | Tkinter activation/status window. |
| `help_tips.py` | Yes (GUI apps) | Hover tooltips + "?" help buttons used by the dialog. |
| `demo_app.py` | — | Example integration. |
| `build_app.py` | **No** | Compiles/obfuscates your app to a single-file executable. |
| `license_generator.py` | **NEVER** | Vendor tool. Creates keys, reissues transfers, keeps history. |
| `vendor_keys.json` | **NEVER** | Your Ed25519 private signing key. Created on first generator run. |

> **Golden rule:** the customer gets `license_sdk.py` (+ dialog/help for GUI) embedded
> in your app. They never receive `license_generator.py` or `vendor_keys.json`.

---

## 2. One-time setup

1. Run the generator once to create your keypair:
   ```
   python license_generator.py
   ```
   This creates `vendor_keys.json` next to the script. **Back it up. Keep it private.**

2. Open the generator's **Settings** tab, click **Copy Public Key**.

3. Paste it into `license_sdk.py`:
   ```python
   PUBLIC_KEY_HEX = "the-64-hex-char-key-you-copied"
   ```

4. Ship `license_sdk.py` (with your public key baked in) inside your app.

The private key never leaves your machine, so even a customer with full SDK
source cannot forge a key.

---

## 3. Integrating into an app

### Console app — one line
```python
from license_sdk import require_license
lm, info = require_license(app_name="MyApp")
# ... rest of app only runs if licensed ...
```

### With a free trial
```python
lm, info = require_license(app_name="MyApp", trial_days=14)
```

### GUI app (Tkinter) — shows an activation window
```python
from license_dialog import gui_require_license
lm, info = gui_require_license(app_name="MyApp", trial_days=14)
```

### Gating premium features
```python
lm, info = require_license(app_name="MyApp")
if lm.has_feature("export"):
    enable_export()

# or hard-require at startup:
lm, info = require_license(app_name="MyApp", require_features=["pro"])

# or raise on demand:
lm.require_feature("api")   # raises LicenseError if missing
```

`app_name` namespaces all stored data (license, state, logs, per-app trial), so
multiple licensed apps coexist cleanly.

---

## 4. The customer activation flow

1. Customer installs/launches your app. No license → activation prompt (console
   `input()` or the dialog window).
2. Customer copies their **License Request Code** (`REQ-…`):
   - GUI: License window → *Copy License Request Code*
   - Console: run `python license_sdk.py`, copy the printed `REQ-` line.
3. Customer sends you the `REQ-` code (email, your store, etc.).
4. You paste it into the generator's **Generate** tab → pick Duration + Tier →
   **Generate** → send back the `LIC-…` key.
5. Customer pastes the `LIC-` key and activates.

A raw 32-char Hardware ID also works in place of the `REQ-` code, but it only
supports **exact** hardware matching (no tolerance for upgrades).

---

## 5. Key format

```
LIC-<base64url(payload)>.<base64url(ed25519_signature)>
```

Payload (v3):
```json
{
  "ver": 3,
  "hwid": "32-hex composite fingerprint",
  "hw": { "machine": "...", "guid": "...", "disk": "...", "mac": "...", "pid": "..." },
  "issued": "2026-06-12T...Z",
  "expires": "2027-06-12T...Z",   // null = lifetime
  "duration": "1 year",
  "tier": "Pro",
  "features": ["export", "pro"]
}
```

Signature covers the encoded payload, so any change invalidates the key.

---

## 6. Validation logic (what `validate()` checks)

In order, failing closed at the first problem:

1. **Signature** — Ed25519 verify against `PUBLIC_KEY_HEX`.
2. **Hardware** — exact composite match, else fuzzy **k-of-n** (default ≥2 of the
   stored components must match). Survives a NIC swap, disk swap, or single-part
   upgrade; rejects an entirely different machine.
3. **State integrity** — `state.json` is HMAC-signed; tampering is detected.
4. **Trusted time** — fetched from a time API. If offline, an **offline grace
   window** (default 14 days) is allowed before an internet check is required.
5. **Clock rollback** — turning the clock back is detected (5-min tolerance).
6. **Issue/expiry** — not-yet-valid or expired keys are rejected.

Returns `(ok: bool, info: dict)`. `info` includes `tier`, `features`,
`days_remaining`, `hw_match`, `time_trusted`, and `error` on failure.

### Tunables (top of `license_sdk.py`)
```python
OFFLINE_GRACE_DAYS = 14     # days allowed on local clock before online recheck
HW_MATCH_MIN       = 2      # k-of-n minimum matching hardware components
DEFAULT_TRIAL_DAYS = 14
```

---

## 7. Trials

```python
lm.trial_status()        # {'state': 'available'|'active'|'expired'|'tampered', 'days_remaining': int|None}
lm.start_trial(days=14)  # one-time; raises if already used
lm.validate_trial()      # (ok, info) — same time/rollback/grace checks as a license
```

The trial registry is an HMAC-signed hidden file in the user data dir, separate
from the app folder, so uninstalling/reinstalling the app does **not** reset it.
(Deleting the hidden registry file does — close that gap with an activation
server if it matters; see Limitations.)

---

## 8. Export / Import (same-machine backup)

```python
lm.export_license("backup.licx")   # encrypted, bound to this machine's HWID
lm.import_license("backup.licx")    # restores + re-validates; fails on a different machine
```

Use for OS reinstalls or app reinstalls on the **same** computer. For a new
computer, use a transfer request instead.

---

## 9. Hardware transfer / reissue

On the customer's machine:
```python
lm.create_transfer_request("transfer_request.txt")
```
This embeds the old (signed) license plus the new machine's hardware components.

In the generator → **Transfer / Reissue** tab: load the file → **Verify &
Reissue**. The tool verifies the embedded signature and issues a fresh key for
the new hardware **with the same expiration, tier, and features**. Logged in
History as `reissue`.

---

## 10. Tamper-evident logging

Every log line ends with `| chain=<hmac16>` linking it to the previous line
(HMAC keyed off the machine's persistent ID).

```python
lm.review_logs(50)   # last N lines
lm.verify_logs()     # {'ok': bool, 'lines': int, 'first_bad_line': int|None}
```

Editing or deleting any line breaks the chain from that point on, which
`verify_logs()` reports. The GUI log viewer shows a CHAIN OK / CHAIN BROKEN
banner. Rotation starts a fresh chain per file.

---

## 11. Building a protected distributable

```bash
# Native compiled single-file exe (recommended)
python build_app.py myapp.py --name MyApp --mode nuitka --gui --icon app.ico

# Obfuscated bytecode, packed to one file
python build_app.py myapp.py --mode pyarmor --gui

# Preview the command without running it
python build_app.py myapp.py --mode nuitka --dry-run
```

`build_app.py` auto-includes `license_sdk.py`, `license_dialog.py`, and
`help_tips.py` from the entry script's folder. Options: `--name`, `--icon`
(Windows), `--include <modules>`, `--company`, `--version`, `--out`, `--dry-run`.

Notes:
- Nuitka needs a C compiler (Windows: it can auto-download MinGW; Linux also
  needs `patchelf`).
- Compilation/obfuscation raises the bar against casual patching; combine it
  with the crypto checks above for defense in depth.

---

## 12. Dependency management

`license_sdk.py` auto-installs `requests` and `cryptography` on first import via
`pip` (subprocess, wrapped in try/except). No manual `pip install` needed for
end users in a normal Python environment. When compiled with `build_app.py`,
dependencies are bundled into the executable.

---

## 13. API quick reference

```python
LicenseManager(app_name)
  .hwid                      # composite hardware fingerprint (str)
  .components                # dict of individual component hashes
  .validate(key=None)        -> (ok, info)
  .install_license(key)
  .load_license()            -> key str | None
  .has_feature(name)         -> bool
  .require_feature(name)      # raises LicenseError if missing
  .tier                      # current tier after validate()
  .trial_status()            -> dict
  .start_trial(days)
  .validate_trial()          -> (ok, info)
  .export_license(path)
  .import_license(path)      -> (ok, info)
  .create_transfer_request(path)
  .review_logs(lines=50)     -> str
  .verify_logs()             -> dict

# module-level
get_hardware_id()            -> str
get_hardware_components()    -> dict
get_license_request()        -> "REQ-..."
get_trusted_time()           -> (datetime_utc, trusted_bool)
parse_license_key(key)       -> payload dict (raises LicenseError)
require_license(app_name, prompt_if_missing=True, exit_on_fail=True,
                require_features=None, trial_days=None) -> (lm, info)
```

---

## 14. Limitations (and honest threat model)

This is **client-side** licensing. It deters casual copying and enforces
expiry/tiers well, but a determined attacker with the binary can patch checks.
For stronger guarantees:

- **Trial reset** by deleting the hidden registry file is possible offline.
- **Full log deletion** (vs. editing) restarts the chain rather than flagging.
- True one-machine-per-key enforcement, central revocation, and renewals need an
  **activation server** (planned item 9). The SDK is written to add that as an
  online enhancement without breaking offline-first behavior.

Always pair this SDK with `build_app.py` (compilation/obfuscation) for shipped
products.
