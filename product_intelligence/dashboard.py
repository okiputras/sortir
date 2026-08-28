"""
Dashboard Streamlit -- terpisah dari app.py yg di-deploy (lihat alasan di
product_intelligence/__init__.py). Jalankan manual dari laptop:

    streamlit run product_intelligence/dashboard.py

Hasil tiap riset otomatis disimpan ke product_intelligence/hasil/ (CSV
bertanggal) -- biar gak perlu scrape ulang Tokopedia tiap buka dashboard,
dan ada jejak histori riset dari waktu ke waktu.
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from product_intelligence.discovery import KATEGORI_QUERIES
from product_intelligence.pipeline import DEFAULT_AIRIN_FILE, run_pipeline

JAKARTA = ZoneInfo("Asia/Jakarta")
HASIL_DIR = os.path.join(os.path.dirname(__file__), "hasil")
os.makedirs(HASIL_DIR, exist_ok=True)

st.set_page_config(page_title="Airin Product Intelligence", page_icon="🔍", layout="wide")
st.title("🔍 Airin Product Intelligence")
st.caption(
    "Cari produk yang laris di Tokopedia tapi belum ada di katalog Airin. "
    "Tool riset lokal -- gak nyambung ke app toko sehari-hari."
)

with st.sidebar:
    st.header("⚙️ Pengaturan Riset")
    airin_file = st.text_input("File master Airin (.xls)", value=DEFAULT_AIRIN_FILE)
    kategori_pilih = st.multiselect(
        "Kategori yang dicek", options=list(KATEGORI_QUERIES), default=list(KATEGORI_QUERIES)[:3],
        help="Tiap kategori punya beberapa search query -- lihat/edit di discovery.py",
    )
    n_per_query = st.slider("Maks produk per query", min_value=5, max_value=25, value=12)
    st.caption("⏱️ Tiap query butuh ~5-8 detik (buka Tokopedia beneran) -- 3 kategori x 2 query ≈ 1 menit.")
    jalankan = st.button("🚀 Jalankan Riset", type="primary", use_container_width=True)

    st.divider()
    st.subheader("📂 Hasil Tersimpan")
    file_tersimpan = sorted(os.listdir(HASIL_DIR), reverse=True) if os.path.isdir(HASIL_DIR) else []
    file_dipilih = st.selectbox("Buka hasil riset sebelumnya", ["(tidak ada)"] + file_tersimpan)

if jalankan:
    if not kategori_pilih:
        st.warning("Pilih minimal 1 kategori dulu.")
        st.stop()
    with st.spinner(f"Riset {len(kategori_pilih)} kategori ke Tokopedia... (jangan tutup tab ini)"):
        try:
            matched = run_pipeline(kategori_pilih, n_per_query=n_per_query, airin_file=airin_file)
        except Exception as e:
            st.error(f"Riset gagal: {e}")
            st.stop()
    ts = datetime.now(JAKARTA).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(HASIL_DIR, f"riset_{ts}.csv")
    matched.to_csv(path, index=False)
    st.session_state["hasil_df"] = matched
    st.session_state["hasil_sumber"] = f"Baru saja dijalankan ({', '.join(kategori_pilih)})"
    st.success(f"Selesai! Hasil disimpan ke {path}")
elif file_dipilih != "(tidak ada)":
    st.session_state["hasil_df"] = None  # perlu direkonstruksi krn kandidat/skor gak ikut ke-CSV apa adanya
    st.session_state["hasil_sumber"] = file_dipilih
    st.session_state["hasil_csv_path"] = os.path.join(HASIL_DIR, file_dipilih)

matched = st.session_state.get("hasil_df")
csv_path = st.session_state.get("hasil_csv_path")

if matched is None and csv_path:
    raw = pd.read_csv(csv_path)
    kandidat = raw[
        (raw["status_airin"] == "BELUM_TERSEDIA") & (raw.get("lolos_retail_fit", True))
    ].sort_values("total", ascending=False) if "total" in raw.columns else raw
    st.caption(f"Menampilkan hasil tersimpan: **{st.session_state.get('hasil_sumber')}**")
elif matched is not None:
    kandidat = matched.attrs.get("kandidat", pd.DataFrame())
    st.caption(f"Sumber: {st.session_state.get('hasil_sumber')}")
else:
    kandidat = None

if kandidat is None:
    st.info("Pilih kategori di sidebar lalu klik **Jalankan Riset**, atau buka hasil riset sebelumnya.")
    st.stop()

if kandidat.empty:
    st.warning("Gak ada kandidat produk ditemukan dari riset ini.")
    st.stop()

# --- filter tampilan ---
c1, c2, c3 = st.columns(3)
prioritas_filter = c1.multiselect(
    "Filter prioritas", options=["🔥 PRIORITAS TINGGI", "⭐ PRIORITAS SEDANG", "⚠️ PERLU VERIFIKASI", "❌ TIDAK DIREKOMENDASIKAN"],
    default=["🔥 PRIORITAS TINGGI", "⭐ PRIORITAS SEDANG"],
)
kategori_filter = c2.multiselect("Filter kategori", options=sorted(kandidat["kategori"].unique()), default=[])
top_n = c3.number_input("Tampilkan berapa produk", min_value=5, max_value=200, value=30, step=5)

tampil = kandidat.copy()
if prioritas_filter:
    tampil = tampil[tampil["prioritas"].isin(prioritas_filter)]
if kategori_filter:
    tampil = tampil[tampil["kategori"].isin(kategori_filter)]
tampil = tampil.head(top_n)

st.subheader(f"📋 {len(tampil)} Produk Direkomendasikan")
kolom_tampil = ["gambar", "prioritas", "nama", "brand", "kategori", "harga", "terjual", "rating", "total", "toko", "lokasi", "alasan"]
kolom_ada = [k for k in kolom_tampil if k in tampil.columns]
st.dataframe(
    tampil[kolom_ada].rename(columns={"total": "score", "nama": "produk"}),
    use_container_width=True, hide_index=True, height=500,
    column_config={
        "gambar": st.column_config.ImageColumn("Gambar", width="small"),
    },
)

st.divider()
st.subheader("📊 Insight")
i1, i2 = st.columns(2)
with i1:
    st.markdown("**Kategori dengan gap terbanyak**")
    st.bar_chart(kandidat["kategori"].value_counts())
with i2:
    st.markdown("**Brand populer yang belum ada di Airin**")
    if "brand" in kandidat.columns:
        brand_counts = kandidat["brand"].value_counts().head(10).reset_index()
        brand_counts.columns = ["brand", "jumlah produk"]
        st.dataframe(brand_counts, hide_index=True, use_container_width=True)

n_tinggi = (kandidat["prioritas"] == "🔥 PRIORITAS TINGGI").sum()
st.info(
    f"**{n_tinggi} produk** masuk Prioritas Tinggi dari total {len(kandidat)} kandidat. "
    "Saran: mulai dari 5-8 produk skor tertinggi buat batch test-order pertama, "
    "baru evaluasi repeat-purchase-nya sebelum nambah lagi."
)
