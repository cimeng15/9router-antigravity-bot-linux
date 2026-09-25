#!/usr/bin/env python3
"""
Bot AntiGravity - Auto Add Account ke 9Router (REVISI CAMOUFOX HEADLESS)

Perubahan dari bot.py (DrissionPage + Chrome):
  - Browser diganti: Camoufox (Firefox anti-detect berbasis Playwright)
    * Tidak ada bug WebSocket headless seperti Chrome/DrissionPage
    * Headless NATAYA stabil, bisa jalan di server tanpa display (pakai Xvfb virtual)
  - TARGET_URL diarahkan ke proxy 9Router user (bukan localhost)
  - Fix salah klik tombol "Add Model" (kini exact-match tombol "Add")
  - Fix tombol modal konfirmasi "I Understand, Continue" (teks persis di 9Router)
  - Popup Google ditangkap via context.expect_page() (andal, bukan polling tab_ids)
  - Timeout berbasis kondisi (wait_for_selector) bukan sleep buta
  - Error handling per-akun tetap: 1 gagal, lanjut ke berikutnya

Cara pakai:
  python3 bot_camoufox.py                  # headless (default)
  python3 bot_camoufox.py --headed         # lihat browser
  python3 bot_camoufox.py --fast           # mode cepat
  python3 bot_camoufox.py --delay 10       # delay antar akun
  python3 bot_camoufox.py --file akun.txt  # file akun custom

Format akun.txt: email|password (satu baris per akun)
"""

# ============================================================
# AUTO-INSTALLER
# ============================================================
import os
import sys
import subprocess
import shutil
import time
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _ensure_deps():
    """Pastikan camoufox terinstall + binary-nya sudah di-fetch."""
    try:
        import camoufox  # noqa: F401
    except ImportError:
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
# KONFIGURASI  (REVISI: pakai proxy 9Router user, bukan localhost)
# ============================================================
TARGET_URL = "https://ai.smkdata.sch.id/dashboard/providers/antigravity"
AKUN_FILE = os.path.join(SCRIPT_DIR, "akun.txt")
DELAY_ANTAR_AKUN = 3

# ============================================================
# TIMING PROFILES (detik)
# ============================================================
TIMING = {
    "fast": {
        "page_load":          2,
        "after_add_click":    1,
        "popup_timeout":      20,
        "google_initial":     1,
        "after_email_next":   2,
        "password_timeout":   10,
        "after_pw_next":      2,
        "step_loop_wait":     1,
        "btn_timeout":        4,
        "no_btn_wait":        2,
        "redirect_wait":      3,
        "after_success":      1,
    },
    "normal": {
        "page_load":          4,
        "after_add_click":    2,
        "popup_timeout":      40,
        "google_initial":     3,
        "after_email_next":   4,
        "password_timeout":   20,
        "after_pw_next":      4,
        "step_loop_wait":     2,
        "btn_timeout":        8,
        "no_btn_wait":        4,
        "redirect_wait":      5,
        "after_success":      2,
    },
}


# ============================================================
# HELPER
# ============================================================
def print_banner():
    banner = r"""
     _   __                __
    / | / /__  _______  __/ /_____  _________ ____
   /  |/ / _ \/ ___/ / / / __/ __ \/ ___/ __ `/ _ \
  / /|  /  __/ /  / /_/ / /_/ /_/ / /  / /_/ /  __/
 /_/ |_/\___/_/   \__,_/\__/\____/_/   \__,_/\___/
    Bot Auto Add Account - Camoufox (headless-ready)
    """
    print(banner)
    print("=" * 55)


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


# REVISI: Google bisa menampilkan halaman consent dalam bahasa Indonesia
# ATAU Inggris, tergantung lokasi IP server. Contoh nyata (IP Indonesia):
#   "Pastikan Anda mendownload aplikasi ini dari Google" → tombol "Login"
# Kata kunci diurutkan dari yang PALING AMAN — jangan pernah klik
# "Batal" / "Cancel" / "No" / "Sign out".
CONSENT_KEYWORDS = [
    # Inggris
    "I Understand", "I understand", "Saya memahami",
    "Allow", "Izinkan",
    "Continue", "Lanjutkan",
    "Confirm", "Konfirmasi",
    "I agree", "Saya setuju",
    "Enter the password again",
    # Halaman nativeapp: tombol konfirmasinya "Login"/"Sign in"
    # (bukan login ulang — ini konfirmasi "Pastikan Anda mendownload
    #  aplikasi ini dari Google", klik Login = lanjutkan)
    "Login", "Sign in", "Masuk",
    "Next", "Berikutnya",
]


