"""
Opportunity Score + Retail Fit filter -- semua rumus di sini DETERMINISTIK
(bukan model/AI), sengaja biar hasilnya bisa diaudit ulang manual & gampang
dikalibrasi kalau owner merasa bobotnya kurang pas.

KETERBATASAN JUJUR (baca dulu sebelum percaya angkanya bulat-bulat):
  - Kita gak punya harga_beli/supplier utk produk yg BELUM dijual Airin --
    margin_score di bawah itu TEBAKAN berbasis kategori, bukan hitungan
    dari data riil. Anggap sbg sinyal kasar, bukan angka final.
  - "terjual" dari Tokopedia itu RANGE ("100rb+"), bukan angka pasti --
    dipakai batas BAWAH-nya (konservatif), jadi Marketplace Demand bisa
    under-estimate produk yg jauh di atas ambang itu.
  - Category Relevance & Repeat Purchase pakai lookup tabel manual, bukan
    hasil analisis data penjualan -- edit KATEGORI_REPEAT/kategori lookup
    di bawah kalau owner punya insight lebih baik dari pengalaman toko.
"""
import re

import pandas as pd

# --------------------------------------------------------------------------
# bobot Opportunity Score -- total harus 100
# --------------------------------------------------------------------------
BOBOT = {
    # prefix "skor_" sengaja -- kalau bare ("rating", "margin") bakal nabrak
    # nama kolom asli dari Tokopedia pas hasil scoring digabung (concat) ke
    # DataFrame utama di pipeline.py (duplicate column name -> pandas balikin
    # Series bukan skalar pas diakses, pernah kejadian & susah dilacak).
    "skor_demand": 30,
    "skor_rating": 20,
    "skor_relevansi_kategori": 20,
    "skor_margin": 15,
    "skor_repeat_purchase": 10,
    "skor_product_gap": 5,
}
assert sum(BOBOT.values()) == 100

_TERJUAL_RE = re.compile(r"([\d.,]+)\s*(rb|jt)?\s*\+?", re.I)
_MULTIPLIER = {"": 1, "rb": 1_000, "jt": 1_000_000}


def parse_terjual(s) -> int:
    """'500rb+' -> 500000, '1rb+' -> 1000, '70+' -> 70, '13' -> 13,
    kosong/gak kebaca -> 0. Selalu batas BAWAH (angka sblm '+'), krn
    Tokopedia nampilin range bukan angka pasti."""
    if not s:
        return 0
    m = _TERJUAL_RE.search(str(s).replace(",", "."))
    if not m:
        return 0
    angka = float(m.group(1))
    mult = _MULTIPLIER.get((m.group(2) or "").lower(), 1)
    return int(angka * mult)


