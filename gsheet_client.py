"""
Koneksi ke Google Sheets & fungsi CRUD untuk sheet "Sortir" dan
"Laporan Harian". Dipakai oleh app.py dan pages/*.py.
"""

import json
import os
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread.http_client import HTTPClient
from gspread.utils import fill_gaps, numericise_all, to_records
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

JAKARTA = ZoneInfo("Asia/Jakarta")

LOCK_SHEET = "_Lock"
# Lock dianggap basi (pemegangnya crash) sesudah sekian detik. Harus jauh di
# atas lama _RetryHTTPClient menunggu kuota (~1 menit per request): pemegang
# lock yang sedang menunggu kuota TIDAK boleh dianggap crash -- kalau lock-nya
# direbut di tengah hapus, index baris yang sudah dia cari jadi salah.
LOCK_TIMEOUT_SECONDS = 150
LOCK_MAX_WAIT_SECONDS = 25

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SORTIR_HEADER = [
    "Session ID",
    "Tanggal",
    "Nama Karyawan",
    "Cabang",
    "Produk",
    "Qty",
    "Harga Satuan",
    "Subtotal",
    "Timestamp",
]

LAPORAN_HEADER = [
    "Session ID",
    "Tanggal",
    "Nama",
    "Cabang",
    "Keterangan",
    "Nominal",
    "Modal",
    "Petty Cash Awal",
    "Cash",
    "Qris",
    "Debit",
    "Tf",
    "Tarik Tunai / Tukar Uang",
    "Total",
    "Timestamp",
]

OPERASIONAL_HEADER = [
    "Session ID",
    "Tanggal",
    "Cabang",
    "Kategori",
    "Keterangan",
    "Nominal",
    "Timestamp",
]

# Kartu konsinyasi (barang titipan). Kunjungan supplier ikut dipisah per bulan
# seperti Sortir; supplier & produknya dua tab master kecil yang tidak dipisah.
KONSINYASI_HEADER = [
    "Session ID",
    "Tanggal",
    "Cabang",
    "Supplier ID",
    "Supplier",
    "Produk ID",
    "Produk",
    "Harga Titip",
    "Stok Lama",
    "Sisa",
    "Terjual",
    "Masuk",
    "Stok Akhir",
    "Bayar",
    "Petugas",
    "Disetujui Supplier",
    "Status Bayar",
    "Catatan",
    "Timestamp",
]
KONS_SUPPLIER_SHEET = "Konsinyasi Supplier"
KONS_SUPPLIER_HEADER = ["ID", "Nama Supplier", "No HP", "Sistem Bayar", "Aktif", "Dibuat"]
KONS_PRODUK_SHEET = "Konsinyasi Produk"
KONS_PRODUK_HEADER = ["ID", "Supplier ID", "Cabang", "Nama Produk", "Harga Titip", "Harga Jual", "Aktif", "Dibuat"]


def _secrets_available() -> bool:
    # Mengakses st.secrets tanpa file secrets.toml sama sekali akan raise
    # exception, bukan cuma False -- jadi cek keberadaan filenya dulu.
    return os.path.exists(".streamlit/secrets.toml") or os.path.exists(
        os.path.expanduser("~/.streamlit/secrets.toml")
    )


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def _load_credentials() -> Credentials:
    # Urutan prioritas: Streamlit secrets (Streamlit Cloud) -> env var (Railway
    # / host lain) -> file lokal (dev di laptop).
    if _secrets_available() and "gcp_service_account" in st.secrets:
        return Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=SCOPES
        )
    env_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if env_json:
        env_json = _strip_wrapping_quotes(env_json)
        try:
            info = json.loads(env_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "Env var GCP_SERVICE_ACCOUNT_JSON isinya bukan JSON yang valid "
                f"(gagal parse: {e}). Pastikan paste SELURUH isi file "
                "service_account.json apa adanya (termasuk { } di awal-akhir), "
                "jangan cuma sebagian atau ada karakter yang ke-strip."
            ) from e
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file("service_account.json", scopes=SCOPES)


