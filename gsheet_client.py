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
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

JAKARTA = ZoneInfo("Asia/Jakarta")

LOCK_SHEET = "_Lock"
LOCK_TIMEOUT_SECONDS = 15
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


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    creds = _load_credentials()
    client = gspread.authorize(creds)
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


def _data_sheets(base_name: str) -> list:
    """Semua worksheet yang jadi sumber data untuk base_name ini: sheet
    lama (nama polos, isinya data sebelum fitur pemisahan-per-bulan ada)
    kalau masih ada, lalu semua sheet bulanan "Base_MM_YYYY", diurutkan
    kronologis lama -> baru. Dipakai supaya laporan tetap bisa melihat
    seluruh histori walau datanya sekarang tersebar per bulan."""
    sh = get_spreadsheet()
    pattern = _monthly_sheet_pattern(base_name)
    legacy = None
    monthly = []
    for ws in sh.worksheets():
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
    sh = get_spreadsheet()
    title = _monthly_sheet_name(base_name, dt)
    titles = {ws.title for ws in sh.worksheets()}
    if title in titles:
        return sh.worksheet(title)
    ws = sh.add_worksheet(title=title, rows=1000, cols=max(len(header), 1))
    ws.update([header], "A1")
    return ws


@st.cache_data(ttl=300, show_spinner=False)
def load_produk():
    ws = get_spreadsheet().worksheet("Produk")
    return ws.get_all_records()


@st.cache_data(ttl=300, show_spinner=False)
def load_cabang():
    ws = get_spreadsheet().worksheet("Cabang")
    return ws.get_all_records()


@st.cache_data(ttl=300, show_spinner=False)
def load_karyawan():
    ws = get_spreadsheet().worksheet("Karyawan")
    return ws.get_all_records()


def _load_all_records(base_name: str) -> list[dict]:
    # Baris yang di-soft-delete (lihat _delete_session_rows) isinya
    # dikosongkan, bukan dihapus fisik -- filter di sini biar tidak
    # nongol sebagai baris kosong di UI.
    records = []
    for ws in _data_sheets(base_name):
        records.extend(r for r in ws.get_all_records() if r.get("Session ID"))
    return records


@st.cache_data(ttl=30, show_spinner=False)
def load_sortir():
    return _load_all_records("Sortir")


@st.cache_data(ttl=30, show_spinner=False)
def load_laporan():
    return _load_all_records("Laporan Harian")


@st.cache_data(ttl=30, show_spinner=False)
def load_operasional():
    return _load_all_records("Pengeluaran Operasional")


def _parallel_load(jobs: dict) -> dict:
    """Jalankan beberapa fungsi loader sekaligus secara paralel (bukan
    berurutan) supaya latency network per-request tidak menumpuk."""
    ctx = get_script_run_ctx()

    def _run(fn):
        add_script_run_ctx(ctx=ctx)
        return fn()

    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as ex:
        futures = {k: ex.submit(_run, fn) for k, fn in jobs.items()}
        return {k: f.result() for k, f in futures.items()}


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


def _ensure_lock_sheet():
    sh = get_spreadsheet()
    titles = {ws.title for ws in sh.worksheets()}
    if LOCK_SHEET not in titles:
        ws = sh.add_worksheet(title=LOCK_SHEET, rows=2, cols=2)
        ws.update([["token", "acquired_at"]], "A1")
        return ws
    return sh.worksheet(LOCK_SHEET)


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
        time.sleep(random.uniform(0.2, 0.6))
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
    langsung berhenti (satu sesi cuma pernah ditulis ke satu sheet)."""
    token = _acquire_lock()
    try:
        for ws in _data_sheets(base_name):
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
