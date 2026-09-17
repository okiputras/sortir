"""
Tarik laporan penjualan per barang dari Kasir Pintar, lewat sesi yang sudah login.

Sumbernya endpoint yang dipakai halaman laporan itu sendiri untuk mengisi
tabelnya:

    GET /account/laporan_penjualan_barang_filter_ajax/<mulai>/<akhir>

CATATAN soal tombol "Download Laporan" di halaman itu: tombol tersebut
menembak /account/download_laporan_penjualan_barang/<mulai>/<akhir>, TAPI
tautannya baru dipasang setelah captcha diverifikasi. Captcha itu kontrol
anti-otomasi milik Kasir Pintar dan TIDAK ditembus di sini. Script ini
memakai endpoint tabel biasa -- angka yang sama, yang memang sudah dikirim
ke browser tanpa tantangan apa pun begitu halamannya dibuka.

Batas yang ditemukan lewat percobaan: kalau hasilnya terlalu besar server
membalas {"success":false,"data":[]} alih-alih error. 8 hari (792 baris)
masih lolos, 17 hari tidak. Jadi rentangnya dipotong, dan tiap potongan yang
ditolak dibelah dua sampai muat, lalu hasilnya dijumlahkan per produk.

Pakai:
    KP_STATE=kasirpintar_state_piranha.json \
    python3 kasirpintar_laporan.py 2026-09-01 2026-09-17 -o laporan_sep.csv
"""
import argparse
import csv
import os
import sys
from datetime import date, timedelta

BASE = "https://kasirpintar.co.id"
STATE = os.environ.get("KP_STATE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "kasirpintar_state.json")
HAL = f"{BASE}/account/laporan_penjualan_barang_filter"
API = f"{BASE}/account/laporan_penjualan_barang_filter_ajax"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def _tanggal(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"tanggal harus YYYY-MM-DD, bukan '{s}'")


def _ambil(ctx, a, b):
    """Satu rentang. Balikin list baris, atau None kalau server menolak
    karena hasilnya kelewat besar."""
    r = ctx.request.get(f"{API}/{a}/{b}", headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": HAL}, timeout=120_000)
    if r.status != 200:
        raise RuntimeError(f"status {r.status} untuk {a}..{b}")
    d = r.json()
    if d.get("success") is False:
        return None
    return d.get("data", [])


def _potong(ctx, a, b, catat):
    """Ambil a..b, belah dua tiap kali ditolak sampai muat."""
    hasil = _ambil(ctx, a, b)
    if hasil is not None:
        catat(f"  {a} .. {b}: {len(hasil)} baris")
        return hasil
    if a == b:
        catat(f"  {a}: DITOLAK walau cuma satu hari -- dilewati")
        return []
    tengah = a + (b - a) // 2
    catat(f"  {a} .. {b}: terlalu besar, dibelah")
    return _potong(ctx, a, tengah, catat) + _potong(ctx, tengah + timedelta(days=1), b, catat)


def tarik(mulai, akhir, keluar, hari=7, diam=False):
    from playwright.sync_api import sync_playwright

    def catat(s):
        if not diam:
            print(s, flush=True)

    if not os.path.exists(STATE):
        sys.exit(f"Belum ada sesi: {STATE}\nIsi dulu lewat kasirpintar_session.py impor")

    baris = []
    with sync_playwright() as pw:
        br = pw.firefox.launch(headless=True)
        ctx = br.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")
        # Halaman dibuka dulu supaya sesinya dianggap aktif seperti pemakaian biasa.
        pg = ctx.new_page()
        pg.goto(HAL, wait_until="domcontentloaded", timeout=60_000)
        pg.wait_for_timeout(2500)
        if "/login" in pg.url:
            br.close()
            sys.exit("Sesi habis -- perbarui cookie lalu jalankan lagi.")

        catat(f"--- {mulai} sampai {akhir}, potongan {hari} hari ---")
        t = mulai
        while t <= akhir:
            u = min(t + timedelta(days=hari - 1), akhir)
            baris += _potong(ctx, t, u, catat)
            t = u + timedelta(days=1)
        try:
            ctx.storage_state(path=STATE)
            os.chmod(STATE, 0o600)
        except Exception:
            pass
        br.close()

    # Rentang dipotong-potong, jadi satu produk bisa muncul beberapa kali.
    # Qty dan nilai dijumlahkan; kolom lain diambil dari kemunculan pertama.
    # Kolom yang nilainya harus DIJUMLAHKAN, bukan diambil salah satu. Kolom
    # nyatanya: kode_barang, nama_barang, jumlah, total, untung.
    JUMLAH = ("jumlah", "qty", "total", "omzet", "untung", "laba", "profit",
              "keuntungan", "sub_total")
    gabung = {}
    for b in baris:
        k = str(b.get("kode_barang", "")).strip()
        if k not in gabung:
            gabung[k] = dict(b)
            continue
        for kol, v in b.items():
            if any(j in kol.lower() for j in JUMLAH):
                try:
                    gabung[k][kol] = float(gabung[k].get(kol) or 0) + float(v or 0)
                except (TypeError, ValueError):
                    pass

    hasil = sorted(gabung.values(), key=lambda r: str(r.get("nama_barang", "")))
    if not hasil:
        sys.exit("Tidak ada data pada rentang itu.")
    kolom = list(hasil[0])
    with open(keluar, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=kolom, extrasaction="ignore")
        w.writeheader()
        w.writerows(hasil)
    catat(f"\n{len(baris)} baris mentah -> {len(hasil)} produk unik")
    catat(f"Tersimpan: {keluar}")
    return hasil


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mulai", type=_tanggal, help="tanggal awal, YYYY-MM-DD")
    ap.add_argument("akhir", type=_tanggal, help="tanggal akhir, YYYY-MM-DD")
    ap.add_argument("-o", "--keluar", default="laporan_penjualan.csv")
    ap.add_argument("--hari", type=int, default=7, help="besar potongan (default 7)")
    a = ap.parse_args()
    if a.akhir < a.mulai:
        sys.exit("Tanggal akhir lebih awal dari tanggal mulai.")
    tarik(a.mulai, a.akhir, a.keluar, a.hari)
