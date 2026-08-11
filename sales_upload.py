"""
Parser file export transaksi Kasir Pintar (.xls) untuk dipakai di
Laporan Sortir -- supaya sortir bisa dibandingkan dengan penjualan riil
(rasio sortir, margin nyata per produk).

File Kasir Pintar formatnya BIFF/OLE2 lama dan kadang sedikit "corrupt"
di header stream-nya, jadi dibaca langsung pakai xlrd dengan
ignore_workbook_corruption -- pandas.read_excel gagal untuk file ini.
"""

import re

import pandas as pd

# Kolom yang kita butuhkan dari sheet "TransaksiBarang".
_COL_ALIASES = {
    "timestamp": ["Timestamp"],
    "kode": ["Kode Barang"],
    "nama": ["Nama Barang"],
    "jumlah": ["Jumlah"],
    "harga_beli": ["Harga Beli"],
    "harga_jual": ["Harga Jual"],
    "total": ["Total"],
}


def normalize_name(value) -> str:
    """Samakan nama produk buat matching sortir <-> transaksi: huruf kecil,
    spasi dirapikan. Nama di data sortir dan di file Kasir Pintar sama-sama
    berasal dari katalog toko yang sama, jadi biasanya cocok persis setelah
    dinormalkan."""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def parse_transaksi(file_bytes: bytes) -> pd.DataFrame:
    """Baca bytes file .xls Kasir Pintar -> DataFrame rapi berisi item
    transaksi. Kolom hasil: Timestamp (datetime), Kode, Nama, nama_norm,
    Jumlah, HargaBeli, HargaJual, Total.

    Raise ValueError dengan pesan ramah kalau file tidak bisa dibaca /
    bukan format yang diharapkan.
    """
    try:
        import xlrd
    except ImportError as e:  # pragma: no cover
        raise ValueError(
            "Paket 'xlrd' belum terpasang di server. Tambahkan 'xlrd' ke "
            "requirements.txt lalu deploy ulang."
        ) from e

    try:
        book = xlrd.open_workbook(file_contents=file_bytes, ignore_workbook_corruption=True)
    except Exception as e:  # xlrd melempar macam-macam; bungkus jadi pesan jelas
        raise ValueError(
            "File tidak bisa dibaca sebagai .xls Kasir Pintar. Pastikan yang "
            f"diupload memang file export .xls dari Kasir Pintar (detail: {e})."
        ) from e

    target = next(
        (n for n in book.sheet_names() if n.replace(" ", "").lower() == "transaksibarang"),
        None,
    )
    if target is None:
        raise ValueError(
            "Sheet 'TransaksiBarang' tidak ditemukan di file. Sheet yang ada: "
            + ", ".join(book.sheet_names())
        )

    sh = book.sheet_by_name(target)
    if sh.nrows < 2:
        raise ValueError("Sheet 'TransaksiBarang' kosong (tidak ada baris transaksi).")

    header = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    lower_to_idx = {h.lower(): i for i, h in enumerate(header)}

    def find_col(key: str):
        for alias in _COL_ALIASES[key]:
            if alias.lower() in lower_to_idx:
                return lower_to_idx[alias.lower()]
        return None

    idx = {key: find_col(key) for key in _COL_ALIASES}
    wajib = ["timestamp", "nama", "jumlah"]
    hilang = [k for k in wajib if idx[k] is None]
    if hilang:
        raise ValueError(
            "Kolom penting tidak ketemu di file: "
            + ", ".join(_COL_ALIASES[k][0] for k in hilang)
        )

    def cell(r, key):
        i = idx[key]
        return sh.cell_value(r, i) if i is not None else None

    rows = [
        {
            "Timestamp": cell(r, "timestamp"),
            "Kode": cell(r, "kode"),
            "Nama": cell(r, "nama"),
            "Jumlah": cell(r, "jumlah"),
            "HargaBeli": cell(r, "harga_beli"),
            "HargaJual": cell(r, "harga_jual"),
            "Total": cell(r, "total"),
        }
        for r in range(1, sh.nrows)
    ]

    df = pd.DataFrame(rows)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for c in ["Jumlah", "HargaBeli", "HargaJual", "Total"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["Nama"] = df["Nama"].astype(str).str.strip()
    df["nama_norm"] = df["Nama"].map(normalize_name)
    df = df.dropna(subset=["Timestamp"])
    df = df[df["nama_norm"] != ""]

    if df.empty:
        raise ValueError("Tidak ada baris transaksi yang valid (timestamp/nama kosong semua).")

    return df
