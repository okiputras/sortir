"""
Sinkronisasi harga & stok produk dari katalog Olshopin (toko AIRIN FRESH MART).

Tiap cabang toko fisik punya toko Olshopin sendiri (TID beda) dgn stok yg
independen -- SULFAT dan PIRANHA BUKAN satu katalog gabungan. Lihat CABANG_TID.

Alur:
  fetch_catalog(tid) -> {nama_barang: (harga_jual, stok)} dari semua halaman katalog
                         toko dgn TID itu (default: toko SULFAT, dipakai sinkronisasi
                         harga di tab Produk -- lihat modul ini apa adanya sejak awal)
  load_mapping(sh)   -> mapping manual {nama_tab -> nama_olshopin} dari tab ProdukMapping
  plan_updates(...)  -> daftar rencana perubahan per baris tab Produk (termasuk stok
                         Olshopin per produk, dipakai utk proyeksi stok habis)
  apply_updates(ws, plan) -> tulis harga_jual_edit & harga_beli_edit ke sheet

Aturan harga beli (sesuai permintaan):
  harga_beli = harga_jual - 4000  bila barang "kg an"
  harga_beli = harga_jual - 500   bila barang satuan
  (tidak boleh negatif -> minimal 0)
"""
import re
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

CABANG_TID = {
    "SULFAT": "1543660",
    "PIRANHA": "2420073",
}
OLSHOP_TID = CABANG_TID["SULFAT"]  # default: dipakai sinkronisasi harga tab Produk
CATALOG_LIMIT = 5000          # ?limit= -> ambil semua produk dalam 1 request
POTONG_KG = 4000
POTONG_SATUAN = 500
_UA = {"User-Agent": "Mozilla/5.0"}
_RE_SHOP = re.compile(r"window\.__SHOP_HOME__\s*=\s*(\{.*?\});", re.S)


# ---------------- fetch katalog ----------------
def _fetch_barangs(url):
    req = urllib.request.Request(url, headers=_UA)
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    m = _RE_SHOP.search(html)
    if not m:
        return {"data": [], "last_page": 1, "total": 0}
    return json.loads(m.group(1))["barangs"]


def _entry(x):
    return (x["harga_jual"], int(x.get("stok") or 0))


def fetch_catalog(tid=OLSHOP_TID):
    """Ambil seluruh katalog toko `tid` -> dict {nama_barang: (harga_jual, stok)}.

    Cara cepat: 1 request pakai ?limit= (server mengembalikan semua produk).
    Fallback: paginasi 20/halaman (paralel) bila limit tidak lengkap."""
    base = f"https://olshopin.com/t/{tid}"
    try:
        b = _fetch_barangs(f"{base}?limit={CATALOG_LIMIT}")
        data = b.get("data", [])
        total = int(b.get("total") or 0)
        if data and len(data) >= total:
            return {x["nama_barang"]: _entry(x) for x in data}
    except Exception:
        pass

    # fallback paginasi
    first = _fetch_barangs(f"{base}?page=1")
    last = int(first.get("last_page", 1) or 1)
    catalog = {x["nama_barang"]: _entry(x) for x in first.get("data", [])}
    if last > 1:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_fetch_barangs, f"{base}?page={p}") for p in range(2, last + 1)]
            for f in as_completed(futs):
                try:
                    for x in f.result().get("data", []):
                        catalog[x["nama_barang"]] = _entry(x)
                except Exception:
                    pass
    return catalog


# ---------------- normalisasi & aturan ----------------
def norm(s):
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    s = re.sub(r"\bkgan\b", "kg an", s)      # samakan 'kgan' dgn 'kg an' (anti-typo)
    return s


def _strip_kg(n):
    return re.sub(r"\s+", " ", re.sub(r"\b(kg\s*an|kgan|per\s*kg|/kg|kg)\b", "", n)).strip()


def is_kg(nama):
    return bool(re.search(r"\bkg|\dkg", norm(nama)))


def hitung_beli(harga_jual, kg):
    try:
        hj = int(round(float(harga_jual)))
    except (TypeError, ValueError):
        return 0
    return max(0, hj - (POTONG_KG if kg else POTONG_SATUAN))


# ---------------- pencocokan & rencana ----------------
# Override diambil dari tab Produk itu sendiri:
#   kolom D = tipe          (kg / satuan; kosong -> auto-deteksi dari nama)
#   kolom E = nama_olshopin (nama katalog; kosong -> auto-cocokkan dari nama)
def _index(catalog):
    idx = {}
    for nama, (hj, stok) in catalog.items():
        idx[norm(nama)] = (nama, hj, stok)
    return idx


def resolve_kg(nama, tipe_cell):
    """True bila kg. Pakai flag kolom 'tipe' bila diisi, selain itu auto dari nama."""
    t = norm(tipe_cell)
    if t:
        return "kg" in t          # "kg"/"kg an" -> kg; "satuan" -> bukan
    return is_kg(nama)


def _to_int(v):
    try:
        return int(round(float(str(v).replace(".", "").replace(",", "").strip() or 0)))
    except (TypeError, ValueError):
        return 0


def plan_updates(produk_rows, catalog):
    """produk_rows: baris tab Produk mulai baris data, tiap baris:
    [nama, harga_jual_edit, harga_beli_edit, tipe, nama_olshopin].
    Return list dict rencana per baris (row_no mulai 2)."""
    idx = _index(catalog)
    out = []
    for i, row in enumerate(produk_rows):
        nama = row[0] if row else ""
        if not str(nama).strip():
            continue
        jual_lama = _to_int(row[1]) if len(row) > 1 else 0
        beli_lama = _to_int(row[2]) if len(row) > 2 else 0
        tipe_cell = row[3] if len(row) > 3 else ""
        ol_cell = (row[4].strip() if len(row) > 4 and row[4] else "")
        kg = resolve_kg(nama, tipe_cell)

        if ol_cell:
            hit = idx.get(norm(ol_cell))            # override manual (kolom E)
        else:
            n = norm(nama)
            hit = idx.get(n) or idx.get(_strip_kg(n))

        rec = {"row_no": i + 2, "nama": nama, "tipe": "kg" if kg else "satuan",
               "jual_lama": jual_lama, "beli_lama": beli_lama,
               "jual_raw": row[1] if len(row) > 1 else "",
               "beli_raw": row[2] if len(row) > 2 else "",
               "override": bool(ol_cell), "matched": hit is not None}
        if hit:
            olname, hj, stok = hit
            rec.update(olshopin=olname, jual_baru=_to_int(hj),
                       beli_baru=hitung_beli(hj, kg), stok=stok)
        else:
            rec.update(olshopin=ol_cell or None, jual_baru=jual_lama, beli_baru=beli_lama, stok=None)
        out.append(rec)
    return out


def apply_updates(ws, plan):
    """Tulis harga_jual_edit (B) & harga_beli_edit (C) untuk baris matched.
    Baris unmatched dibiarkan (nilai lama ditulis kembali = tidak berubah)."""
    if not plan:
        return 0
    last = max(p["row_no"] for p in plan)
    by_row = {p["row_no"]: p for p in plan}
    data = []
    for r in range(2, last + 1):
        p = by_row.get(r)
        if p and p["matched"]:
            data.append([p["jual_baru"], p["beli_baru"]])
        elif p:
            data.append([p["jual_raw"], p["beli_raw"]])   # unmatched: pertahankan asli
        else:
            data.append(["", ""])
    ws.update(data, f"B2:C{last}", value_input_option="USER_ENTERED")
    return sum(1 for p in plan if p["matched"])
