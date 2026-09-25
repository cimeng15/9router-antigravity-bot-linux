#!/usr/bin/env python3
"""
Bot AntiGravity - Auto Add Account ke 9Router (REVISI 3: API-DRIVEN)

REVISI 3 — Kenapa pendekatannya diubah total:
  Masalah versi lama (klik UI "Add Connection"):
    - Setelah consent Google, browser di-redirect ke
      http://localhost:443/callback?code=... — URL callback ini
      menuju KOMPUTER USER (native app flow), bukan ke server 9Router.
      Di server/VPS tidak ada yang listen di port 443/8080, jadi
      alurnya selalu GAGAL walaupun login Google sukses.
  Solusi sekarang (pakai API internal 9Router yang sama dipakai UI):
    1. GET  /api/oauth/antigravity/authorize  → authUrl + state + codeVerifier
    2. Browser (Camoufox) login Google; request redirect ke
       http://localhost:8080/callback?code=... DITANGKAP via Playwright
       route interception (tidak butuh server callback sama sekali)
    3. POST /api/oauth/antigravity/exchange   → akun terdaftar di 9Router
    4. GET  /api/providers                    → verifikasi akun masuk

  Keuntungan:
    - Tidak tergantung UI dashboard (aman kalau tampilan berubah)
    - Tidak butuh server callback / port terbuka
    - Kegagalan jelas: salah password / 2FA / CAPTCHA / timeout —
      masing-masing punya pesan error spesifik

Cara pakai:
  python3 bot_api.py --base https://ai.smkdata.sch.id
  python3 bot_api.py                  # pakai default di bawah
  python3 bot_api.py --headed         # lihat browser
  python3 bot_api.py --file akun.txt
  python3 bot_api.py --delay 10

Format akun.txt: email|password (satu baris per akun)
"""

# ============================================================
# AUTO-INSTALLER
# ============================================================
import os
import sys
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.parse
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _ensure_deps():
    """Pastikan camoufox terinstall + binary-nya sudah di-fetch."""
    try:
        import camoufox  # noqa: F401
        return
    except ImportError:
        pass
    print("=" * 50)
    print(" Camoufox belum terinstall! Menginstall otomatis...")
    print("=" * 50)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "camoufox[geoip]"],
    )
    subprocess.check_call([sys.executable, "-m", "camoufox", "fetch"])
    print("\n Camoufox berhasil diinstall!\n")


_ensure_deps()

from camoufox.sync_api import Camoufox  # noqa: E402

# ============================================================
# KONFIGURASI
# ============================================================
BASE_URL = "https://ai.smkdata.sch.id"
PROVIDER = "antigravity"
REDIRECT_PORT = 8080          # port callback loopback (default 9Router)
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
AKUN_FILE = os.path.join(SCRIPT_DIR, "akun.txt")
DELAY_ANTAR_AKUN = 3

# Timeout total menunggu kode dari redirect Google (detik)
CODE_WAIT_TIMEOUT = 150

# ============================================================
# TIMING PROFILES (detik)
# ============================================================
TIMING = {
    "fast": {
        "google_initial":    1,
        "after_email_next":  2,
        "password_timeout":  10,
        "after_pw_next":     2,
        "step_loop_wait":    1,
        "no_btn_wait":       2,
        "after_success":     1,
    },
    "normal": {
        "google_initial":    3,
        "after_email_next":  4,
        "password_timeout":  20,
        "after_pw_next":     4,
        "step_loop_wait":    2,
        "no_btn_wait":       4,
        "after_success":     2,
    },
}


# ============================================================
# API 9ROUTER
# ============================================================
def api_get(path, params=None, base=None, timeout=30):
    base = base or BASE_URL
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path, payload, base=None, timeout=60):
    base = base or BASE_URL
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            return body, f"HTTP {e.code}: {body.get('error', body)}"
        except Exception:
            return {}, f"HTTP {e.code}"
    except Exception as e:
        return {}, str(e)


def start_oauth(base):
    """Minta 9Router bikin state+verifier & URL login Google."""
    data = api_get(f"/api/oauth/{PROVIDER}/authorize",
                   params={"redirect_uri": REDIRECT_URI}, base=base)
    for key in ("authUrl", "state", "codeVerifier"):
        if key not in data:
            raise Exception(f"Response /authorize tidak valid: {list(data.keys())}")
    return data


def exchange_code(code, state, code_verifier, base):
    """Tukar kode OAuth jadi akun terdaftar di 9Router."""
    resp, err = api_post(f"/api/oauth/{PROVIDER}/exchange", {
        "code": code,
        "redirectUri": REDIRECT_URI,
        "codeVerifier": code_verifier,
        "state": state,
    }, base=base)
    if err:
        raise Exception(f"Exchange gagal: {err}")
    return resp


