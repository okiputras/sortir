"""
Laporan Transaksi Harian (rekonsiliasi kas per shift/cabang).

Rumus Total:
    - Tidak pakai Petty Cash: Total = Cash - Jumlah Pengeluaran - Qris - Debit - Tf
    - Pakai Petty Cash:       Total = Cash - Qris - Debit - Tf
      (Jumlah pengeluaran tidak dikurangi lagi karena sudah dibayar dari Petty Cash)

Modal dan Tarik Tunai / Tukar Uang cuma informasi -- tidak mempengaruhi Total.
"""

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import (
    append_laporan,
    delete_laporan,
    load_all_laporan,
    update_laporan,
)

JAKARTA = ZoneInfo("Asia/Jakarta")

st.title("🧾 Laporan Transaksi Harian")

NUMERIC_FIELDS = [
    "lap_modal",
    "lap_petty_awal",
    "lap_cash",
    "lap_qris",
    "lap_debit",
    "lap_tf",
    "lap_tarik_tukar",
]


def empty_pengeluaran() -> pd.DataFrame:
    return pd.DataFrame({"Keterangan": pd.Series(dtype=str), "Nominal": pd.Series(dtype=float)})


def format_rupiah(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def to_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_thousands(value) -> str:
    n = int(to_number(value))
    return f"{n:,}".replace(",", ".")


def _digits_to_number(raw: str) -> float:
    digits = re.sub(r"[^\d]", "", raw or "")
    return float(digits) if digits else 0.0


def _reformat_on_change(widget_key: str) -> None:
    st.session_state[widget_key] = _format_thousands(
        _digits_to_number(st.session_state[widget_key])
    )


def rupiah_input(label: str, state_key: str, help: str | None = None) -> float:
    """Input angka dengan tampilan pemisah ribuan titik ala Indonesia
    (mis. 5.000), bukan angka polos. Nilai kanonik (float) disimpan balik
    ke session_state[state_key] supaya bisa dibaca kode lain (mis. rumus
    Total) dan supaya prefill saat mode edit tetap konsisten."""
    widget_key = f"{state_key}_input_{st.session_state.lap_form_version}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = _format_thousands(st.session_state[state_key])
    st.text_input(
        label,
        key=widget_key,
        on_change=_reformat_on_change,
        args=(widget_key,),
        help=help,
    )
    value = _digits_to_number(st.session_state[widget_key])
    st.session_state[state_key] = value
    return value


def reset_form() -> None:
    st.session_state.lap_pengeluaran = empty_pengeluaran()
    st.session_state.lap_tanggal = datetime.now(JAKARTA).date()
    st.session_state.lap_editing_id = None
    for key in NUMERIC_FIELDS:
        st.session_state[key] = 0.0
    st.session_state.lap_form_version += 1


# --- init session state ---
if "lap_form_version" not in st.session_state:
    st.session_state.lap_form_version = 0
if "lap_pengeluaran" not in st.session_state:
    st.session_state.lap_pengeluaran = empty_pengeluaran()
if "lap_tanggal" not in st.session_state:
    st.session_state.lap_tanggal = datetime.now(JAKARTA).date()
if "lap_editing_id" not in st.session_state:
    st.session_state.lap_editing_id = None
for _key in NUMERIC_FIELDS:
    if _key not in st.session_state:
        st.session_state[_key] = 0.0

# --- load data ---
try:
    with st.spinner("Memuat data..."):
        data = load_all_laporan()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

cabang_records = data["cabang"]
karyawan_records = data["karyawan"]
laporan_records = data["laporan"]

if not cabang_records or not karyawan_records:
    st.warning(
        "Data master (Cabang / Karyawan) masih ada yang kosong. "
        "Isi dulu langsung di Google Sheet-nya."
    )
    st.stop()

cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})
karyawan_list = sorted({r["Nama Karyawan"] for r in karyawan_records if r.get("Nama Karyawan")})

# --- tanggal, cabang, nama ---
col1, col2 = st.columns(2)
with col1:
    tanggal = st.date_input(
        "Tanggal",
        value=st.session_state.lap_tanggal,
        key=f"lap_tanggal_input_{st.session_state.lap_form_version}",
    )

