"""
license_sdk.py - Drop-in licensing SDK for Python apps (v3).

v3: Fuzzy hardware matching (k-of-n components) + one-time trial mode.

Setup (one time): run license_generator.py once, copy the public key it shows,
paste into PUBLIC_KEY_HEX below. Private key never leaves the generator.

Integration (minimal):
    from license_sdk import require_license
    lm, info = require_license(app_name="MyApp")

With a free trial:
    lm, info = require_license(app_name="MyApp", trial_days=14)

Feature gating:
    lm, info = require_license(app_name="MyApp", require_features=["pro"])
    if lm.has_feature("export"): ...

Customer activation: customer runs `python license_sdk.py` (or uses the dialog)
and sends you the REQ- license request code; you paste it into the generator.
"""

# ----------------------------------------------------------------------
# AUTOMATIC DEPENDENCY MANAGEMENT
# ----------------------------------------------------------------------
import subprocess
import sys

def _ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
    except ImportError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[license_sdk] Failed to auto-install {pkg}: {e}")

_ensure("requests")
_ensure("cryptography")

import os
import json
import hmac
import base64
import hashlib
import logging
import platform
import uuid as _uuid
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# Paste the public key shown by license_generator.py (Settings tab) here:
PUBLIC_KEY_HEX = "PASTE-PUBLIC-KEY-FROM-GENERATOR-HERE"

TIME_APIS = [
    "https://worldtimeapi.org/api/timezone/Etc/UTC",
    "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
]
KEY_PREFIX = "LIC-"
REQ_PREFIX = "REQ-"
EXPORT_SALT = b"license_sdk_export_v1"
STATE_PEPPER = b"license_sdk_state_v3"
OFFLINE_GRACE_DAYS = 14      # days allowed on local clock since last trusted time check
HW_MATCH_MIN = 2             # k-of-n: minimum matching hardware components
DEFAULT_TRIAL_DAYS = 14


class LicenseError(Exception):
    pass


# ----------------------------------------------------------------------
# TAMPER-EVIDENT (HASH-CHAINED) LOG HANDLER
# ----------------------------------------------------------------------
class _ChainedHandler(RotatingFileHandler):
    """Each line ends with '| chain=<hmac16>' linking it to the previous line.
    Editing or deleting any line breaks the chain from that point on."""

    def __init__(self, filename, mac_key: bytes, **kw):
        self._mac_key = mac_key
        super().__init__(filename, **kw)
        self._last = self._read_last_chain()

    def _genesis(self):
        return hmac.new(self._mac_key, b"genesis", hashlib.sha256).hexdigest()[:16]

    def _read_last_chain(self):
        try:
            with open(self.baseFilename, "r", encoding="utf-8", errors="replace") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            if lines and "| chain=" in lines[-1]:
                return lines[-1].rsplit("| chain=", 1)[1].strip()
        except FileNotFoundError:
            pass
        return self._genesis()

    def _chain(self, content: str) -> str:
        return hmac.new(self._mac_key, (self._last + content).encode(),
                        hashlib.sha256).hexdigest()[:16]

    def emit(self, record):
        try:
            content = self.format(record)
            link = self._chain(content)
            record.msg = f"{record.getMessage()} | chain={link}"
            record.args = None
            self._last = link
            super().emit(record)
        except Exception:
            self.handleError(record)

    def doRollover(self):
        super().doRollover()
        self._last = self._genesis()