def parse_harga(s) -> int:
    """'Rp63.000' -> 63000."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else 0


# --------------------------------------------------------------------------
# retail fit -- FILTER duluan, produk yg kena ini gak usah masuk ranking
# --------------------------------------------------------------------------
_KEMASAN_GROSIR_RE = re.compile(
    r"\b(isi\s*\d{2,}|dus|karton|\d+\s*ball|grosir\s*\d|\d+\s*pcs\s*grosir)\b", re.I
)
HARGA_MAX_ECERAN = 200_000  # di atas ini + nama-nya kebaca kemasan besar -> kemungkinan bukan buat rak eceran


def retail_fit(nama: str, harga: int) -> bool:
    """True = layak dipertimbangkan buat rak eceran Airin. False = difilter
    (kemasan grosir/dus besar yg jelas bukan satuan jual eceran toko)."""
    if _KEMASAN_GROSIR_RE.search(nama or "") and harga > HARGA_MAX_ECERAN:
        return False
    return True


# --------------------------------------------------------------------------
# brand -- heuristik sederhana: kata pertama yg bukan angka/satuan
# --------------------------------------------------------------------------
_STOPWORD_AWAL = {"promo", "grosir", "paket", "bundling", "cod", "1pc", "isi"}


def extract_brand(nama: str) -> str:
    kata = re.findall(r"[A-Za-z]+", nama or "")
    for k in kata:
        if k.lower() not in _STOPWORD_AWAL and len(k) > 2:
            return k
    return kata[0] if kata else ""


# --------------------------------------------------------------------------
# lookup manual -- SILAKAN DIEDIT sesuai pengalaman toko, ini titik awal aja
# --------------------------------------------------------------------------
KATEGORI_REPEAT_PURCHASE = {
    "default": 50,
    "sembako": 90, "bumbu": 90, "kopi": 90, "mie": 90, "beras": 90,
    "minyak": 90, "gula": 90, "susu": 85, "madu": 70, "kecap": 85, "saos": 85,
    "snack": 60, "biskuit": 60, "permen": 55, "cokelat": 55,
    "household": 75, "deterjen": 80, "sabun": 75,
    "personal care": 65, "baby": 60, "frozen": 70, "kurma": 45, "abon": 65,
}
KATEGORI_MARGIN_ASUMSI_PCT = {
    "default": 12,
    "bumbu": 10, "kopi": 12, "mie": 8, "beras": 6, "minyak": 6,
    "madu": 25, "kurma": 20, "snack": 15, "biskuit": 15,
    "household": 10, "personal care": 15, "abon": 18, "frozen": 12,
}


def _lookup(kategori: str, table: dict) -> float:
    k = (kategori or "").strip().lower()
    return table.get(k, table["default"])


def category_relevance_score(kategori: str, airin_df: pd.DataFrame) -> float:
    """Makin SEDIKIT produk Airin yg sudah ada di kategori ini, makin
    tinggi skornya (= makin relevan buat diisi, bukan makin gak relevan --
    ini "gap" score, kebalik dari density)."""
    k = (kategori or "").strip().lower()
    if not k:
        return 50.0
    count = (airin_df["kategori_airin"].str.lower() == k).sum()
    if count == 0:
        return 100.0
    if count <= 5:
        return 70.0
    if count <= 20:
        return 40.0
    return 15.0


def demand_score(terjual_min: int) -> float:
    import math
    if terjual_min <= 0:
        return 0.0
    # log10(1)=0 .. log10(500_000)=~5.7 -> dinormalisasi ke 0-100 pakai patokan 5.7
    return min(100.0, math.log10(terjual_min + 1) / 5.7 * 100)


def rating_score(rating) -> float:
    if rating is None:
        return 0.0
    try:
        r = float(rating)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, (r - 3.5) / 1.5 * 100))


def opportunity_score(row: dict, airin_df: pd.DataFrame, kategori: str) -> dict:
    """row: dict hasil satu baris tokped (sudah lolos matching), minimal
    punya 'rating' dan 'terjual' (string mentah Tokopedia). Return dict
    berisi tiap sub-skor + total, biar 'alasan' gampang disusun dari sini."""
    terjual_min = parse_terjual(row.get("terjual"))
    sub = {
        "skor_demand": demand_score(terjual_min),
        "skor_rating": rating_score(row.get("rating")),
        "skor_relevansi_kategori": category_relevance_score(kategori, airin_df),
        "skor_margin": min(100.0, _lookup(kategori, KATEGORI_MARGIN_ASUMSI_PCT) / 30 * 100),
        "skor_repeat_purchase": _lookup(kategori, KATEGORI_REPEAT_PURCHASE),
        "skor_product_gap": 100.0 if row.get("status_airin") == "BELUM_TERSEDIA" else 0.0,
    }
    total = sum(sub[k] * BOBOT[k] / 100 for k in BOBOT)
    sub["total"] = round(total, 1)
    sub["terjual_min"] = terjual_min
    return sub


def priority_label(score: float) -> str:
    if score >= 75:
        return "🔥 PRIORITAS TINGGI"
    if score >= 55:
        return "⭐ PRIORITAS SEDANG"
    if score >= 35:
        return "⚠️ PERLU VERIFIKASI"
    return "❌ TIDAK DIREKOMENDASIKAN"


def build_alasan(row: dict, sub: dict, kategori: str) -> str:
    bagian = []
    if sub["terjual_min"] >= 10_000:
        bagian.append(f"terjual {row.get('terjual')} (demand tinggi)")
    if sub["skor_relevansi_kategori"] >= 70:
        bagian.append(f"kategori '{kategori}' hampir gak ada di katalog Airin")
    if row.get("rating") and float(row["rating"]) >= 4.8:
        bagian.append(f"rating {row['rating']} (sangat dipercaya pembeli)")
    if sub["skor_margin"] >= 60:
        bagian.append("potensi margin di atas rata-rata kategori")
    if not bagian:
        bagian.append("sinyal sedang di semua faktor, worth dipertimbangkan tapi bukan prioritas")
    return "; ".join(bagian)