def _load_spreadsheet_id() -> str:
    if _secrets_available() and "spreadsheet_id" in st.secrets:
        return st.secrets["spreadsheet_id"]
    env_id = os.environ.get("SPREADSHEET_ID")
    if env_id:
        return _strip_wrapping_quotes(env_id)
    with open("spreadsheet_id.txt") as f:
        return f.read().strip()


class _RetryHTTPClient(HTTPClient):
    """Coba ulang request yang ditolak Google karena kuota, bukan langsung crash.

    Semua sesi aplikasi -- plus skrip lokal yang memakai service_account.json --
    berbagi SATU service account, dan Google membatasinya ~60 request baca per
    menit. Di jam ramai (pagi, beberapa karyawan input bareng) batas itu pernah
    tersentuh dan halamannya langsung error 429. Kuotanya dihitung per menit,
    jadi menunggu sebentar lalu mencoba lagi hampir selalu berhasil.

    Yang diulang: 429 untuk semua request (request yang ditolak memang belum
    dijalankan, jadi aman diulang) dan 5xx khusus GET. Tulisan yang kena 5xx
    TIDAK diulang -- bisa saja sebenarnya sudah masuk, dan mengulangnya bikin
    baris dobel. (BackOffHTTPClient bawaan gspread tidak dipakai: penghitung
    backoff-nya dibagi antar-thread dan bisa menunggu sampai ~4 menit.)
    """

    TUNGGU = (2, 4, 8, 16, 32)  # total ~1 menit = satu jendela kuota

    def request(self, method, endpoint, *args, **kwargs):
        for tunggu in self.TUNGGU + (None,):
            try:
                return super().request(method, endpoint, *args, **kwargs)
            except gspread.exceptions.APIError as e:
                ulang = e.code == 429 or (e.code >= 500 and method.lower() == "get")
                if tunggu is None or not ulang:
                    raise
                time.sleep(tunggu + random.uniform(0, 1))


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    creds = _load_credentials()
    client = gspread.authorize(creds, http_client=_RetryHTTPClient)
    spreadsheet_id = _load_spreadsheet_id()
    try:
        return client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as e:
        raise RuntimeError(
            "Spreadsheet tidak ditemukan / tidak bisa diakses.\n\n"
            f"- SPREADSHEET_ID yang dipakai: `{spreadsheet_id or '(KOSONG)'}`\n"
            f"- Service account: `{creds.service_account_email}`\n\n"
            "Cek: (1) env var SPREADSHEET_ID di Railway sudah benar & tidak ada "
            "spasi/quote nyelip, (2) spreadsheet sudah di-share sebagai Editor "
            "ke email service account di atas."
        ) from e


def _monthly_sheet_name(base_name: str, dt: datetime) -> str:
    return f"{base_name}_{dt.month:02d}_{dt.year}"


def _monthly_sheet_pattern(base_name: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(base_name)}_(\d{{2}})_(\d{{4}})$")


@st.cache_resource(ttl=600, show_spinner=False)
def _worksheets() -> list:
    """Daftar tab spreadsheet, disimpan 10 menit. Dulu diambil ulang (1 request
    baca) setiap kali data Sortir/Laporan/Pengeluaran dimuat dan setiap
    simpan/hapus, padahal tab baru cuma muncul sebulan sekali. Dibersihkan
    begitu aplikasi sendiri membuat tab baru."""
    return get_spreadsheet().worksheets()


def _find_sheet(title: str):
    """Worksheet bertitel `title` dari daftar tersimpan. Kalau tidak ketemu,
    daftarnya disegarkan sekali dulu (bisa jadi basi) sebelum balik None."""
    for segarkan in (False, True):
        if segarkan:
            _worksheets.clear()
        for ws in _worksheets():
            if ws.title == title:
                return ws
    return None