def verify_log_chain(path: str, mac_key: bytes) -> dict:
    """Recomputes the hash chain. Returns
    {'ok': bool, 'lines': n, 'first_bad_line': int|None}."""
    genesis = hmac.new(mac_key, b"genesis", hashlib.sha256).hexdigest()[:16]
    last = genesis
    try:
        lines = [l for l in open(path, "r", encoding="utf-8",
                                 errors="replace").read().splitlines() if l.strip()]
    except FileNotFoundError:
        return {"ok": True, "lines": 0, "first_bad_line": None}
    for i, line in enumerate(lines, 1):
        if "| chain=" not in line:
            return {"ok": False, "lines": len(lines), "first_bad_line": i}
        body, link = line.rsplit(" | chain=", 1)
        expect = hmac.new(mac_key, (last + body).encode(),
                          hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(expect, link.strip()):
            return {"ok": False, "lines": len(lines), "first_bad_line": i}
        last = link.strip()
    return {"ok": True, "lines": len(lines), "first_bad_line": None}


# ----------------------------------------------------------------------
# HARDWARE COMPONENTS (fuzzy k-of-n)
# ----------------------------------------------------------------------
def _h(v: str) -> str:
    return hashlib.sha256(v.strip().encode()).hexdigest()[:16].upper()

def _user_base_dir():
    if platform.system() == "Windows":
        return os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.expanduser("~/.local/share")

def _persistent_id() -> str:
    """Per-user persistent random ID; survives hardware changes. Anchor component."""
    base = _user_base_dir()
    os.makedirs(base, exist_ok=True)
    fid = os.path.join(base, ".lsdk_machine_id")
    if not os.path.exists(fid):
        with open(fid, "w") as f:
            f.write(_uuid.uuid4().hex)
        try:
            os.chmod(fid, 0o600)
        except Exception:
            pass
    return open(fid).read().strip()

def get_hardware_components() -> dict:
    """Returns {component_name: short_hash}. Platform-dependent set."""
    comps = {}
    system = platform.system()
    try:
        if system == "Windows":
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                    stderr=subprocess.DEVNULL, timeout=10).decode().strip()
                if out and "FFFFFFFF" not in out.upper():
                    comps["machine"] = _h(out)
            except Exception:
                pass
            try:
                import winreg
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                   r"SOFTWARE\Microsoft\Cryptography")
                comps["guid"] = _h(winreg.QueryValueEx(k, "MachineGuid")[0])
            except Exception:
                pass
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-PhysicalDisk | Sort-Object DeviceId | Select-Object -First 1).SerialNumber"],
                    stderr=subprocess.DEVNULL, timeout=10).decode().strip()
                if out:
                    comps["disk"] = _h(out)
            except Exception:
                pass
        elif system == "Linux":
            for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if os.path.exists(p):
                    comps["machine"] = _h(open(p).read())
                    break
            try:
                for blk in sorted(os.listdir("/sys/block")):
                    sp = f"/sys/block/{blk}/device/serial"
                    if os.path.exists(sp):
                        s = open(sp).read().strip()
                        if s:
                            comps["disk"] = _h(s)
                            break
            except Exception:
                pass
        elif system == "Darwin":
            try:
                out = subprocess.check_output(
                    ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    stderr=subprocess.DEVNULL, timeout=10).decode()
                for line in out.splitlines():
                    if "IOPlatformUUID" in line:
                        comps["machine"] = _h(line.split('"')[-2])
                        break
            except Exception:
                pass
    except Exception:
        pass

    node = _uuid.getnode()
    if not (node >> 40) & 1:          # skip randomly-generated MACs
        comps["mac"] = _h(hex(node))

    comps["pid"] = _h(_persistent_id())   # always present anchor
    return comps

def get_hardware_id(components: dict = None) -> str:
    """Composite fingerprint of all components, 32 hex chars."""
    comps = components or get_hardware_components()
    raw = "|".join(f"{k}={comps[k]}" for k in sorted(comps))
    return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()

def get_license_request() -> str:
    """REQ- code the customer sends to the vendor (contains HWID + components)."""
    comps = get_hardware_components()
    req = {"hwid": get_hardware_id(comps), "hw": comps}
    return REQ_PREFIX + _b64e(json.dumps(req, separators=(",", ":")).encode())


def license_summary(info: dict) -> str:
    """Human-readable one-line status from a validate()/require_license() info dict."""
    if not info:
        return "No license information."
    if info.get("error"):
        return f"Not licensed — {info['error']}"
    tier = info.get("tier", "")
    days = info.get("days_remaining")
    if str(tier).lower() == "trial" or info.get("trial") == "active":
        return f"Trial — {days} day(s) remaining" if days is not None else "Trial active"
    if days is None:
        base = f"Licensed: {tier} — Lifetime" if tier else "Licensed — Lifetime"
    else:
        base = f"Licensed: {tier} — {days} day(s) remaining" if tier \
            else f"Licensed — {days} day(s) remaining"
    feats = info.get("features") or []
    if feats:
        base += f"  [features: {', '.join(feats)}]"
    if info.get("time_trusted") is False and info.get("offline_days_used") is not None:
        base += f"  (offline {info['offline_days_used']}/{info['offline_grace_days']}d)"
    return base


