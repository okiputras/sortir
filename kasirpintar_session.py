"""
Ambil data Kasir Pintar lewat sesi login yang DIBUKA MANUAL oleh owner.

Kenapa manual: halaman login kasirpintar.co.id dijaga Cloudflare Turnstile.
Turnstile itu kontrol akses yang sengaja dipasang Kasir Pintar; script ini
TIDAK menembusnya -- browser-nya dibuka biasa (bukan stealth/anti-detect),
owner yang login & menyelesaikan Turnstile sendiri seperti biasa. Setelah itu
cookie sesinya disimpan, dan penarikan data berikutnya jalan otomatis pakai
sesi itu sampai kedaluwarsa (lalu tinggal `login` lagi).

Password TIDAK disimpan di mana pun oleh script ini -- yang tersimpan cuma
cookie sesi di kasirpintar_state.json (gitignored, chmod 600).

Butuh: pip install playwright && python3 -m playwright install firefox

Pakai:
    python3 kasirpintar_session.py login      # buka browser, login sendiri
    python3 kasirpintar_session.py cek        # tes apakah sesi masih hidup
    python3 kasirpintar_session.py buka <url> # buka halaman apa pun pakai sesi itu
"""
import json
import os
import sys

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kasirpintar_state.json")
BASE = "https://kasirpintar.co.id"


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright belum terpasang. Jalankan:\n"
                 "  pip3 install --user playwright && python3 -m playwright install firefox")
    return sync_playwright


def login():
    """Buka browser normal, owner login sendiri (termasuk Turnstile), lalu
    simpan cookie sesinya. Script nunggu sampai URL-nya pindah dari /login."""
    with _playwright()() as p:
        browser = p.firefox.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/login")
        print("Browser terbuka. Silakan login sendiri (termasuk verifikasi Cloudflare).")
        print("Script nunggu sampai kamu masuk ke dashboard...")
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=300_000)
        except Exception:
            sys.exit("\nTimeout 5 menit -- belum masuk dashboard. Coba ulangi.")
        ctx.storage_state(path=STATE)
        os.chmod(STATE, 0o600)
        print(f"\nBerhasil. Sesi disimpan ke {STATE} (chmod 600).")
        print(f"Halaman sekarang: {page.url}")
        browser.close()


def _ctx(p, headless=True):
    if not os.path.exists(STATE):
        sys.exit(f"Belum ada sesi tersimpan. Jalankan dulu:  python3 {sys.argv[0]} login")
    browser = p.firefox.launch(headless=headless)
    return browser, browser.new_context(storage_state=STATE)


def cek():
    """Tes apakah cookie sesinya masih dianggap login."""
    with _playwright()() as p:
        browser, ctx = _ctx(p)
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        url = page.url
        masih = "/login" not in url
        print(("MASIH LOGIN" if masih else "SESI HABIS -- jalankan 'login' lagi") + f"  ({url})")
        print(f"Judul halaman: {page.title()}")
        browser.close()
        return masih


def buka(url, simpan=None):
    """Buka satu URL pakai sesi tersimpan, cetak teksnya (atau simpan HTML-nya)."""
    if not url.startswith("http"):
        url = BASE + ("" if url.startswith("/") else "/") + url
    with _playwright()() as p:
        browser, ctx = _ctx(p)
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        if "/login" in page.url:
            sys.exit("Dilempar balik ke halaman login -- sesinya sudah habis, jalankan 'login' lagi.")
        print(f"URL   : {page.url}\nJudul : {page.title()}\n")
        if simpan:
            with open(simpan, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"HTML disimpan ke {simpan}")
        else:
            print(page.inner_text("body")[:3000])
        browser.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        login()
    elif cmd == "cek":
        cek()
    elif cmd == "buka" and len(sys.argv) > 2:
        buka(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print(__doc__)