def _data_sheets(base_name: str) -> list:
    """Semua worksheet yang jadi sumber data untuk base_name ini: sheet
    lama (nama polos, isinya data sebelum fitur pemisahan-per-bulan ada)
    kalau masih ada, lalu semua sheet bulanan "Base_MM_YYYY", diurutkan
    kronologis lama -> baru. Dipakai supaya laporan tetap bisa melihat
    seluruh histori walau datanya sekarang tersebar per bulan."""
    pattern = _monthly_sheet_pattern(base_name)
    legacy = None
    monthly = []
    for ws in _worksheets():
        if ws.title == base_name:
            legacy = ws
        else:
            m = pattern.match(ws.title)
            if m:
                monthly.append((int(m.group(2)), int(m.group(1)), ws))
    monthly.sort(key=lambda t: (t[0], t[1]))
    return ([legacy] if legacy else []) + [ws for _, _, ws in monthly]


def _ensure_monthly_sheet(base_name: str, header: list[str], dt: datetime):
    """Sheet tujuan insert untuk bulan `dt` (mis. "Sortir_09_2026"),
    dibuat otomatis dengan header kalau bulan ini baru pertama kali ada
    transaksi -- tujuannya biar data tiap bulan terpisah rapi."""
    title = _monthly_sheet_name(base_name, dt)
    ws = _find_sheet(title)
    if ws is None:
        ws = get_spreadsheet().add_worksheet(title=title, rows=1000, cols=max(len(header), 1))
        ws.update([header], "A1")
        _worksheets.clear()
    return ws


def _batch_get_values(titles) -> list[list[list]]:
    """Isi mentah banyak tab sekaligus lewat 1 request HTTP
    (spreadsheets.values.batchGet), bukan 1 request per tab. Urutannya sama
    dengan `titles`; tab kosong -> []."""
    if not titles:
        return []
    quote = "'"
    ranges = [f"{quote}{t.replace(quote, quote + quote)}{quote}" for t in titles]
    response = get_spreadsheet().values_batch_get(ranges)
    return [vr.get("values", []) for vr in response.get("valueRanges", [])]


def _to_records(raw_values: list[list]) -> list[dict]:
    """Logikanya sengaja disamakan persis dengan gspread's Worksheet.get_all_records()
    (fill_gaps buat baris yang lebih pendek dari header, numericise_all
    buat konversi angka, to_records buat pasangkan header->value) supaya
    hasilnya identik, cuma jalur pengambilan datanya yang beda."""
    if not raw_values:
        return []
    values = fill_gaps(raw_values)
    return to_records(values[0], [numericise_all(row) for row in values[1:]])


MASTER_SHEETS = ("Produk", "Cabang", "Karyawan")


@st.cache_data(ttl=60, show_spinner=False)
def _load_master() -> dict:
    """Isi mentah tab Produk, Cabang & Karyawan dalam SATU request. Dulu tiap
    tab diambil sendiri lewat worksheet(...).get_all_records() = 2 request per
    tab (cari tab + ambil isi). TTL 1 menit: cukup jarang untuk kuota baca
    (lihat _RetryHTTPClient), cukup cepat supaya karyawan/produk yang baru
    ditambahkan langsung di sheet segera muncul di dropdown."""
    return dict(zip(MASTER_SHEETS, _batch_get_values(MASTER_SHEETS)))


def load_produk():
    return _to_records(_load_master()["Produk"])


def load_produk_values() -> list[list]:
    """Seperti worksheet("Produk").get_all_values() (header ikut), tapi dari cache."""
    raw = _load_master()["Produk"]
    return fill_gaps(raw) if raw else []


def load_cabang():
    return _to_records(_load_master()["Cabang"])


def load_karyawan():
    return _to_records(_load_master()["Karyawan"])


def clear_master_cache() -> None:
    """Panggil sesudah aplikasi menulis ke tab Produk/Cabang/Karyawan."""
    _load_master.clear()


def _batch_get_records(worksheets: list) -> list[dict]:
    """Isi banyak worksheet sekaligus lewat 1 request HTTP, bukan 1 request
    per sheet lewat ws.get_all_records() satu-satu. Jumlah request jadi tetap
    1 walau sheet bulanannya terus nambah tiap bulan."""
    return [r for raw in _batch_get_values([ws.title for ws in worksheets]) for r in _to_records(raw)]