# ----------------------------------------------------------------------
# TRUSTED TIME
# ----------------------------------------------------------------------
def get_trusted_time(timeout=6):
    """Returns (datetime_utc, trusted: bool). Falls back to local clock."""
    for url in TIME_APIS:
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            iso = d.get("utc_datetime") or d.get("dateTime")
            if iso:
                iso = iso.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc), True
        except Exception:
            continue
    return datetime.now(timezone.utc), False


# ----------------------------------------------------------------------
# KEY PARSING / Ed25519 VERIFICATION
# ----------------------------------------------------------------------
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def _public_key() -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    except Exception:
        raise LicenseError("PUBLIC_KEY_HEX not configured in license_sdk.py")

def parse_license_key(key: str) -> dict:
    key = key.strip()
    if not key.startswith(KEY_PREFIX):
        raise LicenseError("Invalid key format")
    body = key[len(KEY_PREFIX):]
    try:
        payload_b64, sig_b64 = body.rsplit(".", 1)
    except ValueError:
        raise LicenseError("Malformed key")
    try:
        _public_key().verify(_b64d(sig_b64), payload_b64.encode())
    except InvalidSignature:
        raise LicenseError("Signature verification failed (tampered or wrong key)")
    try:
        payload = json.loads(_b64d(payload_b64))
    except Exception:
        raise LicenseError("Corrupt payload")
    if payload.get("ver") not in (2, 3):
        raise LicenseError(f"Unsupported license version {payload.get('ver')}")
    return payload

