"""
Histori penjualan bulanan per cabang & produk -- dipakai utk proyeksi "berapa
hari lagi stok Olshopin bakal habis" di menu Update Harga (Olshopin).

Data disimpan teragregasi per (Cabang, Bulan, Produk): total qty terjual +
jumlah hari yang tercakup pada bulan itu (dari rentang tanggal sumber data
yang diupload). Upload ulang utk cabang+bulan yang sama akan MENIMPA data
bulan itu (bukan menumpuk), supaya aman diupload ulang kalau ada koreksi.

Rata-rata harian dihitung dari total qty semua bulan terpilih dibagi TOTAL
hari cakupan semua bulan itu (bukan per-produk) -- supaya produk yang
kebetulan tidak laku sama sekali di suatu bulan tetap kehitung "0" di bulan
itu, tidak bikin rata-ratanya kelihatan lebih tinggi dari yang sebenarnya.

Begitu tab "PenjualanBulanan" dibuat pertama kali (belum pernah ada), otomatis
diisi dari sales_history_seed.json kalau file itu ada -- hasil belajar dari
histori transaksi (data-sulfat/) yang sudah diproses sekali di lokal, supaya
begitu di-deploy proyeksinya langsung jalan tanpa perlu upload manual dulu.
Upload lewat UI tetap jalan seperti biasa utk nambah bulan/cabang berikutnya.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from gsheet_client import get_spreadsheet
from olshopin_sync import norm  # normalizer sama dgn yg dipakai cocokkan nama katalog Olshopin

JAKARTA = ZoneInfo("Asia/Jakarta")
SHEET_NAME = "PenjualanBulanan"
HEADER = ["Cabang", "Bulan", "Produk", "Qty", "Hari", "Timestamp"]
SEED_FILE = os.path.join(os.path.dirname(__file__), "sales_history_seed.json")


def _seed_rows() -> list[dict]:
    if not os.path.exists(SEED_FILE):
        return []
    with open(SEED_FILE, encoding="utf-8") as f:
        seed = json.load(f)
    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {"Cabang": cabang, "Bulan": bulan, "Produk": nama, "Qty": qty,
         "Hari": info["hari"], "Timestamp": ts}
        for cabang, bulan_map in seed.items()
        for bulan, info in bulan_map.items()
        for nama, qty in info["qty"].items()
    ]


def _ws():
    sh = get_spreadsheet()
    titles = {w.title for w in sh.worksheets()}
    if SHEET_NAME not in titles:
        w = sh.add_worksheet(title=SHEET_NAME, rows=100, cols=len(HEADER))
        w.update([HEADER], "A1")
        seed = _seed_rows()
        if seed:
            w.append_rows([[r.get(c, "") for c in HEADER] for r in seed],
                           value_input_option="USER_ENTERED")
        return w
    return sh.worksheet(SHEET_NAME)


def load_all() -> list[dict]:
    return _ws().get_all_records()


def bulan_terupload(cabang: str) -> set:
    """Set bulan ('YYYY-MM') yang sudah ada datanya utk cabang ini."""
    return {r["Bulan"] for r in load_all() if r.get("Cabang") == cabang and r.get("Bulan")}


def replace_month(cabang: str, bulan: str, qty_per_produk: dict, hari: int) -> None:
    """Timpa data (cabang, bulan) ini dengan hasil parse baru.
    qty_per_produk: {nama_produk_asli: qty_total}."""
    ws = _ws()
    existing = ws.get_all_records()
    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    kept = [r for r in existing if not (r.get("Cabang") == cabang and r.get("Bulan") == bulan)]
    new_rows = [
        {"Cabang": cabang, "Bulan": bulan, "Produk": nama, "Qty": qty, "Hari": hari, "Timestamp": ts}
        for nama, qty in qty_per_produk.items()
    ]
    all_rows = kept + new_rows
    # clear() tidak mengecilkan grid sheet, cuma isinya -- lalu tulis header
    # (1 baris, selalu muat) & append_rows utk isinya (auto-grow sheet kalau
    # perlu, pola yang sama dipakai gsheet_client._append_rows), supaya tidak
    # kejegal batas baris awal saat datanya sudah tumbuh lewat dari itu.
    ws.clear()
    ws.update([HEADER], "A1")
    if all_rows:
        ws.append_rows([[r.get(c, "") for c in HEADER] for r in all_rows],
                        value_input_option="USER_ENTERED")


def avg_daily_qty(cabang: str, months: int = 6) -> dict:
    """{nama_norm: (nama_display, rata2_qty_per_hari)} dari <=`months` bulan
    TERBARU yang ada datanya utk cabang ini."""
    rows = [r for r in load_all() if r.get("Cabang") == cabang]
    if not rows:
        return {}

    hari_per_bulan = {}
    for r in rows:
        b = r.get("Bulan")
        if b and b not in hari_per_bulan:
            hari_per_bulan[b] = float(r.get("Hari") or 0)
    bulan_terpilih = set(sorted(hari_per_bulan, reverse=True)[:months])
    total_hari = sum(hari_per_bulan[b] for b in bulan_terpilih)
    if total_hari <= 0:
        return {}

    qty_per_produk = {}  # nama_norm -> [qty_total, nama_display]
    for r in rows:
        if r.get("Bulan") not in bulan_terpilih:
            continue
        nama = str(r.get("Produk", "")).strip()
        if not nama:
            continue
        n = norm(nama)
        qty_per_produk.setdefault(n, [0.0, nama])
        qty_per_produk[n][0] += float(r.get("Qty") or 0)

    return {n: (nama, qty / total_hari) for n, (qty, nama) in qty_per_produk.items()}


def hari_habis(stok, avg_qty_per_hari):
    """Proyeksi berapa hari lagi stok habis. None kalau tidak ada histori
    penjualan (avg 0 / tidak ada data) -- artinya tidak bisa diproyeksikan."""
    if not avg_qty_per_hari or avg_qty_per_hari <= 0:
        return None
    return stok / avg_qty_per_hari