def _load_all_records(base_name: str) -> list[dict]:
    # Baris yang di-soft-delete (lihat _delete_session_rows) isinya
    # dikosongkan, bukan dihapus fisik -- filter di sini biar tidak
    # nongol sebagai baris kosong di UI.
    records = _batch_get_records(_data_sheets(base_name))
    return [r for r in records if r.get("Session ID")]


@st.cache_data(ttl=30, show_spinner=False)
def load_sortir():
    return _load_all_records("Sortir")


@st.cache_data(ttl=30, show_spinner=False)
def load_laporan():
    return _load_all_records("Laporan Harian")


@st.cache_data(ttl=30, show_spinner=False)
def load_operasional():
    return _load_all_records("Pengeluaran Operasional")


@st.cache_data(ttl=30, show_spinner=False)
def load_konsinyasi():
    return _load_all_records("Konsinyasi")


@st.cache_data(ttl=60, show_spinner=False)
def load_konsinyasi_master() -> dict:
    """Tab "Konsinyasi Supplier" & "Konsinyasi Produk" dalam SATU request.
    Tab yang belum ada (fitur belum pernah dipakai) dianggap kosong; tab itu
    baru dibuat saat supplier/produk pertama disimpan. Keberadaan tab dicek
    dari daftar tab tersimpan (_worksheets), jadi tidak menambah request."""
    ada = {ws.title for ws in _worksheets()}
    titles = [t for t in (KONS_SUPPLIER_SHEET, KONS_PRODUK_SHEET) if t in ada]
    raw = dict(zip(titles, _batch_get_values(titles)))
    # Supplier dibaca sebagai teks apa adanya, tanpa numericise: "0812..."
    # akan jadi 812... (nol depan No HP hilang).
    supplier_raw = fill_gaps(raw[KONS_SUPPLIER_SHEET]) if raw.get(KONS_SUPPLIER_SHEET) else []
    return {
        "supplier": to_records(supplier_raw[0], supplier_raw[1:]) if supplier_raw else [],
        "produk": _to_records(raw.get(KONS_PRODUK_SHEET, [])),
    }


def _parallel_load(jobs: dict) -> dict:
    """Jalankan beberapa fungsi loader sekaligus secara paralel (bukan
    berurutan) supaya latency network per-request tidak menumpuk."""
    ctx = get_script_run_ctx()

    def _run(fn):
        add_script_run_ctx(ctx=ctx)
        return fn()

    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as ex:
        futures = {k: ex.submit(_run, fn) for k, fn in jobs.items()}
        try:
            return {k: f.result() for k, f in futures.items()}
        except gspread.exceptions.APIError as e:
            # Sampai sini berarti _RetryHTTPClient sudah menunggu ~1 menit dan
            # kuota masih habis -- tampilkan pesan, bukan traceback.
            if e.code != 429:
                raise
            raise RuntimeError(
                "Google Sheets sedang menolak permintaan karena batas baca per "
                "menit terlampaui (terlalu banyak yang memakai aplikasi bersamaan). "
                "Tunggu sekitar 1 menit, lalu muat ulang halaman ini."
            ) from e


def load_all() -> dict:
    """Data untuk halaman Input Sortir: Produk/Cabang/Karyawan/Sortir."""
    return _parallel_load(
        {
            "produk": load_produk,
            "cabang": load_cabang,
            "karyawan": load_karyawan,
            "sortir": load_sortir,
        }
    )


def load_all_laporan() -> dict:
    """Data untuk halaman Laporan Transaksi Harian: Cabang/Karyawan/Laporan."""
    return _parallel_load(
        {
            "cabang": load_cabang,
            "karyawan": load_karyawan,
            "laporan": load_laporan,
        }
    )


def load_all_operasional() -> dict:
    """Data untuk halaman Pengeluaran Operasional: Cabang/Operasional."""
    return _parallel_load(
        {
            "cabang": load_cabang,
            "operasional": load_operasional,
        }
    )


def load_all_konsinyasi() -> dict:
    """Data untuk halaman Kartu Konsinyasi: Cabang/Karyawan/master/kunjungan."""
    return _parallel_load(
        {
            "cabang": load_cabang,
            "karyawan": load_karyawan,
            "master": load_konsinyasi_master,
            "kunjungan": load_konsinyasi,
        }
    )


