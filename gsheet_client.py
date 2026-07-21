"""
Koneksi ke Google Sheets & fungsi CRUD untuk sheet "Sortir".
Dipakai oleh app.py.
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


def _secrets_available() -> bool:
    # Mengakses st.secrets tanpa file secrets.toml sama sekali akan raise
    # exception, bukan cuma False -- jadi cek keberadaan filenya dulu.
    return os.path.exists(".streamlit/secrets.toml") or os.path.exists(
        os.path.expanduser("~/.streamlit/secrets.toml")
    )


def _load_credentials() -> Credentials:
    # Urutan prioritas: Streamlit secrets (Streamlit Cloud) -> env var (Railway
    # / host lain) -> file lokal (dev di laptop).
    if _secrets_available() and "gcp_service_account" in st.secrets:
        return Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=SCOPES
        )
    env_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if env_json:
        return Credentials.from_service_account_info(json.loads(env_json), scopes=SCOPES)
    return Credentials.from_service_account_file("service_account.json", scopes=SCOPES)


def _load_spreadsheet_id() -> str:
    if _secrets_available() and "spreadsheet_id" in st.secrets:
        return st.secrets["spreadsheet_id"]
    env_id = os.environ.get("SPREADSHEET_ID")
    if env_id:
        return env_id
    with open("spreadsheet_id.txt") as f:
        return f.read().strip()


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    creds = _load_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(_load_spreadsheet_id())


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


def load_all() -> dict:
    """Ambil Produk/Cabang/Karyawan/Sortir sekaligus secara paralel.

    Tiap sheet adalah 1 network call ke Google Sheets (~0.8-1s, didominasi
    latency tetap per-request, bukan ukuran data). Kalau dipanggil berurutan
    totalnya ~3-4 detik; paralel memangkas jadi ~waktu call paling lambat.
    """
    ctx = get_script_run_ctx()

    def _run(fn):
        add_script_run_ctx(ctx=ctx)
        return fn()

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            "produk": ex.submit(_run, load_produk),
            "cabang": ex.submit(_run, load_cabang),
            "karyawan": ex.submit(_run, load_karyawan),
            "sortir": ex.submit(_run, load_sortir),
        }
        return {k: f.result() for k, f in futures.items()}


def append_session(rows: list[dict]) -> None:
    ws = get_spreadsheet().worksheet("Sortir")
    values = [[row.get(col, "") for col in SORTIR_HEADER] for row in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")
    # Cuma invalidate cache Sortir -- jangan clear cache Produk/Cabang/Karyawan
    # (Produk isinya 1442 baris, narik ulang tiap Simpan/Hapus itu yang bikin lemot).
    load_sortir.clear()


def delete_session(session_id: str) -> None:
    ws = get_spreadsheet().worksheet("Sortir")
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
    load_sortir.clear()


def update_session(session_id: str, new_rows: list[dict]) -> None:
    delete_session(session_id)
    append_session(new_rows)
