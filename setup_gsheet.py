"""
Script SEKALI JALAN untuk menyiapkan struktur sheet di dalam Google
Spreadsheet yang SUDAH KAMU BUAT SENDIRI, mengisi data awal (produk &
cabang contoh).

Syarat sebelum jalankan:
    1. Buat Google Sheet baru manual di Drive kamu (nama bebas, misal
       "Database Sortir Sayur").
    2. Share spreadsheet itu ke email berikut sebagai EDITOR:
       oki-gsheet@iconic-woods-355603.iam.gserviceaccount.com
    3. Isi SPREADSHEET_ID di spreadsheet_id.txt (satu baris berisi ID-nya
       saja) atau lewat env var SPREADSHEET_ID. ID-nya bagian di URL antara
       /d/ dan /edit, contoh:
       https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit

Jalankan:
    source venv/bin/activate
    python3 setup_gsheet.py
"""

import os

import gspread
from google.oauth2.service_account import Credentials

SERVICE_ACCOUNT_FILE = "service_account.json"


def _load_spreadsheet_id() -> str:
    env_id = os.environ.get("SPREADSHEET_ID")
    if env_id:
        return env_id
    if os.path.exists("spreadsheet_id.txt"):
        with open("spreadsheet_id.txt") as f:
            return f.read().strip()
    return ""


SPREADSHEET_ID = _load_spreadsheet_id()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Header tiap sheet
HEADERS = {
    "Produk": ["Nama Produk", "Satuan", "Harga"],
    "Cabang": ["Nama Cabang"],
    "Karyawan": ["Nama Karyawan"],
    "Sortir": [
        "Session ID",
        "Tanggal",
        "Nama Karyawan",
        "Cabang",
        "Produk",
        "Satuan",
        "Qty",
        "Harga Satuan",
        "Subtotal",
        "Timestamp",
    ],
}

# Data awal (diambil dari contoh data WA yang dikirim user, harga per satuan
# hasil hitung mundur dari salah satu contoh -- SILAKAN DIEDIT lagi di sheet
# "Produk" sesuai harga pasar terbaru, ini cuma starter data)
PRODUK_SEED = [
    ["rawit", "kg", 32000],
    ["sawi putih", "kg", 8000],
    ["kangkung", "ikat", 2000],
    ["bayam", "ikat", 1500],
    ["cambah", "ikat", 1500],
    ["timun", "kg", 15000],
    ["bunga kol", "kg", 15000],
    ["cabe besar merah", "kg", 33000],
    ["cabe besar ijo", "kg", 27000],
    ["andewi", "kg", 16000],
    ["cabe keriting", "kg", 35000],
    ["tomat", "kg", 8000],
    ["manggis", "kg", 25000],
    ["pear", "kg", 25000],
    ["wortel", "kg", 18000],
    ["sere", "ikat", 1500],
    ["genjer", "ikat", 3000],
    ["laos", "kg", 13000],
    ["buncis", "kg", 16000],
    ["gambas", "kg", 12000],
    ["jamur kuping", "kg", 3000],
    ["kubis", "kg", 10000],
]

CABANG_SEED = [
    ["SULFAT"],
    ["PIRANHA"],
]

KARYAWAN_SEED = [
    # Tambahkan nama karyawan asli di sini atau langsung di Google Sheet-nya
    ["Contoh Karyawan 1"],
    ["Contoh Karyawan 2"],
]


def main() -> None:
    if not SPREADSHEET_ID:
        raise SystemExit(
            "SPREADSHEET_ID masih kosong. Isi dulu ID spreadsheet yang sudah "
            "kamu buat & share ke service account (lihat instruksi di atas file ini)."
        )

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SPREADSHEET_ID)
    print(f"Berhasil buka spreadsheet '{sh.title}'.")

    existing_titles = {ws.title for ws in sh.worksheets()}

    for sheet_name, header in HEADERS.items():
        if sheet_name in existing_titles:
            ws = sh.worksheet(sheet_name)
            print(f"Sheet '{sheet_name}' sudah ada, skip pembuatan (header tidak ditimpa).")
            continue
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=len(header))
        ws.update([header], "A1")
        print(f"Sheet '{sheet_name}' dibuat.")

        if sheet_name == "Produk":
            ws.append_rows(PRODUK_SEED)
            print(f"  seed {len(PRODUK_SEED)} produk.")
        elif sheet_name == "Cabang":
            ws.append_rows(CABANG_SEED)
            print(f"  seed {len(CABANG_SEED)} cabang.")
        elif sheet_name == "Karyawan":
            ws.append_rows(KARYAWAN_SEED)
            print(f"  seed {len(KARYAWAN_SEED)} contoh nama karyawan (edit manual di sheet).")

    # Hapus sheet default "Sheet1" kalau masih ada dan kosong
    for ws in sh.worksheets():
        if ws.title == "Sheet1" and ws.row_count and not ws.get_all_values():
            sh.del_worksheet(ws)
            print("Sheet1 default dihapus.")

    print()
    print("Spreadsheet ID:", sh.id)
    print("URL:", sh.url)

    with open("spreadsheet_id.txt", "w") as f:
        f.write(sh.id)
    print("Spreadsheet ID juga disimpan ke spreadsheet_id.txt (dipakai oleh app.py)")


if __name__ == "__main__":
    main()