def _ensure_lock_sheet():
    ws = _find_sheet(LOCK_SHEET)
    if ws is None:
        ws = get_spreadsheet().add_worksheet(title=LOCK_SHEET, rows=2, cols=2)
        ws.update([["token", "acquired_at"]], "A1")
        _worksheets.clear()
    return ws


def _acquire_lock() -> str:
    """Lock sederhana lewat 1 sel di sheet "_Lock", supaya operasi yang
    menggeser baris (hapus/edit) dari user berbeda tidak pernah overlap.

    Bukan lock atomik sempurna (Google Sheets tidak punya compare-and-swap
    bawaan), tapi kombinasi tulis-lalu-verifikasi + retry ini menekan
    peluang tabrakan sampai sangat kecil untuk skala pemakaian toko kecil
    (segelintir karyawan, bukan ratusan request per detik). Lock basi
    (>LOCK_TIMEOUT_SECONDS) dianggap terlepas otomatis, jaga-jaga kalau
    ada proses yang crash sebelum sempat release.
    """
    ws = _ensure_lock_sheet()
    token = str(uuid.uuid4())
    deadline = time.time() + LOCK_MAX_WAIT_SECONDS
    while time.time() < deadline:
        row = ws.row_values(2)
        current_token = row[0] if row else ""
        current_ts = float(row[1]) if len(row) > 1 and row[1] else 0.0
        if not current_token or (time.time() - current_ts) > LOCK_TIMEOUT_SECONDS:
            ws.update([[token, str(time.time())]], "A2")
            time.sleep(0.3)  # kasih waktu write kepropagasi, lalu verifikasi
            row2 = ws.row_values(2)
            if row2 and row2[0] == token:
                return token
        # Cek tiap 1-2 detik, bukan 0,2-0,6: tiap cek = 1 request baca, dan
        # menunggu 25 detik secepat itu bisa menghabiskan kuota baca semenit penuh.
        time.sleep(random.uniform(1.0, 2.0))
    raise RuntimeError(
        "Sistem sedang sibuk (ada yang lain sedang edit/hapus data). "
        "Coba klik Simpan/Hapus lagi sebentar."
    )


def _release_lock(token: str) -> None:
    ws = _ensure_lock_sheet()
    row = ws.row_values(2)
    if row and row[0] == token:
        ws.update([["", ""]], "A2")


def _append_rows(base_name: str, header: list[str], rows: list[dict]) -> None:
    # Tujuan insert selalu sheet bulan berjalan (mis. "Sortir_09_2026"),
    # dibuat otomatis kalau bulan ini baru pertama kali ada transaksi --
    # jadi data tiap bulan otomatis terpisah, tidak menumpuk di satu sheet.
    ws = _ensure_monthly_sheet(base_name, header, datetime.now(JAKARTA))
    values = [[row.get(col, "") for col in header] for row in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")


def _delete_session_rows(base_name: str, session_id: str) -> None:
    """Hapus baris fisik (deleteDimension) -- sheet tetap bersih, tidak
    menumpuk baris kosong. Dilindungi lock (_acquire_lock/_release_lock)
    supaya tidak overlap dengan delete/edit user lain yang jalan
    bersamaan, karena hapus fisik menggeser index baris di bawahnya.

    Sesi bisa ada di sheet bulan mana saja (data terpisah per bulan),
    jadi dicari di semua sheet punya base_name ini -- begitu ketemu,
    langsung berhenti (satu sesi cuma pernah ditulis ke satu sheet).
    Dicari dari bulan terbaru dulu: hapus/edit hampir selalu untuk data
    bulan berjalan, dan tiap sheet yang dicari = 1 request baca."""
    token = _acquire_lock()
    try:
        for ws in reversed(_data_sheets(base_name)):
            matches = ws.findall(session_id, in_column=1)
            if not matches:
                continue
            rows = sorted({c.row for c in matches}, reverse=True)
            requests = [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "ROWS",
                            "startIndex": r - 1,
                            "endIndex": r,
                        }
                    }
                }
                for r in rows
            ]
            get_spreadsheet().batch_update({"requests": requests})
            break
    finally:
        _release_lock(token)


