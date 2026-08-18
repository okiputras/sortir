"""
Histori penjualan bulanan per cabang & produk -- dipakai utk:
  1. Proyeksi Stok Habis (stok real-time Olshopin vs rata-rata penjualan
     harian) -- pakai Periode "Total" (semua jam digabung).
  2. Jadwal Sayur Pagi/Siang (berapa banyak sayur disiapkan jam 4 pagi vs
     ditambah jam 12 siang) -- pakai Periode "Pagi" (<jam 12) / "Siang"
     (>=jam 12), khusus produk yg ada di tab Produk (sayur sortir).

Data disimpan teragregasi per (Cabang, Bulan, Periode, Produk): total qty
terjual + jumlah hari yang tercakup pada bulan itu (dari rentang tanggal
sumber data yang diupload -- SAMA utk ketiga periode, krn ini soal berapa
hari kalender yang datanya ada, bukan soal jam laris/tidaknya). Upload ulang
utk cabang+bulan+periode yang sama akan MENIMPA data itu (bukan menumpuk),
supaya aman diupload ulang kalau ada koreksi.

Rata-rata harian dihitung dari total qty semua bulan terpilih dibagi TOTAL
hari cakupan semua bulan itu (bukan per-produk) -- supaya produk yang
kebetulan tidak laku sama sekali di suatu bulan tetap kehitung "0" di bulan
itu, tidak bikin rata-ratanya kelihatan lebih tinggi dari yang sebenarnya.

trend_avg_qty() menambahkan rata-rata bertren (regresi linear per bulan,
lihat fungsi itu) di atas rata-rata flat -- dipakai supaya cabang yang
penjualannya lagi naik/turun (bukan stagnan) tidak salah diproyeksikan pakai
rata-rata lama yang sudah tidak mewakili kondisi sekarang.

Begitu tab "PenjualanBulanan" dibuat pertama kali (belum pernah ada), otomatis
diisi dari sales_history_seed.json kalau file itu ada -- hasil belajar dari
histori transaksi (data-sulfat/, data-piranha/) yang sudah diproses sekali
di lokal, supaya begitu di-deploy datanya langsung ada tanpa perlu upload
manual dulu. Kalau sheet-nya sudah ada dari SEBELUM Periode Pagi/Siang
ditambahkan (jadi cuma punya baris Total), panggil ensure_periode_seeded()
utk isi susulan -- lihat fungsi itu. Upload lewat UI tetap jalan seperti
biasa utk nambah bulan/cabang berikutnya (ketiga periode sekaligus).
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from gsheet_client import get_spreadsheet
from olshopin_sync import norm  # normalizer sama dgn yg dipakai cocokkan nama katalog Olshopin

JAKARTA = ZoneInfo("Asia/Jakarta")
SHEET_NAME = "PenjualanBulanan"
# "Periode" sengaja di PALING AKHIR (bukan disisipkan di tengah): baris lama
# dari sblm kolom ini ada (6 kolom, urutan Cabang..Timestamp) tetap kebaca
# benar apa adanya (zip berhenti di kolom ke-6, Periode dianggap kosong ->
# "Total" lewat _periode_of) -- kalau disisipkan di tengah, baris lama jadi
# geser kolom dan datanya rusak waktu dibaca ulang.
HEADER = ["Cabang", "Bulan", "Produk", "Qty", "Hari", "Timestamp", "Periode"]
SEED_FILE = os.path.join(os.path.dirname(__file__), "sales_history_seed.json")


def _periode_of(r: dict) -> str:
    return r.get("Periode") or "Total"  # baris lama (sblm kolom ini ada) = Total


def _load_seed_json() -> dict:
    if not os.path.exists(SEED_FILE):
        return {}
    with open(SEED_FILE, encoding="utf-8") as f:
        return json.load(f)


def _seed_rows() -> list[dict]:
    seed = _load_seed_json()
    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {"Cabang": cabang, "Bulan": bulan, "Periode": periode, "Produk": nama,
         "Qty": qty, "Hari": info["hari"], "Timestamp": ts}
        for cabang, bulan_map in seed.items()
        for bulan, periode_map in bulan_map.items()
        for periode, info in periode_map.items()
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


def ensure_periode_seeded(cabang: str) -> None:
    """Backfill baris Pagi/Siang dari seed file utk cabang ini, KALAU sheet-nya
    sudah ada dari sebelum kolom Periode ditambahkan (jadi belum pernah punya
    baris Pagi/Siang sama sekali). Aman dipanggil berkali-kali -- begitu ada
    baris Pagi/Siang (dari seed ataupun upload manual), tidak akan menimpa
    atau menambah dobel lagi."""
    rows = load_all()
    if any(r.get("Cabang") == cabang and _periode_of(r) in ("Pagi", "Siang") for r in rows):
        return
    seed_cabang = _load_seed_json().get(cabang, {})
    if not seed_cabang:
        return
    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    new_rows = []
    for bulan, periode_map in seed_cabang.items():
        for periode in ("Pagi", "Siang"):
            info = periode_map.get(periode)
            if not info:
                continue
            for nama, qty in info["qty"].items():
                new_rows.append({"Cabang": cabang, "Bulan": bulan, "Periode": periode,
                                  "Produk": nama, "Qty": qty, "Hari": info["hari"], "Timestamp": ts})
    if new_rows:
        ws = _ws()
        ws.update([HEADER], "A1")  # refresh header (sheet lama mungkin blm punya kolom Periode)
        ws.append_rows([[r.get(c, "") for c in HEADER] for r in new_rows],
                        value_input_option="USER_ENTERED")


def bulan_terupload(cabang: str, periode: str = "Total") -> set:
    """Set bulan ('YYYY-MM') yang sudah ada datanya utk cabang+periode ini."""
    return {r["Bulan"] for r in load_all()
            if r.get("Cabang") == cabang and _periode_of(r) == periode and r.get("Bulan")}


def replace_month(cabang: str, bulan: str, qty_per_produk: dict, hari: int,
                   periode: str = "Total") -> None:
    """Timpa data (cabang, bulan, periode) ini dengan hasil parse baru --
    periode lain (mis. Total tetap utuh saat yang ditimpa cuma Pagi) tidak
    kesenggol. qty_per_produk: {nama_produk_asli: qty_total}."""
    ws = _ws()
    existing = ws.get_all_records()
    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    kept = [r for r in existing
            if not (r.get("Cabang") == cabang and r.get("Bulan") == bulan
                    and _periode_of(r) == periode)]
    new_rows = [
        {"Cabang": cabang, "Bulan": bulan, "Periode": periode, "Produk": nama,
         "Qty": qty, "Hari": hari, "Timestamp": ts}
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


def avg_daily_qty(cabang: str, months: int = 6, periode: str = "Total",
                   exclude_bulan=None) -> dict:
    """{nama_norm: (nama_display, rata2_qty_per_hari)} dari <=`months` bulan
    TERBARU yang ada datanya utk cabang+periode ini (bulan di `exclude_bulan`
    tidak ikut dipilih sama sekali, mis. buat buang bulan puasa/anomali)."""
    exclude_bulan = set(exclude_bulan or ())
    rows = [r for r in load_all() if r.get("Cabang") == cabang and _periode_of(r) == periode]
    if not rows:
        return {}

    hari_per_bulan = {}
    for r in rows:
        b = r.get("Bulan")
        if b and b not in exclude_bulan and b not in hari_per_bulan:
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


def monthly_series(cabang: str, months: int = 6, periode: str = "Total",
                    exclude_bulan=None) -> dict:
    """{nama_norm: (nama_display, [(bulan_index, rata2_qty_per_hari_bulan_itu), ...])}
    dari <=`months` bulan TERBARU (dikurangi `exclude_bulan`), diurutkan
    kronologis lama->baru (bulan_index 0,1,2,...) -- dipakai regresi tren.
    Tiap bulan yg dipakai SELALU ada titiknya per produk (0 kalau produk itu
    nol laku bulan itu), sama spt prinsip avg_daily_qty -- bulan sepi tetap
    kehitung, bukan diabaikan begitu saja dari garis trennya."""
    exclude_bulan = set(exclude_bulan or ())
    rows = [r for r in load_all() if r.get("Cabang") == cabang and _periode_of(r) == periode]
    if not rows:
        return {}

    hari_per_bulan = {}
    for r in rows:
        b = r.get("Bulan")
        if b and b not in exclude_bulan and b not in hari_per_bulan:
            hari_per_bulan[b] = float(r.get("Hari") or 0)
    bulan_urut = sorted(sorted(hari_per_bulan, reverse=True)[:months])  # kronologis lama->baru
    if not bulan_urut:
        return {}
    bulan_terpilih = set(bulan_urut)
    idx_bulan = {b: i for i, b in enumerate(bulan_urut)}

    qty_per_produk_per_bulan = {}  # nama_norm -> [nama_display, {bulan: qty}]
    for r in rows:
        b = r.get("Bulan")
        if b not in bulan_terpilih:
            continue
        nama = str(r.get("Produk", "")).strip()
        if not nama:
            continue
        n = norm(nama)
        slot = qty_per_produk_per_bulan.setdefault(n, [nama, {}])
        slot[1][b] = slot[1].get(b, 0.0) + float(r.get("Qty") or 0)

    out = {}
    for n, (nama, qty_bulan) in qty_per_produk_per_bulan.items():
        # Buang bulan SEBELUM kemunculan pertama produk ini -- itu artinya
        # produknya belum ada/belum dijual, bukan "terjual 0" (beda makna).
        # Bulan kosong SETELAH kemunculan pertama tetap dihitung sbg titik 0,
        # itu histori asli (produk pernah ada tapi lagi sepi/nol bulan itu).
        bulan_mulai = min(qty_bulan)
        bulan_dipakai = [b for b in bulan_urut if b >= bulan_mulai]
        seri = [(idx_bulan[b], qty_bulan.get(b, 0.0) / hari_per_bulan[b]) for b in bulan_dipakai]
        out[n] = (nama, seri)
    return out


def _linreg_nilai_terakhir(titik):
    """titik: [(x, y), ...]. Regresi least-squares sederhana (tanpa numpy),
    kembalikan (y_prediksi_di_x_terbesar, slope) -- y DIHALUSKAN di titik
    TERAKHIR yg diamati, BUKAN diekstrapolasi lewat data yg ada (lebih aman,
    tidak gampang meleset kalau trennya sebenarnya tidak linear terus).
    None kalau titik x-nya kurang dari 2 nilai berbeda (regresi tak bermakna)."""
    xs_unik = set(x for x, _ in titik)
    if len(xs_unik) < 2:
        return None
    n = len(titik)
    mean_x = sum(x for x, _ in titik) / n
    mean_y = sum(y for _, y in titik) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in titik)
    den = sum((x - mean_x) ** 2 for x, _ in titik)
    if den == 0:
        return None
    slope = num / den
    intercept = mean_y - slope * mean_x
    x_terakhir = max(x for x, _ in titik)
    return max(0.0, intercept + slope * x_terakhir), slope


def trend_avg_qty(cabang: str, months: int = 6, periode: str = "Total",
                   exclude_bulan=None, min_bulan_tren: int = 3) -> dict:
    """{nama_norm: (nama_display, rata2_flat, rata2_tren, slope_per_bulan)}.

    rata2_flat = sama persis dgn avg_daily_qty() (total qty / total hari).
    rata2_tren = hasil regresi linear di bulan TERAKHIR yg dipakai, supaya
    produk yg lagi tren naik/turun tidak ketarik ke rata-rata lama yg sudah
    tidak relevan (mis. cabang yang jualannya lagi tumbuh, 7 bulan lalu vs
    sekarang beda jauh -- rata-rata flat meremehkan kondisi sekarang).
    Fallback ke rata2_flat (slope=0.0) kalau datanya < `min_bulan_tren`
    bulan -- regresi butuh cukup titik biar tidak asal nebak dari noise."""
    flat_map = avg_daily_qty(cabang, months=months, periode=periode, exclude_bulan=exclude_bulan)
    seri_map = monthly_series(cabang, months=months, periode=periode, exclude_bulan=exclude_bulan)

    out = {}
    for n, (nama, rata2_flat) in flat_map.items():
        seri = seri_map.get(n, (nama, []))[1]
        hasil = _linreg_nilai_terakhir(seri) if len(seri) >= min_bulan_tren else None
        if hasil is None:
            out[n] = (nama, rata2_flat, rata2_flat, 0.0)
        else:
            nilai_tren, slope = hasil
            out[n] = (nama, rata2_flat, nilai_tren, slope)
    return out


def hari_habis(stok, avg_qty_per_hari):
    """Proyeksi berapa hari lagi stok habis. None kalau tidak ada histori
    penjualan (avg 0 / tidak ada data) -- artinya tidak bisa diproyeksikan."""
    if not avg_qty_per_hari or avg_qty_per_hari <= 0:
        return None
    return stok / avg_qty_per_hari
