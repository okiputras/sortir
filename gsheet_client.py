"""
Koneksi ke Google Sheets & fungsi CRUD untuk sheet "Sortir" dan
"Laporan Harian". Dipakai oleh app.py dan pages/*.py.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

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
    "Tarik Tunai",
    "Tukar Uang",
    "Total",
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


@st.cache_data(ttl=30, show_spinner=False)
def load_sortir():
    ws = get_spreadsheet().worksheet("Sortir")
    return ws.get_all_records()


@st.cache_data(ttl=30, show_spinner=False)
def load_laporan():
    ws = get_spreadsheet().worksheet("Laporan Harian")
    return ws.get_all_records()


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


def _append_rows(sheet_name: str, header: list[str], rows: list[dict]) -> None:
    ws = get_spreadsheet().worksheet(sheet_name)
    values = [[row.get(col, "") for col in header] for row in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")


def _delete_session_rows(sheet_name: str, session_id: str) -> None:
    ws = get_spreadsheet().worksheet(sheet_name)
    matches = ws.findall(session_id, in_column=1)
    if matches:
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