def append_session(rows: list[dict]) -> None:
    _append_rows("Sortir", SORTIR_HEADER, rows)
    # Cuma invalidate cache Sortir -- jangan clear cache Produk/Cabang/Karyawan
    # (Produk isinya ratusan baris, narik ulang tiap Simpan/Hapus itu yang bikin lemot).
    load_sortir.clear()


def delete_session(session_id: str) -> None:
    _delete_session_rows("Sortir", session_id)
    load_sortir.clear()


def update_session(session_id: str, new_rows: list[dict]) -> None:
    delete_session(session_id)
    append_session(new_rows)


def append_laporan(rows: list[dict]) -> None:
    _append_rows("Laporan Harian", LAPORAN_HEADER, rows)
    load_laporan.clear()


def delete_laporan(session_id: str) -> None:
    _delete_session_rows("Laporan Harian", session_id)
    load_laporan.clear()


def update_laporan(session_id: str, new_rows: list[dict]) -> None:
    delete_laporan(session_id)
    append_laporan(new_rows)


def append_operasional(rows: list[dict]) -> None:
    _append_rows("Pengeluaran Operasional", OPERASIONAL_HEADER, rows)
    load_operasional.clear()


def delete_operasional(session_id: str) -> None:
    _delete_session_rows("Pengeluaran Operasional", session_id)
    load_operasional.clear()


def update_operasional(session_id: str, new_rows: list[dict]) -> None:
    delete_operasional(session_id)
    append_operasional(new_rows)


def append_konsinyasi(rows: list[dict]) -> None:
    _append_rows("Konsinyasi", KONSINYASI_HEADER, rows)
    load_konsinyasi.clear()


def delete_konsinyasi(session_id: str) -> None:
    _delete_session_rows("Konsinyasi", session_id)
    load_konsinyasi.clear()


def update_konsinyasi(session_id: str, new_rows: list[dict]) -> None:
    delete_konsinyasi(session_id)
    append_konsinyasi(new_rows)


_KONS_MASTER = {
    "supplier": (KONS_SUPPLIER_SHEET, KONS_SUPPLIER_HEADER),
    "produk": (KONS_PRODUK_SHEET, KONS_PRODUK_HEADER),
}


def _ensure_kons_master(jenis: str):
    title, header = _KONS_MASTER[jenis]
    ws = _find_sheet(title)
    if ws is None:
        ws = get_spreadsheet().add_worksheet(title=title, rows=200, cols=len(header))
        ws.update([header], "A1")
        _worksheets.clear()
    return ws, header


def tambah_konsinyasi_master(jenis: str, row: dict) -> None:
    """Tambah satu supplier/produk di akhir tab master ("supplier"/"produk").
    RAW, bukan USER_ENTERED: No HP "0812..." harus tetap teks, nol di depannya
    tidak boleh hilang."""
    ws, header = _ensure_kons_master(jenis)
    ws.append_rows([[row.get(c, "") for c in header]], value_input_option="RAW")
    load_konsinyasi_master.clear()


def simpan_konsinyasi_master(jenis: str, rows: list[dict]) -> None:
    """Tulis ulang isi tab master dari A1 dengan `rows` (semua baris, urutan
    sama seperti saat dimuat). Sengaja tanpa clear(): baris master tidak
    pernah dihapus -- yang tidak dipakai lagi cukup Aktif = Tidak -- jadi
    menimpa dari A1 sudah cukup, dan kalau koneksi putus di tengah jalan
    isinya tidak sempat terhapus dulu (lihat catatan backfill_penjualan di
    CLAUDE.md)."""
    ws, header = _ensure_kons_master(jenis)
    values = [header] + [[r.get(c, "") for c in header] for r in rows]
    if len(values) > ws.row_count:
        ws.add_rows(len(values) - ws.row_count + 50)
    ws.update(values, "A1", value_input_option="RAW")
    load_konsinyasi_master.clear()