is_editing = bool(st.session_state.lap_editing_id)
with col2:
    cabang = st.selectbox(
        "Cabang", cabang_list, disabled=is_editing,
        help="Batal edit dulu untuk ganti cabang." if is_editing else None,
    )

nama = st.selectbox(
    "Nama", karyawan_list, disabled=is_editing,
    help="Batal edit dulu untuk ganti nama." if is_editing else None,
)

st.divider()

# --- history 2 sesi terakhir ---
laporan_df = pd.DataFrame(laporan_records) if laporan_records else pd.DataFrame()
if not laporan_df.empty:
    hist = laporan_df[(laporan_df["Nama"] == nama) & (laporan_df["Cabang"] == cabang)]
else:
    hist = pd.DataFrame()

RUPIAH_COL_FORMAT = "%,d"

if not hist.empty:
    st.subheader("Riwayat 2 sesi terakhir")
    last_ts = hist.groupby("Session ID")["Timestamp"].max().sort_values(ascending=False)
    recent_session_ids = last_ts.index[:2]

    for sid in recent_session_ids:
        sess_rows = hist[hist["Session ID"] == sid].copy()
        first = sess_rows.iloc[0]
        tgl = first["Tanggal"]
        total_val = to_number(first.get("Total"))

        with st.expander(f"{tgl} — Total {format_rupiah(total_val)}"):
            items = sess_rows[sess_rows["Keterangan"].astype(str).str.strip() != ""]
            if not items.empty:
                st.write("Pengeluaran:")
                st.dataframe(
                    items[["Keterangan", "Nominal"]],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Nominal": st.column_config.NumberColumn(format=RUPIAH_COL_FORMAT)
                    },
                )

            ringkasan = {
                "Modal": format_rupiah(first.get("Modal")),
                "Petty Cash Awal": format_rupiah(first.get("Petty Cash Awal")),
                "Cash": format_rupiah(first.get("Cash")),
                "Qris": format_rupiah(first.get("Qris")),
                "Debit": format_rupiah(first.get("Debit")),
                "Tf": format_rupiah(first.get("Tf")),
                "Tarik Tunai / Tukar Uang": format_rupiah(
                    first.get("Tarik Tunai / Tukar Uang")
                ),
            }
            st.dataframe(
                pd.DataFrame(ringkasan.items(), columns=["Field", "Nilai"]),
                hide_index=True,
                width="stretch",
            )

            bcol1, bcol2 = st.columns(2)
            if bcol1.button("Edit sesi ini", key=f"lap_edit_{sid}", width="stretch"):
                item_rows = items[["Keterangan", "Nominal"]].copy()
                item_rows["Nominal"] = pd.to_numeric(item_rows["Nominal"], errors="coerce")
                st.session_state.lap_pengeluaran = item_rows.reset_index(drop=True)
                st.session_state.lap_tanggal = pd.to_datetime(tgl).date()
                st.session_state.lap_modal = to_number(first.get("Modal"))
                st.session_state.lap_petty_awal = to_number(first.get("Petty Cash Awal"))
                st.session_state.lap_cash = to_number(first.get("Cash"))
                st.session_state.lap_qris = to_number(first.get("Qris"))
                st.session_state.lap_debit = to_number(first.get("Debit"))
                st.session_state.lap_tf = to_number(first.get("Tf"))
                st.session_state.lap_tarik_tukar = to_number(
                    first.get("Tarik Tunai / Tukar Uang")
                )
                st.session_state.lap_editing_id = sid
                st.session_state.lap_form_version += 1
                st.rerun()
            if bcol2.button("Hapus sesi ini", key=f"lap_del_{sid}", width="stretch"):
                with st.spinner("Menghapus sesi..."):
                    delete_laporan(sid)
                st.success("Sesi berhasil dihapus.")
                st.rerun()
else:
    st.caption("Belum ada riwayat laporan untuk kombinasi nama & cabang ini.")

st.divider()

if st.session_state.lap_editing_id:
    st.info(f"Mode edit sesi: `{st.session_state.lap_editing_id}`")
    if st.button("Batal edit", key="lap_batal_edit"):
        reset_form()
        st.rerun()