def _parse_iso_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------
# MAIN MANAGER
# ----------------------------------------------------------------------
class LicenseManager:
    def __init__(self, app_name="App"):
        self.app_name = app_name
        self.data_dir = self._data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.license_path = os.path.join(self.data_dir, "license.key")
        self.state_path = os.path.join(self.data_dir, "state.json")
        self.log_path = os.path.join(self.data_dir, "license.log")
        self.trials_path = os.path.join(_user_base_dir(), ".lsdk_trials.json")
        self.components = get_hardware_components()
        self.hwid = get_hardware_id(self.components)
        self._features = []
        self._tier = None
        self._setup_logging()

    def _data_dir(self):
        return os.path.join(_user_base_dir(), self.app_name, "license")

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------
    def _setup_logging(self):
        self.log = logging.getLogger(f"license_sdk.{self.app_name}")
        self.log.setLevel(logging.DEBUG)
        if not self.log.handlers:
            h = _ChainedHandler(self.log_path, self._mac_key(),
                                maxBytes=512 * 1024, backupCount=3)
            h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            self.log.addHandler(h)
        try:
            os.chmod(self.log_path, 0o600)
        except Exception:
            pass

    def review_logs(self, lines=50):
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-lines:])
        except FileNotFoundError:
            return "(no log yet)"

    def verify_logs(self) -> dict:
        """Checks the hash chain of the current log file.
        Returns {'ok', 'lines', 'first_bad_line'}."""
        return verify_log_chain(self.log_path, self._mac_key())

    # ------------------------------------------------------------------
    # SIGNED STATE / TRIAL FILES (HMAC keyed by persistent ID)
    # ------------------------------------------------------------------
    def _mac_key(self) -> bytes:
        return hashlib.sha256(_persistent_id().encode() + STATE_PEPPER).digest()

    def _load_signed(self, path):
        """Returns (dict, status) where status in {'ok','missing','tampered'}."""
        try:
            with open(path) as f:
                wrapper = json.load(f)
            data_b64 = wrapper["data"]
            mac = wrapper["mac"]
            expect = hmac.new(self._mac_key(), data_b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, expect):
                return {}, "tampered"
            return json.loads(_b64d(data_b64)), "ok"
        except FileNotFoundError:
            return {}, "missing"
        except Exception:
            return {}, "tampered"

    def _save_signed(self, path, d: dict):
        data_b64 = _b64e(json.dumps(d).encode())
        mac = hmac.new(self._mac_key(), data_b64.encode(), hashlib.sha256).hexdigest()
        with open(path, "w") as f:
            json.dump({"data": data_b64, "mac": mac}, f)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    def _load_state(self):
        return self._load_signed(self.state_path)

    def _save_state(self, st):
        self._save_signed(self.state_path, st)

    # ------------------------------------------------------------------
    # INSTALL / LOAD
    # ------------------------------------------------------------------
    def install_license(self, key: str):
        parse_license_key(key)
        with open(self.license_path, "w") as f:
            f.write(key.strip())
        try:
            os.chmod(self.license_path, 0o600)
        except Exception:
            pass
        self.log.info("License installed")

    def load_license(self):
        try:
            return open(self.license_path).read().strip()
        except FileNotFoundError:
            return None

    def deactivate_license(self, export_path: str = None):
        """Remove the installed license from this machine so it can be moved.
        Optionally export an encrypted backup first. Returns the removed key (or None)."""
        key = self.load_license()
        if not key:
            return None
        if export_path:
            self.export_license(export_path)
        try:
            os.remove(self.license_path)
        except FileNotFoundError:
            pass
        self._tier = None
        self._features = []
        self.log.info(f"License deactivated{' (backup exported)' if export_path else ''}")
        return key

    # ------------------------------------------------------------------
    # FUZZY HARDWARE MATCH
    # ------------------------------------------------------------------
    def _hardware_matches(self, payload) -> (bool, str):
        if payload.get("hwid") == self.hwid:
            return True, "exact"
        lic_hw = payload.get("hw") or {}
        if not lic_hw:
            return False, "composite HWID mismatch (no component data in license)"
        common = set(lic_hw) & set(self.components)
        matches = sum(1 for c in common if lic_hw[c] == self.components[c])
        need = HW_MATCH_MIN if len(common) >= HW_MATCH_MIN else max(len(common), 1)
        if matches >= need:
            self.log.warning(f"Fuzzy hardware match: {matches}/{len(common)} components "
                             f"(hardware partially changed)")
            return True, f"fuzzy {matches}/{len(common)}"
        return False, f"hardware mismatch ({matches}/{len(common)} components matched, need {need})"

    # ------------------------------------------------------------------
    # TIME / ROLLBACK CHECKS (shared by license + trial)
    # ------------------------------------------------------------------
    def _time_check(self, info):
        """Returns (now, ok, err). Updates and saves signed state."""
        st, st_status = self._load_state()
        if st_status == "tampered":
            return None, False, "License state file tampered — contact vendor"
        now, trusted = get_trusted_time()
        info["time_trusted"] = trusted
        if trusted:
            st["last_trusted"] = now.timestamp()
        else:
            anchor = st.get("last_trusted") or st.get("first_seen")
            if anchor is None:
                st["first_seen"] = now.timestamp()
                anchor = st["first_seen"]
                self.log.warning("No trusted time available; starting offline grace window")
            offline_days = (now.timestamp() - anchor) / 86400
            info["offline_days_used"] = round(max(offline_days, 0), 1)
            info["offline_grace_days"] = OFFLINE_GRACE_DAYS
            if offline_days > OFFLINE_GRACE_DAYS:
                self._save_state(st)
                return now, False, (f"No internet time check in {OFFLINE_GRACE_DAYS}+ days — "
                                    "connect to internet to revalidate")
        last_seen = st.get("last_seen")
        if last_seen and now.timestamp() < last_seen - 300:
            self._save_state(st)
            return now, False, "System clock rollback detected"
        st["last_seen"] = max(now.timestamp(), last_seen or 0)
        st.setdefault("first_seen", now.timestamp())
        self._save_state(st)
        return now, True, None

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------
    def validate(self, key: str = None):
        """Returns (ok: bool, info: dict). Logs every attempt."""
        key = key or self.load_license()
        info = {"hwid": self.hwid}
        if not key:
            self.log.warning("Validation failed: no license installed")
            return False, {**info, "error": "No license installed"}

        try:
            payload = parse_license_key(key)
        except LicenseError as e:
            self.log.error(f"Validation failed: {e}")
            return False, {**info, "error": str(e)}

        info.update({k: v for k, v in payload.items() if k != "hw"})

        hw_ok, hw_detail = self._hardware_matches(payload)
        info["hw_match"] = hw_detail
        if not hw_ok:
            self.log.error(f"Validation failed: {hw_detail}")
            return False, {**info, "error": f"License bound to different hardware — {hw_detail}"}

        now, t_ok, t_err = self._time_check(info)
        if not t_ok:
            self.log.error(f"Validation failed: {t_err}")
            return False, {**info, "error": t_err}

        issued = _parse_iso_utc(payload["issued"])
        if now < issued - timedelta(minutes=10):
            self.log.error("Validation failed: issue date in the future")
            return False, {**info, "error": "License issue date is in the future"}

        exp = payload.get("expires")
        if exp:
            exp_dt = _parse_iso_utc(exp)
            if now > exp_dt:
                self.log.warning("Validation failed: license expired")
                return False, {**info, "error": f"License expired {exp}"}
            info["days_remaining"] = (exp_dt - now).days
        else:
            info["days_remaining"] = None  # lifetime

        self._tier = payload.get("tier", "Standard")
        self._features = [f.lower() for f in payload.get("features", [])]
        info["tier"] = self._tier
        info["features"] = self._features

        self.log.info(f"Validation OK | tier={self._tier} | duration={payload.get('duration')} "
                      f"| hw={hw_detail} | trusted_time={info.get('time_trusted')}")
        return True, info

    # ------------------------------------------------------------------
    # TRIAL MODE (one-time per machine per app, signed registry)
    # ------------------------------------------------------------------
    def trial_status(self):
        """Returns dict: {'state': 'available'|'active'|'expired'|'tampered',
                          'days_remaining': int|None}"""
        reg, status = self._load_signed(self.trials_path)
        if status == "tampered":
            return {"state": "tampered", "days_remaining": None}
        t = reg.get(self.app_name)
        if not t:
            return {"state": "available", "days_remaining": None}
        now, _ = get_trusted_time()
        end = t["started"] + t["days"] * 86400
        remaining = (end - now.timestamp()) / 86400
        if remaining <= 0:
            return {"state": "expired", "days_remaining": 0}
        return {"state": "active", "days_remaining": int(remaining) + (1 if remaining % 1 else 0)}

    def start_trial(self, days=DEFAULT_TRIAL_DAYS):
        """Starts the one-time trial. Raises LicenseError if already used/tampered."""
        reg, status = self._load_signed(self.trials_path)
        if status == "tampered":
            self.log.error("Trial start refused: trial registry tampered")
            raise LicenseError("Trial registry tampered — contact vendor")
        if self.app_name in reg:
            self.log.warning("Trial start refused: already used")
            raise LicenseError("Trial already used on this machine")
        now, trusted = get_trusted_time()
        reg[self.app_name] = {"started": now.timestamp(), "days": int(days),
                              "trusted_start": trusted}
        self._save_signed(self.trials_path, reg)
        self.log.info(f"Trial started: {days} days (trusted_time={trusted})")

    def validate_trial(self):
        """Returns (ok, info) for trial access. Applies same time/rollback checks."""
        info = {"hwid": self.hwid, "tier": "Trial", "features": []}
        ts = self.trial_status()
        info["trial"] = ts["state"]
        if ts["state"] == "tampered":
            self.log.error("Trial validation failed: registry tampered")
            return False, {**info, "error": "Trial registry tampered — contact vendor"}
        if ts["state"] == "available":
            return False, {**info, "error": "Trial not started"}
        if ts["state"] == "expired":
            self.log.warning("Trial validation failed: expired")
            return False, {**info, "error": "Trial expired — purchase a license"}
        now, t_ok, t_err = self._time_check(info)
        if not t_ok:
            self.log.error(f"Trial validation failed: {t_err}")
            return False, {**info, "error": t_err}
        self._tier = "Trial"
        self._features = []
        info["days_remaining"] = ts["days_remaining"]
        info["duration"] = "Trial"
        self.log.info(f"Trial validation OK | {ts['days_remaining']} days remaining")
        return True, info

    # ------------------------------------------------------------------
    # FEATURE GATING
    # ------------------------------------------------------------------
    def has_feature(self, name: str) -> bool:
        return name.lower() in self._features

    def status_line(self) -> str:
        """One-line human status for the current license/trial (re-validates)."""
        ok, info = self.validate()
        if not ok:
            t_ok, t_info = self.validate_trial()
            if t_ok:
                info = t_info
        return license_summary(info)

    @property
    def tier(self):
        return self._tier

    def require_feature(self, name: str):
        if not self.has_feature(name):
            self.log.warning(f"Feature denied: {name}")
            raise LicenseError(f"License does not include feature: {name}")

    # ------------------------------------------------------------------
    # EXPORT / IMPORT (encrypted, bound to current composite HWID)
    # ------------------------------------------------------------------
    def _export_fernet(self, hwid: str) -> Fernet:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=EXPORT_SALT, iterations=200_000)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(hwid.encode())))

    def export_license(self, out_path: str):
        key = self.load_license()
        if not key:
            raise LicenseError("No license installed to export")
        blob = self._export_fernet(self.hwid).encrypt(key.encode())
        with open(out_path, "wb") as f:
            f.write(b"LSDKEXP1" + blob)
        self.log.info(f"License exported to {out_path}")
        return out_path

    def import_license(self, in_path: str):
        data = open(in_path, "rb").read()
        if not data.startswith(b"LSDKEXP1"):
            raise LicenseError("Not a valid export file")
        try:
            key = self._export_fernet(self.hwid).decrypt(data[8:]).decode()
        except InvalidToken:
            self.log.error("Import failed: hardware changed or file corrupt")
            raise LicenseError("Import failed — hardware ID does not match export")
        self.install_license(key)
        ok, info = self.validate(key)
        self.log.info(f"License imported, re-validation ok={ok}")
        return ok, info

    # ------------------------------------------------------------------
    # LIMITED TRANSFER (hardware upgrade reissue request)
    # ------------------------------------------------------------------
    def create_transfer_request(self, out_path: str):
        """Contains the old (Ed25519-signed) license + new HWID + new components.
        The generator verifies the embedded license signature."""
        key = self.load_license()
        if not key:
            raise LicenseError("No license installed")
        req = {
            "type": "transfer_request",
            "old_license": key,
            "new_hwid": self.hwid,
            "new_hw": self.components,
            "requested": datetime.now(timezone.utc).isoformat(),
        }
        blob = f"XFER-{_b64e(json.dumps(req).encode())}"
        with open(out_path, "w") as f:
            f.write(blob)
        self.log.info(f"Transfer request written to {out_path}")
        return out_path