def js_click_any(page, texts, exact=False):
    """Klik elemen (button/a) yang teksnya cocok, via JS. Return True jika sukses.
    Teks dengan exact=True dicocokkan persis (untuk tombol pendek seperti
    'Login' supaya tidak salah klik tombol yang mengandung kata itu)."""
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


def js_click_consent(page, timeout_s=0):
    """Klik tombol consent di halaman Google — coba exact-match dulu
    (aman utk tombol pendek), baru partial-match. Return True jika sukses.
    Halaman 'nativeapp' Google punya tombol 'Login' DAN 'Batal' — kalau
    exact match 'login' gagal (mis. teks tombol ada icon), jangan sampai
    partial-match 'login' kena <a> di header. Fallback terakhir tetap
    dibatasi hanya untuk kata kunci yang aman."""
    # Pass 1: exact match
    if js_click_any(page, CONSENT_KEYWORDS, exact=True):
        return True
    # Pass 2: partial match (hanya utk frasa panjang yang pasti unik)
    long_phrases = [
        "I Understand", "I understand", "Saya memahami",
        "Lanjutkan", "Continue", "Izinkan", "Allow",
        "Konfirmasi", "Confirm", "Saya setuju", "I agree",
        "Enter the password again", "Berikutnya", "Next",
    ]
    if js_click_any(page, long_phrases, exact=False):
        return True
    # Pass 3: exact match 'login'/'masuk'/'sign in' — khusus halaman
    # nativeapp; kalau di halaman lain kata ini bisa berbahaya, tapi di
    # loop consent kita SUDAH di halaman yang butuh konfirmasi.
    return js_click_any(page, ["Login", "Masuk", "Sign in"], exact=True)


def click_add_button(page):
    """REVISI: tombol Add di 9Router ada 2 — 'Add' (provider) dan 'Add Model'.
    Selain itu innerText tombolnya 'add\\nAdd' (ikon material ikut kebaca),
    jadi matching dilakukan per-baris teks + exclude 'Add Model'."""
    script = """
    () => {
        const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
        const els = [...document.querySelectorAll('button')];
        const el = els.find(e => {
            const lines = (e.innerText || '').split('\\n')
                .map(l => norm(l)).filter(Boolean);
            // match: ada baris 'add' DAN tidak ada baris 'add model'
            return lines.includes('add') && !lines.includes('add model');
        });
        if (el) { el.click(); return true; }
        return false;
    }
    """
    return page.evaluate(script)


def click_confirm_modal(page):
    """REVISI: tombol modal di 9Router teksnya 'I Understand, Continue'
    (bukan 'I Understand' saja). Termasuk fallback teks lama."""
    return js_click_any(page, [
        "I Understand, Continue",
        "I Understand",
        "I understand",
        "Continue",
        "Confirm",
    ])