# --- modal & petty cash ---
st.subheader("Modal & Petty Cash")
c1, c2 = st.columns(2)
with c1:
    modal = rupiah_input("Modal (Rp)", "lap_modal")
with c2:
    petty_awal = rupiah_input(
        "Petty Cash Awal (Rp) — opsional", "lap_petty_awal",
        help="Kosongkan (0) kalau shift ini tidak pakai petty cash.",
    )

# --- pengeluaran ---
st.subheader("Pengeluaran")
st.caption("Tambah baris pakai ikon + di pojok kanan atas tabel di bawah ini.")

edited = st.data_editor(
    st.session_state.lap_pengeluaran,
    num_rows="dynamic",
    column_config={
        "Keterangan": st.column_config.TextColumn("Keterangan", required=False),
        "Nominal": st.column_config.NumberColumn(
            "Nominal", min_value=0.0, step=1000.0, required=False, format=RUPIAH_COL_FORMAT
        ),
    },
    hide_index=True,
    width="stretch",
    key=f"lap_pengeluaran_editor_{st.session_state.lap_form_version}",
)

pengeluaran_rows = []
jumlah_pengeluaran = 0.0
for _, row in edited.iterrows():
    ket, nom = row.get("Keterangan"), row.get("Nominal")
    if not ket or not nom:
        continue
    jumlah_pengeluaran += nom
    pengeluaran_rows.append({"Keterangan": ket, "Nominal": nom})

st.markdown(f"**Jumlah Pengeluaran: {format_rupiah(jumlah_pengeluaran)}**")

pakai_petty_cash = petty_awal > 0
if pakai_petty_cash:
    sisa_petty = petty_awal - jumlah_pengeluaran
    st.markdown(f"**Sisa Petty Cash: {format_rupiah(sisa_petty)}**")

# --- pembayaran ---
st.subheader("Pembayaran")
c1, c2 = st.columns(2)
with c1:
    cash = rupiah_input("Cash (Rp)", "lap_cash")
    debit = rupiah_input("Debit (Rp)", "lap_debit")
with c2:
    qris = rupiah_input("Qris (Rp)", "lap_qris")
    tf = rupiah_input("Tf (Rp)", "lap_tf")

tarik_tukar = rupiah_input(
    "Tarik Tunai / Tukar Uang (Rp)", "lap_tarik_tukar",
    help="Informasi saja, tidak mempengaruhi rumus Total.",
)

# --- rumus Total ---
if pakai_petty_cash:
    total = cash - qris - debit - tf
    rumus_text = "Cash − Qris − Debit − Tf (pakai Petty Cash, Jumlah Pengeluaran tidak dikurangi lagi)"
else:
    total = cash - jumlah_pengeluaran - qris - debit - tf
    rumus_text = "Cash − Jumlah Pengeluaran − Qris − Debit − Tf"

st.divider()
st.markdown(f"### Total: {format_rupiah(total)}")
st.caption(f"Rumus: {rumus_text}")

if st.button("Simpan", type="primary", width="stretch"):
    now = datetime.now(JAKARTA)
    session_id = st.session_state.lap_editing_id or str(uuid.uuid4())

    common = {
        "Session ID": session_id,
        "Tanggal": tanggal.isoformat(),
        "Nama": nama,
        "Cabang": cabang,
        "Modal": modal,
        "Petty Cash Awal": petty_awal,
        "Cash": cash,
        "Qris": qris,
        "Debit": debit,
        "Tf": tf,
        "Tarik Tunai / Tukar Uang": tarik_tukar,
        "Total": total,
        "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if pengeluaran_rows:
        new_rows = [
            dict(common, Keterangan=r["Keterangan"], Nominal=r["Nominal"])
            for r in pengeluaran_rows
        ]
    else:
        new_rows = [dict(common, Keterangan="", Nominal=0)]

    with st.spinner("Menyimpan..."):
        if st.session_state.lap_editing_id:
            update_laporan(session_id, new_rows)
        else:
            append_laporan(new_rows)

    if st.session_state.lap_editing_id:
        st.success("Laporan berhasil diupdate.")
    else:
        st.success("Laporan berhasil disimpan.")

    reset_form()
    st.rerun()
