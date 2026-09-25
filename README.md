# AntiGravity Bot — Auto Add Account ke 9Router (Linux/Server)

Bot otomatis untuk menambahkan akun Google (Antigravity) ke 9Router.
Dibangun dengan **Python + Camoufox** (Firefox anti-detect berbasis Playwright).

> **Versi ini adalah revisi Camoufox** — menggantikan versi lama berbasis
> Chrome/DrissionPage yang punya bug WebSocket saat headless.

---

## Daftar Isi

- [Requirements](#requirements)
- [Instalasi](#instalasi)
- [Penggunaan](#penggunaan)
- [Opsi Command Line](#opsi-command-line)
- [Fitur revisi Camoufox](#fitur-revisi-camoufox)
- [Cara kerja bot](#cara-kerja-bot)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Python 3.9+ (Linux / Mac / WSL)
- Koneksi internet
- 9Router yang bisa diakses (default: `https://ai.smkdata.sch.id`)
- **Tidak perlu Chrome/Chromium** — Camoufox mengunduh browser-nya sendiri

## Instalasi

```bash
chmod +x setup.sh
./setup.sh
```

`setup.sh` otomatis:
- Membuat virtual environment `.venv/`
- Menginstall `camoufox[geoip]`
- Mengunduh browser Camoufox (sekali saja, ±150 MB)

Manual:

```bash
python3 -m venv .venv
.venv/bin/pip install "camoufox[geoip]"
.venv/bin/python -m camoufox fetch
```

## Penggunaan

### 1. Isi akun

Buat file `akun.txt` di folder yang sama dengan `bot.py`:

```
email@gmail.com|password123
akun2@gmail.com|password456
```

> Format: `email|password` (dipisah `|`), satu baris per akun.
> Akun yang sukses **otomatis dihapus** dari file ini.

### 2. Jalankan

```bash
# headless (default — stabil di server tanpa display)
.venv/bin/python bot.py

# lihat browser (butuh display / Xvfb)
.venv/bin/python bot.py --headed

# mode cepat (internet bagus)
.venv/bin/python bot.py --fast

# delay 10 detik antar akun
.venv/bin/python bot.py --delay 10

# override URL 9Router
.venv/bin/python bot.py --url https://server-lain.com/dashboard/providers/antigravity
```

## Opsi Command Line

| Opsi | Default | Keterangan |
|------|---------|------------|
| `--headed` | headless | Tampilkan jendela browser |
| `--fast` | normal | Delay minimal di halaman Google |
| `--delay` | `3` | Jeda antar akun (detik) |
| `--file` | `akun.txt` | Path file akun |
| `--proxy` | - | Proxy browser, format `http://host:port` |
| `--url` | URL Antigravity | Override halaman target 9Router |

## Fitur revisi Camoufox

- **Camoufox** (Firefox anti-detect) menggantikan Chrome/DrissionPage —
  headless stabil tanpa bug WebSocket
- Fix salah klik tombol **"Add Model"** — kini exact-match tombol **"Add"**
- Fix tombol modal konfirmasi **"I Understand, Continue"** (teks persis 9Router)
- Popup Google ditangkap via `context.expect_page()` — andal, tanpa race condition
- Timeout berbasis kondisi (`wait_for_selector`), bukan sleep buta
- Consent handler mendukung halaman Google **bahasa Inggris & Indonesia**
  (termasuk tombol "Login" di halaman "Pastikan Anda mendownload aplikasi ini dari Google")
- Deteksi error login EN+ID: salah password / akun tidak ditemukan → gagal cepat
- Error handling per-akun: 1 gagal, lanjut ke berikutnya

## Cara kerja bot

1. Buka halaman provider Antigravity di dashboard 9Router
2. Klik **Add** → modal **I Understand, Continue**
3. Tab Google Login terbuka → isi email → Next → password → Next
4. Handle halaman konfirmasi Google secara otomatis (loop):
   - "Welcome to your new account" (Workspace TOS) → klik "I understand"
   - "Pastikan Anda mendownload aplikasi ini dari Google" → klik "Login"/"Continue"
   - OAuth consent → klik "Allow"/"Izinkan"
5. Sukses = akun dihapus dari `akun.txt`, lanjut akun berikutnya

> **Catatan:** alur callback OAuth 9Router mengarah ke `localhost` komputer
> user. Jika bot dijalankan di **server/VPS** (bukan komputer yang menjalankan
> 9Router), lihat repo
> [9router-antigravity-bot-windows](https://github.com/cimeng15/9router-antigravity-bot-windows)
> sebagai referensi pendekatan **API-driven** (`bot_api.py`) yang tidak butuh
> callback localhost.

## Troubleshooting

**"Camoufox belum terinstall"** → jalankan `./setup.sh`, atau manual:
`.venv/bin/python -m camoufox fetch`

**"Tab Google tidak muncul"** → jalankan dengan `--headed` untuk melihat
prosesnya; pastikan URL target benar dan dashboard 9Router bisa dibuka.

**"Password salah"** → cek format `akun.txt` (`email|password`, tanpa spasi).

**CAPTCHA muncul** → naikkan delay (`--delay 10`), jangan terlalu banyak
akun sekaligus, jalankan dengan `--headed`.

**Stuck di halaman Google** → akun dengan 2FA tidak bisa diproses otomatis.

---

## Keamanan

- **JANGAN** commit / bagikan `akun.txt` (sudah di-ignore git)
- Password hanya dipakai untuk login Google, tidak dikirim ke pihak lain
- Gunakan hanya pada 9Router milik sendiri