# ============================================================
# FUNGSI UTAMA: LOGIN SATU AKUN
# ============================================================
def login_account(account, index, total, headed=False, t=None, proxy=None):
    if t is None:
        t = TIMING["normal"]

    email = account["email"]
    password = account["password"]

    print(f"\n{'=' * 55}")
    print(f" Akun {index + 1}/{total}: {email}")
    print(f"{'=' * 55}")

    print(" [1/6] Membuka Camoufox (anti-detect Firefox)...")
    headless_arg = not headed  # Camoufox: headless=True tanpa masalah

    cam_kwargs = dict(
        headless=headless_arg,
        geoip=True,          # IP konsisten dengan locale (lebih natural)
        humanize=True,       # gerakan mouse/keyboard human-like
        i_know_what_im_doing=True,  # matikan warning camoufox
    )
    if proxy:
        cam_kwargs["proxy"] = {"server": proxy}

    try:
        # headless="virtual" butuh Xvfb; kalau tidak ada, fallback ke headless biasa
        with Camoufox(**cam_kwargs) as browser:
            context = browser.new_context(locale="en-US")
            page = context.new_page()

            # --- [2/6] Navigasi ke halaman Antigravity ---
            print(f" [2/6] Navigasi ke {TARGET_URL}")
            page.goto(TARGET_URL, wait_until="domcontentloaded",
                      timeout=t["page_load"] * 15000)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(t["after_add_click"])

            # --- [3/6] Klik Add ---
            print(" [3/6] Klik tombol 'Add'...")
            if not click_add_button(page):
                raise Exception("Tombol 'Add' tidak ditemukan di halaman provider")
            time.sleep(t["after_add_click"])

            # --- [4/6] Klik modal konfirmasi + tangkap popup Google ---
            # REVISI: pakai context.expect_page() — popup Google ditangkap
            # secara atomic, tidak ada race condition seperti polling tab_ids
            print(" [4/6] Klik 'I Understand, Continue' + tunggu tab Google...")
            try:
                with context.expect_page(timeout=t["popup_timeout"] * 1000) as pop_info:
                    if not click_confirm_modal(page):
                        raise Exception("Tombol konfirmasi modal tidak ditemukan")
                google_page = pop_info.value
            except Exception as e:
                # Fallback: mungkin OAuth kebuka di tab yang sama (redirect)
                if "konfirmasi modal" in str(e):
                    raise
                pages = [p for p in context.pages if "accounts.google.com" in p.url]
                if pages:
                    google_page = pages[0]
                elif "accounts.google.com" in page.url:
                    google_page = page
                else:
                    raise Exception(
                        f"Tab Google Login tidak muncul dalam {t['popup_timeout']} detik"
                    )

            # --- [5/6] Login Google ---
            print(f" [5/6] Login Google: {email}")
            google_page.set_default_timeout(t["password_timeout"] * 1000)
            google_page.wait_for_load_state("domcontentloaded")
            time.sleep(t["google_initial"])

            # Input email
            print("        Input email...")
            email_field = google_page.wait_for_selector(
                "#identifierId", timeout=t["password_timeout"] * 1000)
            email_field.fill(email)
            time.sleep(0.5)

            # Klik Next (email)
            print("        Klik Next (email)...")
            try:
                google_page.click("#identifierNext", timeout=5000)
            except Exception:
                if not js_click_any(google_page, ["Next", "Berikutnya"]):
                    raise Exception("Tombol Next (email) tidak ditemukan")
            time.sleep(t["after_email_next"])

            # Input password (tunggu muncul — kondisi, bukan sleep buta)
            print("        Input password...")
            pw_field = google_page.wait_for_selector(
                'input[type="password"]', timeout=t["password_timeout"] * 1000)
            pw_field.fill(password)
            time.sleep(0.5)

            # Klik Next (password)
            print("        Klik Next (password)...")
            try:
                google_page.click("#passwordNext", timeout=5000)
            except Exception:
                if not js_click_any(google_page, ["Next", "Berikutnya"]):
                    raise Exception("Tombol Next (password) tidak ditemukan")
            time.sleep(t["after_pw_next"])

            # --- [6/6] Handle konfirmasi Google (loop sampai redirect) ---
            print(" [6/6] Handle konfirmasi Google...")
            MAX_STEPS = 15
            for step in range(1, MAX_STEPS + 1):
                time.sleep(t["step_loop_wait"])

                # Cek tab masih hidup
                try:
                    current_url = google_page.url
                except Exception:
                    print("        Tab Google nutup (redirect sukses)")
                    break

                if "google.com" not in current_url:
                    print(f"        Redirect ke: {current_url[:70]}")
                    break

                print(f"        [Step {step}] URL: {current_url[:80]}")

                # REVISI: deteksi error login (Inggris + Indonesia)
                err = google_page.evaluate(
                    """() => {
                        const t = document.body.innerText.toLowerCase();
                        if (t.includes('wrong password') || t.includes('sandi salah')
                            || t.includes('kata sandi salah')
                            || t.includes("couldn't find your google account")
                            || t.includes('tidak menemukan akun google')
                            || t.includes('tidak dapat menemukan akun google')) {
                            return (t.includes('wrong password') || t.includes('sandi salah')
                                || t.includes('kata sandi salah'))
                                ? 'SALAH_PASSWORD' : 'AKUN_TIDAK_DITEMUKAN';
                        }
                        return null;
                    }"""
                )
                if err == "SALAH_PASSWORD":
                    raise Exception("Password salah (Google: Wrong password)")
                if err == "AKUN_TIDAK_DITEMUKAN":
                    raise Exception("Email tidak ditemukan (Google: Account not found)")

                # Workspace TOS: "Welcome to your new account" /
                # "Selamat datang di akun baru Anda"
                if "workspacetermsofservice" in current_url or "speedbump" in current_url:
                    print("        >> Halaman 'Welcome to your new account' terdeteksi")
                    if js_click_consent(google_page):
                        print("        >> 'I understand' diklik!")
                        time.sleep(t["after_pw_next"])
                        continue

                # OAuth consent / nativeapp / Allow (REVISI: pakai
                # js_click_consent — mendukung halaman Google bahasa
                # Indonesia, tombolnya 'Login' bukan 'Continue')
                clicked = js_click_consent(google_page)
                if clicked:
                    print("        >> Tombol consent diklik!")
                    time.sleep(t["step_loop_wait"])
                    continue

                # Centang checkbox yang belum dicentang (beberapa consent butuh ini)
                try:
                    google_page.evaluate(
                        """() => document.querySelectorAll(
                               'input[type="checkbox"]:not(:checked)')
                           .forEach(cb => cb.click())"""
                    )
                except Exception:
                    pass

                print("        >> [WAIT] Tidak ada tombol dikenal, tunggu...")
                time.sleep(t["no_btn_wait"])
            else:
                raise Exception(
                    f"Terlalu banyak step konfirmasi Google ({MAX_STEPS}x) — "
                    "kemungkinan stuck di halaman yang tidak dikenal"
                )

            # --- Verifikasi sukses ---
            print("        Menunggu redirect selesai...")
            time.sleep(t["redirect_wait"])

            still_google = False
            try:
                still_google = "accounts.google.com" in google_page.url
            except Exception:
                pass  # tab sudah tutup = sukses

            if still_google:
                raise Exception(
                    f"Masih di halaman Google ({google_page.url[:60]}) — "
                    "kemungkinan login gagal atau ada step tambahan (2FA/CAPTCHA)"
                )

            # --- SUKSES ---
            print(f"\n [SUKSES] Akun {index + 1}/{total}: {email}")
            remove_account(AKUN_FILE, account["raw"])
            print(" [INFO]   Akun dihapus dari akun.txt")
            time.sleep(t["after_success"])

    except Exception as e:
        print(f"\n [GAGAL] Akun {index + 1}/{total}: {email}")
        print(f"          Error: {str(e)}")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Bot AntiGravity - Auto Add Account ke 9Router (Camoufox)"
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Tampilkan browser (default: headless)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Mode cepat (internet bagus, delay minimal)",
    )
    parser.add_argument(
        "--delay", type=int, default=DELAY_ANTAR_AKUN,
        help=f"Delay antar akun dalam detik (default: {DELAY_ANTAR_AKUN})",
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Path ke file akun (default: akun.txt)",
    )
    parser.add_argument(
        "--proxy", type=str, default=None,
        help="Proxy untuk browser, format: http://host:port",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help=f"Override TARGET_URL (default: {TARGET_URL})",
    )
    args = parser.parse_args()

    if args.url is not None:
        globals()["TARGET_URL"] = args.url
    if args.file is not None:
        globals()["AKUN_FILE"] = args.file

    speed_mode = "fast" if args.fast else "normal"
    t = TIMING[speed_mode]

    print_banner()
    print(f" Target      : {TARGET_URL}")
    print(f" Speed mode  : {speed_mode.upper()}")
    print(f" Headless    : {'TIDAK (headed)' if args.headed else 'YA (default)'}")
    print(f" Delay antar : {args.delay} detik")
    print(f" File akun   : {AKUN_FILE}")
    print()

    accounts = read_accounts(AKUN_FILE)
    if not accounts:
        print("\n [INFO] Tidak ada akun yang bisa diproses.")
        print("        Format akun.txt: email|password (satu baris per akun)")
        sys.exit(1)

    print(f" Total akun: {len(accounts)}\n")

    sukses = 0
    gagal = 0
    for i, account in enumerate(accounts):
        login_account(account, i, len(accounts),
                      headed=args.headed, t=t, proxy=args.proxy)

        remaining = read_accounts(AKUN_FILE)
        if account["raw"] not in [a["raw"] for a in remaining]:
            sukses += 1
        else:
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


if __name__ == "__main__":
    main()