def get_antigravity_emails(base):
    """Ambil daftar email akun antigravity yang sudah terdaftar."""
    try:
        data = api_get("/api/providers", base=base)
        conns = data.get("connections", data if isinstance(data, list) else [])
        return {c.get("email", "").lower() for c in conns
                if c.get("provider", c.get("alias", "")) in (PROVIDER, "ag")
                and c.get("email")}
    except Exception as e:
        print(f" [WARN]   Gagal membaca /api/providers: {e}")
        return set()


# ============================================================
# AKUN
# ============================================================
def read_accounts(path):
    if not os.path.exists(path):
        print(f" [ERROR] File '{path}' tidak ditemukan!")
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    accounts = []
    for line in lines:
        if "|" not in line:
            continue
        email, password = [p.strip() for p in line.split("|", 1)]
        if email and password:
            accounts.append({"email": email, "password": password, "raw": line})
    return accounts


def remove_account(path, raw_line):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    remaining = [l for l in lines if l.strip() != raw_line]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(remaining)


# ============================================================
# HELPER KLIK DI HALAMAN GOOGLE
# ============================================================
# REVISI: Google bisa menampilkan halaman consent dalam bahasa Indonesia
# ATAU Inggris, tergantung lokasi IP. Contoh nyata (IP Indonesia):
#   "Pastikan Anda mendownload aplikasi ini dari Google" → tombol "Login"
# Kata kunci diurutkan dari yang PALING AMAN — jangan pernah klik
# "Batal" / "Cancel" / "No" / "Sign out".
CONSENT_KEYWORDS = [
    "I Understand", "I understand", "Saya memahami",
    "Allow", "Izinkan",
    "Continue", "Lanjutkan",
    "Confirm", "Konfirmasi",
    "I agree", "Saya setuju",
    "Enter the password again",
    "Login", "Sign in", "Masuk",
    "Next", "Berikutnya",
]


def js_click_any(page, texts, exact=False):
    """Klik elemen (button/a) yang teksnya cocok, via JS. Return True jika sukses."""
    script = """
    ([texts, exact]) => {
        const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
        const els = [...document.querySelectorAll('button, a, input[type="submit"]')];
        for (const t of texts) {
            const target = norm(t);
            const el = els.find(e => {
                const txt = norm(e.innerText || e.value);
                return exact ? txt === target : txt.includes(target);
            });
            if (el) { el.click(); return true; }
        }
        return false;
    }
    """
    try:
        return page.evaluate(script, [texts, exact])
    except Exception:
        return False


def js_click_consent(page):
    """Klik tombol consent di halaman Google — exact-match dulu (aman
    untuk tombol pendek seperti 'Login'), baru partial-match frasa panjang.
    Terakhir: exact-match Login/Masuk/Sign in (khusus halaman nativeapp)."""
    if js_click_any(page, CONSENT_KEYWORDS, exact=True):
        return True
    long_phrases = [
        "I Understand", "I understand", "Saya memahami",
        "Lanjutkan", "Continue", "Izinkan", "Allow",
        "Konfirmasi", "Confirm", "Saya setuju", "I agree",
        "Enter the password again", "Berikutnya", "Next",
    ]
    if js_click_any(page, long_phrases, exact=False):
        return True
    return js_click_any(page, ["Login", "Masuk", "Sign in"], exact=True)


def detect_login_error(page):
    """Deteksi halaman error login (EN + ID). Return pesan atau None."""
    try:
        return page.evaluate("""() => {
            const t = document.body.innerText.toLowerCase();
            if (t.includes('wrong password') || t.includes('sandi salah')
                || t.includes('kata sandi salah'))
                return 'Password salah (Google: Wrong password)';
            if (t.includes("couldn't find your google account")
                || t.includes('tidak menemukan akun google')
                || t.includes('tidak dapat menemukan akun google'))
                return 'Email tidak ditemukan (Google: Account not found)';
            return null;
        }""")
    except Exception:
        return None


