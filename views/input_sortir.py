"""
Dashboard input Sortir harian untuk karyawan toko.

Jalankan:
    source venv/bin/activate
    streamlit run app.py
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import (
    append_session,
    delete_session,
    load_all,
    update_session,
)

JAKARTA = ZoneInfo("Asia/Jakarta")

st.title("🥬 Input Sortir Harian")


def empty_line_items() -> pd.DataFrame:
    return pd.DataFrame({"Produk": pd.Series(dtype=str), "Qty": pd.Series(dtype=float)})


def format_rupiah(value) -> str:
    return f"Rp {value:,.0f}".replace(",", ".")


def reset_form() -> None:
    st.session_state.line_items = empty_line_items()
    st.session_state.form_tanggal = datetime.now(JAKARTA).date()
    st.session_state.editing_session_id = None
    st.session_state.form_version += 1


# --- init session state ---
if "form_version" not in st.session_state:
    st.session_state.form_version = 0
if "line_items" not in st.session_state:
    st.session_state.line_items = empty_line_items()
if "form_tanggal" not in st.session_state:
    st.session_state.form_tanggal = datetime.now(JAKARTA).date()
if "editing_session_id" not in st.session_state:
    st.session_state.editing_session_id = None

# --- load semua data sekaligus (paralel, bukan berurutan) ---
try:
    with st.spinner("Memuat data..."):
        data = load_all()
except RuntimeError as e:
    st.error(str(e))
    st.stop()
produk_records = data["produk"]
cabang_records = data["cabang"]
karyawan_records = data["karyawan"]
sortir_records = data["sortir"]

if not produk_records or not cabang_records or not karyawan_records:
    st.warning(
        "Data master (Produk / Cabang / Karyawan) masih ada yang kosong. "
        "Isi dulu langsung di Google Sheet-nya sebelum input sortir."
    )
    st.stop()

# Sheet "Produk" pakai skema katalog toko yang sudah ada:
# nama_barang_edit, harga_jual_edit, harga_beli_edit.
# Harga acuan sortir pakai harga_beli (harga modal -> nilai kerugian sortir).
produk_df = pd.DataFrame(produk_records)
produk_df["nama_barang_edit"] = produk_df["nama_barang_edit"].astype(str).str.strip()
produk_df["harga_beli_edit"] = pd.to_numeric(
    produk_df["harga_beli_edit"], errors="coerce"
).fillna(0)
produk_df = produk_df[produk_df["nama_barang_edit"] != ""]

cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})
karyawan_list = sorted({r["Nama Karyawan"] for r in karyawan_records if r.get("Nama Karyawan")})
produk_names = sorted(produk_df["nama_barang_edit"].unique().tolist())
produk_lookup = dict(zip(produk_df["nama_barang_edit"], produk_df["harga_beli_edit"]))

# --- form utama: tanggal, cabang, nama ---
col1, col2 = st.columns(2)
with col1:
    tanggal = st.date_input(
        "Tanggal",
        value=st.session_state.form_tanggal,
        key=f"tanggal_input_{st.session_state.form_version}",
    )
is_editing = bool(st.session_state.editing_session_id)
with col2:
    cabang = st.selectbox(
        "Cabang", cabang_list, disabled=is_editing,
        help="Batal edit dulu untuk ganti cabang." if is_editing else None,
    )

nama = st.selectbox(
    "Nama Karyawan", karyawan_list, disabled=is_editing,
    help="Batal edit dulu untuk ganti nama karyawan." if is_editing else None,
)

st.divider()

# --- history 2 sesi terakhir untuk nama+cabang ini ---
sortir_df = pd.DataFrame(sortir_records) if sortir_records else pd.DataFrame()

if not sortir_df.empty:
    hist = sortir_df[(sortir_df["Nama Karyawan"] == nama) & (sortir_df["Cabang"] == cabang)]
else:
    hist = pd.DataFrame()

if not hist.empty:
    st.subheader("Riwayat 2 sesi terakhir")
    last_ts = hist.groupby("Session ID")["Timestamp"].max().sort_values(ascending=False)
    recent_session_ids = last_ts.index[:2]

    for sid in recent_session_ids:
        sess_rows = hist[hist["Session ID"] == sid].copy()
        tgl = sess_rows["Tanggal"].iloc[0]
        total = pd.to_numeric(sess_rows["Subtotal"], errors="coerce").fillna(0).sum()

        with st.expander(f"{tgl} — Total {format_rupiah(total)}"):
            st.dataframe(
                sess_rows[["Produk", "Qty", "Harga Satuan", "Subtotal"]],
                hide_index=True,
                width="stretch",
            )
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("Edit sesi ini", key=f"edit_{sid}", width="stretch"):
                edit_items = sess_rows[["Produk", "Qty"]].copy()
                edit_items["Qty"] = pd.to_numeric(edit_items["Qty"], errors="coerce")
                st.session_state.line_items = edit_items.reset_index(drop=True)
                st.session_state.form_tanggal = pd.to_datetime(tgl).date()
                st.session_state.editing_session_id = sid
                st.session_state.form_version += 1
                st.rerun()
            if bcol2.button("Hapus sesi ini", key=f"del_{sid}", width="stretch"):
                with st.spinner("Menghapus sesi..."):
                    delete_session(sid)
                st.success("Sesi berhasil dihapus.")
                st.rerun()
else:
    st.caption("Belum ada riwayat sortir untuk kombinasi nama & cabang ini.")

st.divider()

if st.session_state.editing_session_id:
    st.info(f"Mode edit sesi: `{st.session_state.editing_session_id}`")
    if st.button("Batal edit"):
        reset_form()
        st.rerun()

st.subheader("Input Produk Sortiran")
st.caption("Tambah baris pakai ikon + di pojok kanan atas tabel di bawah ini.")

edited = st.data_editor(
    st.session_state.line_items,
    num_rows="dynamic",
    column_config={
        "Produk": st.column_config.SelectboxColumn(
            "Produk", options=produk_names, required=False
        ),
        "Qty": st.column_config.NumberColumn(
            "Qty", min_value=0.0, step=0.01, required=False
        ),
    },
    hide_index=True,
    width="stretch",
    key=f"line_items_editor_{st.session_state.form_version}",
)
# Catatan: sengaja TIDAK menulis balik `edited` ke st.session_state.line_items
# di sini. Variabel session_state itu cuma dipakai sebagai nilai awal saat
# widget baru dibuat (mis. waktu klik "Edit sesi ini" / reset) -- data_editor
# sendiri sudah menyimpan hasil edit terbaru secara internal berdasarkan
# `key`, jadi `edited` (variabel lokal di bawah) yang jadi sumber kebenaran
# untuk sisa kode di run ini.

# --- preview harga & subtotal (harga otomatis dari database produk) ---
preview_rows = []
total = 0
for _, row in edited.iterrows():
    p, q = row.get("Produk"), row.get("Qty")
    if not p or not q:
        continue
    harga = produk_lookup.get(p, 0)
    subtotal = q * harga
    total += subtotal
    preview_rows.append({"Produk": p, "Qty": q, "Harga Satuan": harga, "Subtotal": subtotal})

if preview_rows:
    st.write("Preview:")
    st.dataframe(pd.DataFrame(preview_rows), hide_index=True, width="stretch")
    st.markdown(f"**Total: {format_rupiah(total)}**")

if st.button("Simpan", type="primary", disabled=not preview_rows, width="stretch"):
    now = datetime.now(JAKARTA)
    session_id = st.session_state.editing_session_id or str(uuid.uuid4())

    new_rows = [
        {
            "Session ID": session_id,
            "Tanggal": tanggal.isoformat(),
            "Nama Karyawan": nama,
            "Cabang": cabang,
            "Produk": r["Produk"],
            "Qty": r["Qty"],
            "Harga Satuan": r["Harga Satuan"],
            "Subtotal": r["Subtotal"],
            "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in preview_rows
    ]

    with st.spinner("Menyimpan..."):
        if st.session_state.editing_session_id:
            update_session(session_id, new_rows)
        else:
            append_session(new_rows)

    if st.session_state.editing_session_id:
        st.success("Sesi berhasil diupdate.")
    else:
        st.success("Data berhasil disimpan.")

    reset_form()
    st.rerun()
