"""
Pengeluaran Operasional (listrik, PDAM, gaji karyawan, dll).

Beda dari Input Sortir & Laporan Harian yang dipakai semua karyawan,
halaman ini dikunci login sederhana -- cuma owner yang bisa akses,
karena isinya data gaji & biaya operasional.

Kredensial login: default "oki"/"oki", bisa dioverride lewat env var
OPS_USERNAME / OPS_PASSWORD (mis. di Railway) tanpa perlu ubah kode.
"""

import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import (
    append_operasional,
    delete_operasional,
    load_all_operasional,
    update_operasional,
)

JAKARTA = ZoneInfo("Asia/Jakarta")

AUTH_USERNAME = os.environ.get("OPS_USERNAME", "oki")
AUTH_PASSWORD = os.environ.get("OPS_PASSWORD", "oki")

KATEGORI_OPTIONS = ["Listrik", "PDAM", "Gaji Karyawan", "Sewa", "Internet", "Lainnya"]

st.title("🧾 Pengeluaran Operasional")

# --- LOGIN GATE ---
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False

if not st.session_state.ops_authenticated:
    st.info("Halaman ini khusus owner. Silakan login dulu.")
    with st.form("ops_login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")
        if submitted:
            if username == AUTH_USERNAME and password == AUTH_PASSWORD:
                st.session_state.ops_authenticated = True
                st.rerun()
            else:
                st.error("Username atau password salah.")
    st.stop()

_, logout_col = st.columns([5, 1])
with logout_col:
    if st.button("Logout"):
        st.session_state.ops_authenticated = False
        st.rerun()

def empty_pengeluaran() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Kategori": pd.Series(dtype=str),
            "Keterangan": pd.Series(dtype=str),
            "Nominal": pd.Series(dtype=float),
        }
    )


def format_rupiah(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def to_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def reset_form() -> None:
    st.session_state.ops_pengeluaran = empty_pengeluaran()
    st.session_state.ops_tanggal = datetime.now(JAKARTA).date()
    st.session_state.ops_editing_id = None
    st.session_state.ops_form_version += 1


# --- init session state ---
if "ops_form_version" not in st.session_state:
    st.session_state.ops_form_version = 0
if "ops_pengeluaran" not in st.session_state:
    st.session_state.ops_pengeluaran = empty_pengeluaran()
if "ops_tanggal" not in st.session_state:
    st.session_state.ops_tanggal = datetime.now(JAKARTA).date()
if "ops_editing_id" not in st.session_state:
    st.session_state.ops_editing_id = None

# --- load data ---
try:
    with st.spinner("Memuat data..."):
        data = load_all_operasional()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

cabang_records = data["cabang"]
operasional_records = data["operasional"]

if not cabang_records:
    st.warning("Data master Cabang masih kosong. Isi dulu langsung di Google Sheet-nya.")
    st.stop()

cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})

# --- tanggal & cabang ---
col1, col2 = st.columns(2)
with col1:
    tanggal = st.date_input(
        "Tanggal",
        value=st.session_state.ops_tanggal,
        key=f"ops_tanggal_input_{st.session_state.ops_form_version}",
    )

is_editing = bool(st.session_state.ops_editing_id)
with col2:
    cabang = st.selectbox(
        "Cabang", cabang_list, disabled=is_editing, key="ops_cabang_select",
        help="Batal edit dulu untuk ganti cabang." if is_editing else None,
    )

st.divider()

# --- history 2 sesi terakhir untuk cabang ini ---
ops_df = pd.DataFrame(operasional_records) if operasional_records else pd.DataFrame()
if not ops_df.empty:
    hist = ops_df[ops_df["Cabang"] == cabang]
else:
    hist = pd.DataFrame()

