# User Manual — Activating & Managing Your License

This guide explains how to activate the app, start a free trial, back up your
license, and move it to a new computer. No technical knowledge required.

---

## Opening the License window

When the app needs a license, it shows a **License** window automatically. It
has four areas:

- **Status** — whether you're licensed, on a trial, or not yet activated.
- **Activate** — where you paste the key you receive.
- **Buttons** for copying your request code and starting a trial.
- **Tools** — Export, Import, Transfer, and View Logs.

Every section has a small **?** button. Click it any time for on-screen help.
Hovering over a button also shows a short tip.

---

## Starting a free trial

If a trial is available, you'll see **"Free trial available"** in the Status box.

1. Click **Start Free Trial**.
2. The status changes to **TRIAL — N days remaining**.
3. Click **Continue** to use the app.

The trial runs once per computer and can't be restarted, so start it when you're
ready to evaluate.

---

## Buying and activating a license

1. In the License window, click **Copy License Request Code**.
   - This copies a code that starts with `REQ-`.
2. Send that code to the vendor (however they ask — email, website, etc.).
3. The vendor sends back a **license key** that starts with `LIC-`.
4. Paste the whole key into the **Activate** box.
5. Click **Activate License**.

You should see **✔ LICENSED** with your plan and expiration date. Click
**Continue**.

> The license is tied to your computer's hardware, so the request code is unique
> to this machine.

---

## Understanding the status line

| You see | Meaning |
|---------|---------|
| ✔ LICENSED — *Plan* — *Duration* | Active license. Days remaining / expiry shown. |
| ● TRIAL — N days remaining | Free trial in progress. |
| ✘ NOT LICENSED | No valid license yet — activate or start a trial. |

**Time source:**
- *online* — your expiry was checked against internet time (most accurate).
- *LOCAL CLOCK (offline)* — you're offline. The app keeps working for a grace
  period (shown as "grace X/14 days used"), then needs an internet connection
  once to re-check.

---

## Backing up your license

Use this before reinstalling Windows or the app **on the same computer**.

**To back up:**
1. Click **Export License**.
2. Choose where to save the `.licx` file (e.g. a USB drive or cloud folder).

**To restore:**
1. Click **Import License**.
2. Select your saved `.licx` file.

> A backup only works on the **same computer** it was made on. To move to a
> different computer, use Transfer (below).

---

## Moving to a new computer or upgrading hardware

If you replace major hardware or move to a new PC and the app stops recognizing
your license:

1. On the affected computer, click **Transfer Request**.
2. Save the `transfer_request.txt` file.
3. Send that file to the vendor.
4. The vendor sends back a new `LIC-` key for your new setup, with the same
   expiration and features.
5. Paste it into **Activate** and click **Activate License**.

Minor changes (like swapping a network card or one drive) usually keep working
automatically — you only need a transfer for bigger changes.

---

## Viewing activity logs

Click **View Logs** to see a record of license checks and events. The top line
tells you whether the log's integrity is intact:

- **[CHAIN OK]** — the log hasn't been altered.
- **[CHAIN BROKEN at line N]** — the log was edited or truncated.

You normally won't need this, but the vendor may ask for it if you report a
problem.

---

## Troubleshooting

**"License bound to different hardware"**
Your hardware changed too much. Use **Transfer Request** and send the file to
the vendor for a new key.

**"No internet time check in 14+ days"**
The app has been offline too long. Connect to the internet and reopen the app
once to revalidate.

**"System clock rollback detected"**
Your computer's date/time was set backward. Set the correct date and time, then
reopen the app.

**"License expired"**
Your term ended. Contact the vendor to renew, then activate the new key.

**"Trial already used on this machine"**
The free trial can only run once per computer. Purchase a license to continue.

**"Trial registry tampered" / "License state file tampered"**
Protected files were modified. Contact the vendor for help.

**Lost your key?**
Contact the vendor — they keep a record and can resend it.
