# Licensing SDK — Step-by-Step Tutorial

Follow these in order. Part 1 is a one-time setup. Part 2 adds licensing to your
app. Part 3 is how you issue keys to customers.

---

## Part 1 — One-Time Vendor Setup (do this once, ever)

- [ ] **1.1** Put these files in a private folder on YOUR computer (not shipped to customers):
  ```
  license_generator.py
  license_sdk.py
  license_dialog.py
  help_tips.py
  ```

- [ ] **1.2** Open a terminal in that folder and run the generator:
  ```
  python license_generator.py
  ```
  The first run creates `vendor_keys.json` (your private signing key).

- [ ] **1.3** Back up `vendor_keys.json` somewhere safe (cloud, USB).
  - Lose it = you can't issue keys existing customers accept.
  - Leak it = anyone can forge your licenses.

- [ ] **1.4** In the generator window, click the **Settings** tab → **Copy Public Key**.

- [ ] **1.5** Open `license_sdk.py`, find this line near the top (~line 65):
  ```python
  PUBLIC_KEY_HEX = "PASTE-PUBLIC-KEY-FROM-GENERATOR-HERE"
  ```
  Replace the placeholder with the key you copied:
  ```python
  PUBLIC_KEY_HEX = "056cad6442b9acf5fa50abbb...your-64-char-key..."
  ```
  Save the file.

> This `license_sdk.py` (with YOUR public key baked in) is the one you ship inside
> your apps. Do it once; reuse the same file across all your apps.

✅ Setup done. You never repeat Part 1 unless you start a brand-new product line
with its own keys.

---

## Part 2 — Add Licensing to Your App

- [ ] **2.1** Copy these three files into your app's folder (next to your main `.py`):
  ```
  license_sdk.py        (the one with your public key from step 1.5)
  license_dialog.py     (only needed for Tkinter GUI apps)
  help_tips.py          (only needed for the dialog)
  ```

- [ ] **2.2** Pick the block that matches your app and paste it at the very top of
  your entry file, before your app starts.

### If it's a console / script app
```python
from license_sdk import require_license
lm, info = require_license(app_name="MyApp", trial_days=14)

# ↓↓↓ your existing code stays exactly as it is ↓↓↓
```

### If it's a Tkinter GUI app
```python
import tkinter as tk
from license_dialog import gui_require_license

lm, info = gui_require_license(app_name="MyApp", trial_days=14)

# ↓↓↓ your existing app below ↓↓↓
root = tk.Tk()
# ...
root.mainloop()
```

### If it's CustomTkinter or PyQt6 (no Tkinter dialog)
```python
import sys
from license_sdk import require_license, LicenseError

try:
    lm, info = require_license(
        app_name="MyApp",
        prompt_if_missing=False,
        exit_on_fail=False,
        trial_days=14,
    )
except LicenseError as e:
    print("License error:", e)   # or show your framework's own message box
    sys.exit(1)

# ↓↓↓ your existing app below ↓↓↓
```

- [ ] **2.3** Change `"MyApp"` to your app's real name.
  - Use a unique name per app — it keeps each app's license, logs, and trial separate.

- [ ] **2.4** (Optional) Remove `trial_days=14` if you don't want a free trial.

- [ ] **2.5** (Optional) Lock premium features. Anywhere after the block above:
  ```python
  if lm.has_feature("export"):
      enable_export_button()

  # or force a tier at startup instead:
  # require_license(app_name="MyApp", require_features=["pro"])
  ```

- [ ] **2.6** Run your app and test:
  - First launch shows the activation prompt/window.
  - Click **Start Free Trial** → app opens. Trial works. ✅

✅ Your app is now licensed.

---

## Part 3 — Issue a Key to a Customer

Do this each time you sell/activate a license.

- [ ] **3.1** Customer gives you their **Request Code** (starts with `REQ-`):
  - In your app's License window: **Copy License Request Code**, or
  - They run `python license_sdk.py` and copy the printed `REQ-` line.

- [ ] **3.2** Open your generator:
  ```
  python license_generator.py
  ```

- [ ] **3.3** **Generate License** tab:
  1. Paste the `REQ-` code into **HWID or REQ- code**.
  2. Pick **Duration** (30 days … Lifetime).
  3. Pick **Tier** (auto-fills features; choose Custom to type your own).
  4. Click **Generate**.
  5. Click **Copy** (or **Save to File**).

- [ ] **3.4** Send the `LIC-` key back to the customer.

- [ ] **3.5** Customer pastes it into **Activate** → **Activate License** → done.

> Every key is saved in the generator's **History** tab. If a customer loses
> theirs, select the row → **Copy Selected Key** → resend.

---

## Part 4 — Ship a Protected Build (optional but recommended)

Compiling makes the license checks much harder to patch out.

- [ ] **4.1** Keep `build_app.py` in your app folder (don't ship it).

- [ ] **4.2** Build a single-file executable:
  ```
  python build_app.py myapp.py --name MyApp --mode nuitka --gui --icon app.ico
  ```
  (`--gui` hides the console window; drop it for console apps. `--icon` is Windows-only.)

- [ ] **4.3** Test the `.exe` from the `dist/` folder on a clean machine (no Python installed).

- [ ] **4.4** Distribute ONLY the built executable. Never ship:
  ```
  license_generator.py
  vendor_keys.json
  build_app.py
  ```

---

## Quick Reference

| You want to… | Do this |
|--------------|---------|
| Add licensing to an app | Part 2, paste one block at the top |
| Give a customer a key | Part 3 (generator → Generate tab) |
| Resend a lost key | Generator → History → Copy Selected Key |
| Move license to new PC | Customer: Transfer Request → you: Transfer/Reissue tab |
| Lock a feature to paid tiers | `if lm.has_feature("name"):` |
| Get the public key for the SDK | Generator → Settings → Copy Public Key |

## Common Errors

| Message | Fix |
|---------|-----|
| `PUBLIC_KEY_HEX not configured` | You skipped step 1.5 — paste your public key into `license_sdk.py`. |
| `Signature verification failed` | The SDK's public key doesn't match the generator that made the key. Re-do step 1.5. |
| `License bound to different hardware` | Customer changed hardware — use Transfer/Reissue (Part 3 note). |
| `No internet time check in 14+ days` | Customer must connect to the internet once to revalidate. |
