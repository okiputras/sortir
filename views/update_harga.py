"""
Update Harga (Olshopin) -- tarik harga jual terbaru dari katalog Olshopin,
hitung harga beli (kg -4.000 / satuan -500), tampilkan preview, lalu tulis ke
tab Produk (kolom harga_jual_edit & harga_beli_edit).

Produk yang belum cocok otomatis dibiarkan; pemetaan manual dibaca dari tab
ProdukMapping (nama_barang_edit | nama_olshopin).

Dikunci login owner (session "ops_authenticated"), sama seperti Laporan Sortir.
"""
import os

import pandas as pd
import streamlit as st

from gsheet_client import get_spreadsheet
import olshopin_sync as S

st.title("💰 Update Harga (Olshopin)")

# --- LOGIN GATE (session sama dgn Pengeluaran/Laporan Sortir) ---
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False
if not st.session_state.ops_authenticated:
    st.info("Halaman ini khusus owner. Silakan login dulu.")
    auth_username = os.environ.get("OPS_USERNAME", "oki")
    auth_password = os.environ.get("OPS_PASSWORD", "oki")
    with st.form("update_harga_login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login", type="primary"):
            if username == auth_username and password == auth_password:
                st.session_state.ops_authenticated = True
                st.rerun()
            else:
                st.error("Username / password salah.")
    st.stop()

st.caption(
    "Ambil harga jual terbaru dari katalog Olshopin berdasarkan nama produk, "
    "hitung harga beli otomatis (**kg −4.000**, **satuan −500**), lalu tulis "
    "ke tab **Produk**."
)


@st.cache_data(ttl=21600, show_spinner=False)
def _catalog():
    return S.fetch_catalog()


c1, c2 = st.columns([1, 1])
if c1.button("🔄 Tarik katalog Olshopin", type="primary"):
    with st.spinner("Menarik katalog Olshopin (1 request, ~1–2 dtk)…"):
        st.session_state.olshop_catalog = _catalog()
if c2.button("🧹 Bersihkan cache"):
    _catalog.clear()
    st.session_state.pop("olshop_catalog", None)
    st.info("Cache katalog dibersihkan. Klik 'Tarik katalog' untuk ambil ulang.")

catalog = st.session_state.get("olshop_catalog")
if not catalog:
    st.info("Klik **Tarik katalog Olshopin** untuk mulai.")
    st.stop()

st.success(f"Katalog termuat: {len(catalog):,} produk.".replace(",", "."))

sh = get_spreadsheet()
ws = sh.worksheet("Produk")
rows = ws.get_all_values()[1:]
plan = S.plan_updates(rows, catalog)
matched = [p for p in plan if p["matched"]]
unmatched = [p for p in plan if not p["matched"]]
overridden = sum(1 for p in plan if p.get("override"))

m1, m2, m3 = st.columns(3)
m1.metric("Total produk", len(plan))
m2.metric("Cocok (akan diupdate)", len(matched))
m3.metric("Belum cocok", len(unmatched))
st.caption(
    "Atur langsung di tab **Produk**: kolom **tipe** (kg/satuan) & **nama_olshopin** "
    f"(nama katalog untuk ambil harga). {overridden} produk memakai override nama_olshopin."
)

st.subheader("Preview perubahan (produk cocok)")
df = pd.DataFrame([{
    "Nama": p["nama"], "Tipe": p["tipe"],
    "Jual lama": p["jual_lama"], "Jual baru": p["jual_baru"], "Δ jual": p["jual_baru"] - p["jual_lama"],
    "Beli lama": p["beli_lama"], "Beli baru": p["beli_baru"], "Δ beli": p["beli_baru"] - p["beli_lama"],
    "Olshopin": p["olshopin"],
} for p in matched])
st.dataframe(df, use_container_width=True, hide_index=True, height=420)

with st.expander(f"Belum cocok ({len(unmatched)}) — dibiarkan apa adanya"):
    st.dataframe(
        pd.DataFrame([{"Nama": p["nama"], "Tipe": p["tipe"],
                       "nama_olshopin (diisi tapi tak ada di katalog?)": p["olshopin"] or ""}
                      for p in unmatched]),
        use_container_width=True, hide_index=True,
    )
    st.caption("Untuk mencocokkan: buka tab **Produk**, isi kolom **nama_olshopin** "
               "dengan nama persis di katalog Olshopin (lalu Tarik katalog & cek lagi).")

st.divider()
st.warning("Menerapkan akan **menimpa** harga_jual_edit & harga_beli_edit untuk "
           f"{len(matched)} produk yang cocok. Yang belum cocok tidak diubah.")
if st.button(f"💾 Terapkan ke Sheet ({len(matched)} produk)", type="primary"):
    with st.spinner("Menulis ke sheet…"):
        n = S.apply_updates(ws, plan)
    st.success(f"✅ Selesai — {n} produk diperbarui di tab Produk.")
    st.balloons()
