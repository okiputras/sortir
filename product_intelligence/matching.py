"""
Baca katalog Airin dari file master (DATA_BARANG*.xls, sheet "barang" --
format yg sama dipakai backfill/analisa margin sebelumnya) + normalisasi
nama produk + fuzzy match hasil Tokopedia ke katalog itu.

Normalisasi di sini SENGAJA lebih agresif drpd olshopin_sync.norm() --
nama Tokopedia penuh kata promo ("bundling", "grosir", "diskon", "gratis
ongkir") dan satuan kemasan (gr/ml/kg/pcs/dus/karton) yg bikin fuzzy match
meleset kalau gak dibuang dulu. olshopin_sync.norm() didesain buat nama
katalog Olshopin yg sudah rapi, beda kasus.
"""
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import xlrd
from rapidfuzz import fuzz, process

# --------------------------------------------------------------------------
# baca katalog Airin dari DATA_BARANG*.xls
# --------------------------------------------------------------------------

def load_airin_catalog(path: str) -> pd.DataFrame:
    """DATA_BARANG*.xls (export Kasir Pintar, sheet 'barang', 2 baris header
    -- baris pertama nama kolom, baris kedua penjelasan, data mulai baris 3).
    Kolom yg dipakai: kode_barang_edit(1), nama_barang_edit(2),
    harga_jual_edit(5), harga_beli_edit(6), stok_edit(8), kategori(15)."""
    book = xlrd.open_workbook(path, ignore_workbook_corruption=True)
    sh = book.sheet_by_name("barang")
    rows = []
    for r in range(2, sh.nrows):
        nama = str(sh.cell_value(r, 2)).strip()
        if not nama:
            continue
        rows.append({
            "kode": str(sh.cell_value(r, 1)).strip(),
            "nama_airin": nama,
            "harga_jual": sh.cell_value(r, 5) or 0,
            "harga_beli": sh.cell_value(r, 6) or 0,
            "stok": sh.cell_value(r, 8) or 0,
            "kategori_airin": str(sh.cell_value(r, 15)).strip(),
        })
    df = pd.DataFrame(rows)
    df["nama_norm"] = df["nama_airin"].map(normalize_name)
    return df


# --------------------------------------------------------------------------
# normalisasi nama
# --------------------------------------------------------------------------

_SATUAN_RE = re.compile(
    r"\b\d+([.,]\d+)?\s*(gr|gram|g|kg|ml|liter|l|pcs|pc|pack|renteng|dus|karton|box|botol|sachet|shacet)\b",
    re.I,
)
_PROMO_KATA = re.compile(
    r"\b(bundling|bundle|grosir|diskon|promo|gratis\s*ongkir|cod|bisa\s*cod|"
    r"beli\s*\d+\s*gratis\s*\d+|buy\s*\d+\s*get\s*\d+|clearance|sale|"
    r"terlaris|termurah|original|ori|halal|bpom)\b",
    re.I,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def normalize_name(nama: str) -> str:
    s = str(nama or "").lower()
    s = _SATUAN_RE.sub(" ", s)       # buang "500ml", "1kg", dst
    s = _PROMO_KATA.sub(" ", s)      # buang kata promo/marketing
    s = _PUNCT_RE.sub(" ", s)        # buang tanda baca
    s = _SPACE_RE.sub(" ", s).strip()
    return s


# --------------------------------------------------------------------------
# fuzzy matching
# --------------------------------------------------------------------------

SKOR_SAMA = 85       # >= ini: dianggap produk yg sama, sudah ada di Airin
SKOR_VERIFIKASI = 60  # >= ini (tapi < SKOR_SAMA): mungkin sama, perlu cek manual


@dataclass
class MatchResult:
    status: str          # "SAMA_PRODUK" | "PERLU_VERIFIKASI" | "BELUM_TERSEDIA"
    skor: float           # 0-100, skor fuzzy match terbaik
    airin_match: Optional[str]    # nama produk Airin yg paling mirip (kalau ada)
    airin_kategori: Optional[str]


def _classify(skor: float) -> str:
    if skor >= SKOR_SAMA:
        return "SAMA_PRODUK"
    if skor >= SKOR_VERIFIKASI:
        return "PERLU_VERIFIKASI"
    return "BELUM_TERSEDIA"


def match_to_airin(nama_tokped: str, airin_df: pd.DataFrame) -> MatchResult:
    """Cari kecocokan terbaik `nama_tokped` di seluruh katalog Airin (semua
    kategori -- gak dibatasi kategori Tokopedia-nya krn pemetaan kategori
    dua sisi belum tentu konsisten namanya). Buat cek satu-satu / debug;
    kalau match banyak produk sekaligus pakai match_batch() (jauh lebih
    cepat, gak looping ulang katalog tiap kali)."""
    target = normalize_name(nama_tokped)
    if not target or airin_df.empty:
        return MatchResult("BELUM_TERSEDIA", 0.0, None, None)

    choices = airin_df["nama_norm"].tolist()
    hit = process.extractOne(target, choices, scorer=fuzz.token_sort_ratio)
    if hit is None:
        return MatchResult("BELUM_TERSEDIA", 0.0, None, None)
    _, skor, idx = hit
    row = airin_df.iloc[idx]
    return MatchResult(
        status=_classify(skor), skor=round(skor, 1),
        airin_match=row["nama_airin"], airin_kategori=row["kategori_airin"],
    )


def match_batch(tokped_df: pd.DataFrame, airin_df: pd.DataFrame, nama_col: str = "nama") -> pd.DataFrame:
    """Tempel kolom status/skor/airin_match ke tiap baris tokped_df.

    Dipakai `process.cdist` (matriks skor semua-lawan-semua sekaligus, C++
    vektor di rapidfuzz) drpd extractOne satu-satu per baris -- utk 100
    produk tokped x 1.440 produk Airin ini beda jauh dari sisi kecepatan
    drpd loop Python biasa."""
    hasil = tokped_df.copy()
    if hasil.empty or airin_df.empty:
        hasil["status_airin"] = "BELUM_TERSEDIA"
        hasil["skor_match"] = 0.0
        hasil["airin_match"] = None
        hasil["airin_kategori"] = None
        return hasil

    targets = hasil[nama_col].map(normalize_name).tolist()
    choices = airin_df["nama_norm"].tolist()
    score_matrix = process.cdist(targets, choices, scorer=fuzz.token_sort_ratio)

    best_idx = score_matrix.argmax(axis=1)
    best_skor = score_matrix.max(axis=1)

    hasil["skor_match"] = best_skor.round(1)
    hasil["status_airin"] = [_classify(s) for s in best_skor]
    hasil["airin_match"] = airin_df["nama_airin"].to_numpy()[best_idx]
    hasil["airin_kategori"] = airin_df["kategori_airin"].to_numpy()[best_idx]
    return hasil
