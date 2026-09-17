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

CATATAN (Sep 2026): mode `login` di bawah TERNYATA GAGAL di kasirpintar.co.id
-- Turnstile menolak browser bawaan Playwright (terdeteksi otomasi lewat
navigator.webdriver/marionette) walaupun yang login manusia betulan. Jadi
pakai mode `impor` : login di browser harian sendiri, lalu salin cookie
sesinya ke sini. Sesi itu dibuat manusia lewat browser normal -- script cuma
memakai ulang, bukan menembus apa-apa.

Butuh: pip install playwright && python3 -m playwright install firefox

Pakai:
    python3 kasirpintar_session.py impor      # tempel cookie dari browser sendiri
    python3 kasirpintar_session.py cek        # tes apakah sesi masih hidup
    python3 kasirpintar_session.py barang     # unduh DATA_BARANG*.xls (master produk)
    python3 kasirpintar_session.py buka <url> # buka halaman apa pun pakai sesi itu
    python3 kasirpintar_session.py login      # (biasanya gagal, lihat catatan di atas)
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


def impor():
    """Pakai sesi yang dibuat di browser HARIAN sendiri.

    Langkahnya (sekali saja tiap sesi habis):
      1. Login ke kasirpintar.co.id di Chrome/Firefox biasa seperti biasanya.
      2. Buka DevTools (Cmd+Option+I) -> tab Application (Chrome) atau
         Storage (Firefox) -> Cookies -> https://kasirpintar.co.id
      3. Salin NAMA dan VALUE tiap cookie, tempel di sini satu per baris
         dengan format  nama=value
      4. Tekan Enter dua kali kalau sudah selesai.
    """
    print(impor.__doc__)
    print("Tempel cookie (format: nama=value), Enter 2x kalau selesai:\n")
    baris = []
    kosong = 0
    while kosong < 1:
        try:
            l = input().strip()
        except EOFError:
            break
        if not l:
            kosong += 1
            continue
        baris.append(l)
    cookies = []
    for l in baris:
        if "=" not in l:
            print(f"  dilewati (tak ada '='): {l[:40]}")
            continue
        nama, val = l.split("=", 1)
        cookies.append({"name": nama.strip(), "value": val.strip(),
                        "domain": ".kasirpintar.co.id", "path": "/"})
    if not cookies:
        sys.exit("Tidak ada cookie yang terbaca.")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f)
    os.chmod(STATE, 0o600)
    print(f"\n{len(cookies)} cookie disimpan ke {STATE} (chmod 600).")
    print("Sekarang tes:  python3 kasirpintar_session.py cek")


def _ctx(p, headless=True):
    if not os.path.exists(STATE):
        sys.exit(f"Belum ada sesi tersimpan. Jalankan dulu:  python3 {sys.argv[0]} login")
    browser = p.firefox.launch(headless=headless)
    return browser, browser.new_context(storage_state=STATE)


def _simpan_sesi(ctx):
    """Tulis balik cookie hasil request terakhir. Server memutar nilai
    laravel_session tiap request, dan sesinya rolling (tiap aktivitas
    memperpanjang umur) -- jadi menyimpan yang terbaru bikin sesi bertahan
    selama script dipakai rutin, tanpa perlu ambil cookie manual lagi."""
    try:
        ctx.storage_state(path=STATE)
        os.chmod(STATE, 0o600)
    except Exception as e:
        print(f"  (peringatan: sesi gagal disimpan ulang -- {e})")


def cek():
    """Tes apakah cookie sesinya masih dianggap login."""
    with _playwright()() as p:
        browser, ctx = _ctx(p)
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        url = page.url
        masih = "/login" not in url
        if masih:
            _simpan_sesi(ctx)
        print(("MASIH LOGIN" if masih else "SESI HABIS -- jalankan 'login' lagi") + f"  ({url})")
        print(f"Judul halaman: {page.title()}")
        browser.close()
        return masih


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
HAL_BARANG = f"{BASE}/account/import_edit_products_v2"
API_BARANG = f"{BASE}/account/export_products_v2"


def barang(keluar=None):
    """Unduh master produk (DATA_BARANG*.xls) -- file yang sama persis dengan
    tombol 'Export Barang' di halaman Export/Import Edit Produk.

    Payload-nya disadap dari request asli halaman itu; dua field ini wajib
    persis, kalau tidak server cuma balas "Error Data":
      range_selected_product = "0~0"          (artinya semua baris)
      choosen_order          = "kode_barang"
    """
    from datetime import datetime
    with _playwright()() as p:
        browser = p.firefox.launch(headless=True)
        ctx = browser.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")
        page = ctx.new_page()
        page.goto(HAL_BARANG, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        if "/login" in page.url:
            sys.exit("Sesi sudah habis -- ambil cookie baru lalu jalankan 'impor' lagi.")
        tok = page.evaluate(
            "document.querySelector('meta[name=csrf-token]')?.content"
            " || document.querySelector('form input[name=_token]')?.value")
        if not tok:
            sys.exit("CSRF token tidak ketemu di halaman.")
        payload = {"kategori": "[]", "range_selected_product": "0~0", "choosen_state": "all",
                   "choosen_order": "kode_barang", "by_zero": "false",
                   "export_type": "product", "data_stok": False}
        r = ctx.request.post(API_BARANG, data=json.dumps(payload), headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": tok, "Referer": HAL_BARANG})
        body = r.body()
        _simpan_sesi(ctx)
        browser.close()

    if body[:4] != b"\xd0\xcf\x11\xe0" and body[:2] != b"PK":
        sys.exit(f"Bukan file Excel (status {r.status}): {body[:200].decode('utf-8', 'ignore')}")
    nama = keluar or f"DATA_BARANG_{datetime.now():%Y-%m-%d_%H%M%S}.xls"
    with open(nama, "wb") as f:
        f.write(body)
    print(f"Tersimpan: {nama}  ({len(body):,} byte)".replace(",", "."))
    try:
        import xlrd
        sh = xlrd.open_workbook(nama, ignore_workbook_corruption=True).sheet_by_name("barang")
        print(f"  sheet 'barang': {sh.nrows - 2} produk")
    except Exception:
        pass
    return nama


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
    elif cmd == "impor":
        impor()
    elif cmd == "cek":
        cek()
    elif cmd == "barang":
        barang(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "buka" and len(sys.argv) > 2:
        buka(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print(__doc__)