if not hist.empty:
    st.subheader("Riwayat 2 sesi terakhir")
    last_ts = hist.groupby("Session ID")["Timestamp"].max().sort_values(ascending=False)
    recent_session_ids = last_ts.index[:2]

    for sid in recent_session_ids:
        sess_rows = hist[hist["Session ID"] == sid].copy()
        first = sess_rows.iloc[0]
        tgl = first["Tanggal"]
        total_val = pd.to_numeric(sess_rows["Nominal"], errors="coerce").fillna(0).sum()

        with st.expander(f"{tgl} — Total {format_rupiah(total_val)}"):
            st.dataframe(
                sess_rows[["Kategori", "Keterangan", "Nominal"]],
                hide_index=True,
                width="stretch",
                column_config={"Nominal": st.column_config.NumberColumn(format="%,d")},
            )
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("Edit sesi ini", key=f"ops_edit_{sid}", width="stretch"):
                item_rows = sess_rows[["Kategori", "Keterangan", "Nominal"]].copy()
                item_rows["Nominal"] = pd.to_numeric(item_rows["Nominal"], errors="coerce")
                st.session_state.ops_pengeluaran = item_rows.reset_index(drop=True)
                st.session_state.ops_tanggal = pd.to_datetime(tgl).date()
                st.session_state.ops_editing_id = sid
                st.session_state.ops_form_version += 1
                st.rerun()
            if bcol2.button("Hapus sesi ini", key=f"ops_del_{sid}", width="stretch"):
                with st.spinner("Menghapus sesi..."):
                    delete_operasional(sid)
                st.success("Sesi berhasil dihapus.")
                st.rerun()
else:
    st.caption("Belum ada riwayat pengeluaran operasional untuk cabang ini.")

st.divider()

if st.session_state.ops_editing_id:
    st.info(f"Mode edit sesi: `{st.session_state.ops_editing_id}`")
    if st.button("Batal edit", key="ops_batal_edit"):
        reset_form()
        st.rerun()

st.subheader("Input Pengeluaran Operasional")
st.caption("Tambah baris pakai ikon + di pojok kanan atas tabel di bawah ini.")

edited = st.data_editor(
    st.session_state.ops_pengeluaran,
    num_rows="dynamic",
    column_config={
        "Kategori": st.column_config.SelectboxColumn(
            "Kategori", options=KATEGORI_OPTIONS, required=False
        ),
        "Keterangan": st.column_config.TextColumn("Keterangan", required=False),
        "Nominal": st.column_config.NumberColumn(
            "Nominal", min_value=0.0, step=1000.0, required=False, format="%,d"
        ),
    },
    hide_index=True,
    width="stretch",
    key=f"ops_pengeluaran_editor_{st.session_state.ops_form_version}",
)

pengeluaran_rows = []
total = 0.0
for _, row in edited.iterrows():
    kat, ket, nom = row.get("Kategori"), row.get("Keterangan"), row.get("Nominal")
    if not kat or not nom:
        continue
    total += nom
    pengeluaran_rows.append({"Kategori": kat, "Keterangan": ket or "", "Nominal": nom})

if pengeluaran_rows:
    st.markdown(f"**Total: {format_rupiah(total)}**")

if st.button(
    "Simpan", type="primary", width="stretch", disabled=not pengeluaran_rows
):
    now = datetime.now(JAKARTA)
    session_id = st.session_state.ops_editing_id or str(uuid.uuid4())

    new_rows = [
        {
            "Session ID": session_id,
            "Tanggal": tanggal.isoformat(),
            "Cabang": cabang,
            "Kategori": r["Kategori"],
            "Keterangan": r["Keterangan"],
            "Nominal": r["Nominal"],
            "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in pengeluaran_rows
    ]

    with st.spinner("Menyimpan..."):
        if st.session_state.ops_editing_id:
            update_operasional(session_id, new_rows)
        else:
            append_operasional(new_rows)

    if st.session_state.ops_editing_id:
        st.success("Sesi berhasil diupdate.")
    else:
        st.success("Data berhasil disimpan.")

    reset_form()
    st.rerun()