# ============================================================
# FUNGSI UTAMA: PROSES SATU AKUN
# ============================================================
def process_account(account, index, total, headed, t, base):
    email = account["email"]
    password = account["password"]

    print(f"\n{'=' * 55}")
    print(f" Akun {index + 1}/{total}: {email}")
    print(f"{'=' * 55}")

    # --- [1/6] Minta sesi OAuth ke 9Router ---
    print(" [1/6] Membuat sesi OAuth via API 9Router...")
    oauth = start_oauth(base)
    state, verifier = oauth["state"], oauth["codeVerifier"]
    print(f"        redirect_uri : {oauth.get('redirectUri', REDIRECT_URI)}")
    print(f"        state        : {state[:20]}...")

    # --- [2/6] Siapkan penangkap kode (route interception) ---
    captured = {}

    def _intercept_callback(route):
        q = urllib.parse.parse_qs(
            urllib.parse.urlparse(route.request.url).query)
        if "code" in q:
            captured["code"] = q["code"][0]
            captured["state"] = (q.get("state") or [""])[0]
            print("        >> Kode OAuth tertangkap dari redirect!")
        elif "error" in q:
            captured["error"] = (q.get("error_description")
                                 or q["error"])[0]
            print(f"        >> Google mengembalikan error: {captured['error']}")
        try:
            route.abort()
        except Exception:
            pass

    print(" [2/6] Membuka Camoufox (anti-detect Firefox)...")
    cam_kwargs = dict(
        headless=not headed,
        geoip=True,
        humanize=True,
        i_know_what_im_doing=True,
    )

    with Camoufox(**cam_kwargs) as browser:
        context = browser.new_context(locale="en-US")
        context.route(f"http://localhost:{REDIRECT_PORT}/**",
                      _intercept_callback)
        page = context.new_page()

        # --- [3/6] Buka halaman login Google ---
        print(" [3/6] Membuka halaman login Google...")
        page.goto(oauth["authUrl"], wait_until="domcontentloaded",
                  timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(t["google_initial"])

        # --- [4/6] Login Google ---
        print(f" [4/6] Login Google: {email}")
        try:
            email_field = page.wait_for_selector(
                "#identifierId", timeout=t["password_timeout"] * 1000)
            email_field.fill(email)
        except Exception:
            raise Exception(
                "Field email Google tidak ditemukan (halaman tidak dikenal / "
                f"URL sekarang: {page.url[:80]})")
        time.sleep(0.5)
        try:
            page.click("#identifierNext", timeout=5000)
        except Exception:
            if not js_click_any(page, ["Next", "Berikutnya"]):
                raise Exception("Tombol Next (email) tidak ditemukan")
        time.sleep(t["after_email_next"])

        try:
            pw_field = page.wait_for_selector(
                'input[type="password"]', timeout=t["password_timeout"] * 1000)
            pw_field.fill(password)
        except Exception:
            err = detect_login_error(page)
            if err:
                raise Exception(err)
            raise Exception(
                f"Field password tidak muncul (mungkin email salah / 2FA. "
                f"URL: {page.url[:80]})")
        time.sleep(0.5)
        try:
            page.click("#passwordNext", timeout=5000)
        except Exception:
            if not js_click_any(page, ["Next", "Berikutnya"]):
                raise Exception("Tombol Next (password) tidak ditemukan")
        time.sleep(t["after_pw_next"])

        # --- [5/6] Handle konfirmasi Google sampai kode tertangkap ---
        print(" [5/6] Menunggu konfirmasi Google & kode OAuth...")
        deadline = time.time() + CODE_WAIT_TIMEOUT
        step = 0
        while time.time() < deadline:
            if "code" in captured or "error" in captured:
                break
            step += 1
            time.sleep(t["step_loop_wait"])

            try:
                current_url = page.url
            except Exception:
                break  # tab ditutup

            if f"localhost:{REDIRECT_PORT}/callback" in current_url:
                break  # redirect terjadi, kode mestinya sudah tertangkap

            err = detect_login_error(page)
            if err:
                raise Exception(err)

            if step % 5 == 1:
                print(f"        [Step {step}] URL: {current_url[:80]}")

            # Halaman Workspace TOS: "Welcome to your new account"
            if "workspacetermsofservice" in current_url or "speedbump" in current_url:
                print("        >> Halaman 'Welcome to your new account' terdeteksi")
                if js_click_consent(page):
                    print("        >> 'I understand' diklik!")
                    time.sleep(t["after_pw_next"])
                continue

            # Consent / nativeapp / Allow / Continue / Login (ID+EN)
            if js_click_consent(page):
                print("        >> Tombol consent diklik!")
                time.sleep(t["step_loop_wait"])
                continue

            # Centang checkbox consent yang belum dicentang (kalau ada)
            try:
                page.evaluate("""() => document.querySelectorAll(
                       'input[type="checkbox"]:not(:checked)')
                   .forEach(cb => cb.click())""")
            except Exception:
                pass

            time.sleep(t["no_btn_wait"])

        if "error" in captured:
            raise Exception(f"Google menolak consent: {captured['error']}")
        if "code" not in captured:
            raise Exception(
                f"Kode OAuth tidak tertangkap dalam {CODE_WAIT_TIMEOUT} detik "
                f"(kemungkinan stuck di halaman: {page.url[:80]})")

        if captured.get("state") and captured["state"] != state:
            raise Exception("State OAuth tidak cocok — kemungkinan sesi kedaluwarsa")

        # --- [6/6] Exchange kode → akun terdaftar di 9Router ---
        print(" [6/6] Mendaftarkan akun ke 9Router (exchange)...")
        exchange_code(captured["code"], state, verifier, base)

    # --- Verifikasi akun benar-benar masuk ---
    time.sleep(t["after_success"])
    emails = get_antigravity_emails(base)
    if email.lower() in emails:
        print(f"\n [SUKSES] Akun {index + 1}/{total}: {email}")
        print(" [INFO]   Akun terverifikasi ada di /api/providers")
        remove_account(AKUN_FILE, account["raw"])
        print(" [INFO]   Akun dihapus dari akun.txt")
    else:
        print(f"\n [SUKSES?] Akun {index + 1}/{total}: {email}")
        print(" [WARN]   Exchange sukses tapi email belum terlihat di "
              "/api/providers (cek manual di dashboard)")


# ============================================================
# MAIN
# ============================================================
def main():
    global BASE_URL, REDIRECT_PORT, REDIRECT_URI, AKUN_FILE

    parser = argparse.ArgumentParser(
        description="Bot AntiGravity - Auto Add Account ke 9Router (API-driven)"
    )
    parser.add_argument("--headed", action="store_true",
                        help="Tampilkan browser (default: headless)")
    parser.add_argument("--fast", action="store_true",
                        help="Mode cepat (internet bagus, delay minimal)")
    parser.add_argument("--delay", type=int, default=DELAY_ANTAR_AKUN,
                        help=f"Delay antar akun (default: {DELAY_ANTAR_AKUN}s)")
    parser.add_argument("--file", type=str, default=None,
                        help="Path file akun (default: akun.txt)")
    parser.add_argument("--base", type=str, default=None,
                        help=f"Base URL 9Router (default: {BASE_URL})")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Port callback loopback (default: {REDIRECT_PORT})")
    args = parser.parse_args()

    if args.base:
        BASE_URL = args.base.rstrip("/")
    if args.port:
        REDIRECT_PORT = args.port
        REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
    if args.file:
        AKUN_FILE = args.file

    speed_mode = "fast" if args.fast else "normal"
    t = TIMING[speed_mode]

    print_banner()

    # Sanity check: 9Router harus bisa dihubungi
    try:
        api_get("/api/providers", base=BASE_URL, timeout=15)
    except Exception as e:
        print(f" [ERROR] 9Router tidak bisa dihubungi di {BASE_URL}: {e}")
        sys.exit(1)

    accounts = read_accounts(AKUN_FILE)
    if not accounts:
        print("\n [INFO] Tidak ada akun yang bisa diproses.")
        print("        Format akun.txt: email|password (satu baris per akun)")
        sys.exit(1)

    before = get_antigravity_emails(BASE_URL)
    print(f" Target      : {BASE_URL}")
    print(f" Speed mode  : {speed_mode.upper()}")
    print(f" Headless    : {'TIDAK (headed)' if args.headed else 'YA (default)'}")
    print(f" Delay antar : {args.delay} detik")
    print(f" File akun   : {AKUN_FILE}")
    print(f" Akun terdaftar sudah: {len(before)}")
    print(f" Total akun baru   : {len(accounts)}\n")

    sukses, gagal = 0, 0
    for i, account in enumerate(accounts):
        try:
            process_account(account, i, len(accounts),
                            headed=args.headed, t=t, base=BASE_URL)
            remaining = read_accounts(AKUN_FILE)
            if account["raw"] not in [a["raw"] for a in remaining]:
                sukses += 1
            else:
                gagal += 1
        except Exception as e:
            print(f"\n [GAGAL] Akun {i + 1}/{len(accounts)}: {account['email']}")
            print(f"          Error: {e}")
            gagal += 1

        if i < len(accounts) - 1:
            print(f"\n [DELAY] Menunggu {args.delay} detik...")
            time.sleep(args.delay)

    print(f"\n{'=' * 55}")
    print(" SELESAI!")
    print(f" Total  : {len(accounts)} akun")
    print(f" Sukses : {sukses} akun")
    print(f" Gagal  : {gagal} akun")
    print(f"{'=' * 55}")


def print_banner():
    banner = r"""
     _   __                __
    / | / /__  _______  __/ /_____  _________ ____
   /  |/ / _ \/ ___/ / / / __/ __ \/ ___/ __ `/ _ \
  / /|  /  __/ /  / /_/ / /_/ /_/ / /  / /_/ /  __/
 /_/ |_/\___/_/   \__,_/\__/\____/_/   \__,_/\___/
    Bot Auto Add Account - API-driven (Camoufox)
    """
    print(banner)
    print("=" * 55)


if __name__ == "__main__":
    main()