# ----------------------------------------------------------------------
# ONE-LINE INTEGRATION
# ----------------------------------------------------------------------
def require_license(app_name="App", prompt_if_missing=True, exit_on_fail=True,
                    require_features=None, trial_days=None):
    """If trial_days is set and no license is installed, falls back to the
    one-time trial (auto-starting it if still available)."""
    lm = LicenseManager(app_name)
    ok, info = lm.validate()

    if not ok and info.get("error") == "No license installed" and trial_days:
        ts = lm.trial_status()
        if ts["state"] == "available":
            try:
                lm.start_trial(trial_days)
            except LicenseError:
                pass
        ok, info = lm.validate_trial()
        if ok:
            return lm, info  # trial grants base features only

    err = str(info.get("error", ""))
    if not ok and prompt_if_missing and ("No license installed" in err or "Trial" in err):
        try:
            key = input(f"[{app_name}] Enter license key: ").strip()
            if key:
                lm.install_license(key)
                ok, info = lm.validate()
        except (EOFError, KeyboardInterrupt):
            pass

    if ok and require_features:
        missing = [f for f in require_features if not lm.has_feature(f)]
        if missing:
            ok = False
            info["error"] = f"License tier '{lm.tier}' missing features: {', '.join(missing)}"

    if not ok:
        msg = f"[{app_name}] License check failed: {info.get('error')}"
        if exit_on_fail:
            print(msg)
            sys.exit(1)
        raise LicenseError(msg)
    return lm, info


if __name__ == "__main__":
    print("Hardware ID :", get_hardware_id())
    print("Components  :", json.dumps(get_hardware_components(), indent=1))
    print("\nLicense Request Code (send this to vendor):")
    print(get_license_request())
    lm = LicenseManager("SDKTest")
    ok, info = lm.validate()
    print("\nLicensed:", ok)
    if not ok:
        print("Trial:", lm.trial_status())
