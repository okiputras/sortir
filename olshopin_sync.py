"""
Sinkronisasi harga produk dari katalog Olshopin (toko AIRIN FRESH MART).

Alur:
  fetch_catalog()  -> {nama_barang: harga_jual} dari semua halaman katalog
  load_mapping(sh) -> mapping manual {nama_tab -> nama_olshopin} dari tab ProdukMapping
  plan_updates(...) -> daftar rencana perubahan per baris tab Produk
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

OLSHOP_TID = "1543660"
OLSHOP_URL = f"https://olshopin.com/t/{OLSHOP_TID}?page="
MAPPING_TAB = "ProdukMapping"
POTONG_KG = 4000
POTONG_SATUAN = 500
_UA = {"User-Agent": "Mozilla/5.0"}
_RE_SHOP = re.compile(r"window\.__SHOP_HOME__\s*=\s*(\{.*?\});", re.S)


# ---------------- fetch katalog ----------------
def _fetch_page(page):
    req = urllib.request.Request(OLSHOP_URL + str(page), headers=_UA)
    html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    m = _RE_SHOP.search(html)
    if not m:
        return {"data": [], "last_page": 1}
    return json.loads(m.group(1))["barangs"]


def fetch_catalog():
    """Ambil seluruh katalog -> dict {nama_barang: harga_jual}. Paralel antar halaman."""
    first = _fetch_page(1)
    last = int(first.get("last_page", 1) or 1)
    catalog = {}
    for x in first.get("data", []):
        catalog[x["nama_barang"]] = x["harga_jual"]
    if last > 1:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_fetch_page, p) for p in range(2, last + 1)]
            for f in as_completed(futs):
                try:
                    for x in f.result().get("data", []):
                        catalog[x["nama_barang"]] = x["harga_jual"]
                except Exception:
                    pass
    return catalog


# ---------------- normalisasi & aturan ----------------
def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


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


# ---------------- mapping manual ----------------
def load_mapping(spreadsheet):
    """Baca tab ProdukMapping (nama_barang_edit | nama_olshopin) -> {norm(nama_tab): nama_olshopin}."""
    try:
        ws = spreadsheet.worksheet(MAPPING_TAB)
    except Exception:
        return {}
    out = {}
    for row in ws.get_all_values()[1:]:
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            out[norm(row[0])] = row[1].strip()
    return out


def save_mapping(spreadsheet, pairs):
    """pairs: list of (nama_tab, nama_olshopin). Tulis/replace tab ProdukMapping."""
    try:
        ws = spreadsheet.worksheet(MAPPING_TAB)
        ws.clear()
    except Exception:
        ws = spreadsheet.add_worksheet(title=MAPPING_TAB, rows=max(len(pairs) + 10, 20), cols=2)
    data = [["nama_barang_edit", "nama_olshopin"]] + [[a, b] for a, b in pairs]
    ws.update(data, "A1", value_input_option="RAW")
    return ws


# ---------------- pencocokan & rencana ----------------
def _index(catalog):
    idx = {}
    for nama, hj in catalog.items():
        idx[norm(nama)] = (nama, hj)
    return idx


def _match(nama_tab, idx, manual):
    n = norm(nama_tab)
    if n in manual:
        t = norm(manual[n])
        if t in idx:
            return idx[t]
    if n in idx:
        return idx[n]
    nk = _strip_kg(n)
    if nk in idx:
        return idx[nk]
    return None


def _to_int(v):
    try:
        return int(round(float(str(v).replace(".", "").replace(",", "").strip() or 0)))
    except (TypeError, ValueError):
        return 0


def plan_updates(produk_rows, catalog, manual):
    """produk_rows: list [nama, harga_jual_edit, harga_beli_edit] (mulai baris data).
    Return list dict rencana per baris (row_no mulai 2)."""
    idx = _index(catalog)
    out = []
    for i, row in enumerate(produk_rows):
        nama = row[0] if row else ""
        if not str(nama).strip():
            continue
        jual_lama = _to_int(row[1]) if len(row) > 1 else 0
        beli_lama = _to_int(row[2]) if len(row) > 2 else 0
        kg = is_kg(nama)
        hit = _match(nama, idx, manual)
        rec = {"row_no": i + 2, "nama": nama, "tipe": "kg" if kg else "satuan",
               "jual_lama": jual_lama, "beli_lama": beli_lama,
               "jual_raw": row[1] if len(row) > 1 else "",
               "beli_raw": row[2] if len(row) > 2 else "",
               "matched": hit is not None}
        if hit:
            olname, hj = hit
            rec.update(olshopin=olname, jual_baru=_to_int(hj),
                       beli_baru=hitung_beli(hj, kg))
        else:
            rec.update(olshopin=None, jual_baru=jual_lama, beli_baru=beli_lama)
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
