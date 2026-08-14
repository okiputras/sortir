"""
Jadwal Sayur Pagi/Siang -- rata-rata sayur terjual per hari, dipecah sebelum
jam 12 (siapkan jam 4 pagi) vs jam 12 ke atas (tambah jam 12 siang), supaya
sayur tidak keluar sekaligus semua pagi lalu layu di showcase. Tujuannya
mengurangi sortiran.

Sumber datanya diupload di menu Update Harga (Olshopin) -> Upload Data
Penjualan (owner). Halaman INI sendiri terbuka utk semua karyawan tanpa
login, sama seperti Input Sortir -- isinya cuma rekomendasi jumlah
siap-siap, bukan data finansial.
"""
import pandas as pd
import streamlit as st

from gsheet_client import get_spreadsheet, load_cabang
import olshopin_sync as S
import sales_history as SH

st.title("🥬 Jadwal Sayur Pagi/Siang")
st.caption(
    "Rata-rata terjual per hari, dipecah **sebelum jam 12 (siapkan jam 4 pagi)** "
    "vs **jam 12 ke atas (tambah jam 12 siang)** -- khusus produk yang ada di tab "
    "**Produk** (sayur sortir), biar sayur tidak keluar sekaligus semua pagi lalu "
    "layu di showcase."
)

cabang_records = load_cabang()
cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})

if not cabang_list:
    st.warning("Data master **Cabang** masih kosong. Isi dulu tab Cabang di Google Sheet.")
    st.stop()

c1, c2 = st.columns([1, 1])
jadwal_cabang = c1.selectbox("Cabang", cabang_list, key="jadwal_cabang")
jadwal_bulan = c2.number_input(
    "Pakai berapa bulan data terakhir?",
    min_value=1, max_value=12, value=3, step=1, key="jadwal_bulan",
    help="Rasio pagi/siang bisa bergeser antar bulan (mis. bulan puasa) -- "
         "coba beberapa angka & bandingkan kalau hasilnya jauh beda.",
)

SH.ensure_periode_seeded(jadwal_cabang)
bulan_ada_pagi = sorted(SH.bulan_terupload(jadwal_cabang, periode="Pagi"), reverse=True)
if not bulan_ada_pagi:
    st.info(
        f"Belum ada data penjualan untuk **{jadwal_cabang}**. Minta owner upload dulu "
        "di menu **Update Harga (Olshopin)** → Upload Data Penjualan."
    )
    st.stop()

produk_rows = get_spreadsheet().worksheet("Produk").get_all_values()[1:]
pagi_map = SH.avg_daily_qty(jadwal_cabang, months=jadwal_bulan, periode="Pagi")
siang_map = SH.avg_daily_qty(jadwal_cabang, months=jadwal_bulan, periode="Siang")

baris_jadwal = []
for row in produk_rows:
    nama = row[0] if row else ""
    if not str(nama).strip():
        continue
    satuan = row[3].strip() if len(row) > 3 and row[3] else "-"
    n = S.norm(nama)
    vp = pagi_map.get(n) or pagi_map.get(S._strip_kg(n))
    vs = siang_map.get(n) or siang_map.get(S._strip_kg(n))
    if not vp and not vs:
        continue  # tidak ada histori sama sekali -- tidak usah ditampilkan
    avg_pagi = vp[1] if vp else 0.0
    avg_siang = vs[1] if vs else 0.0
    baris_jadwal.append({
        "Produk": nama,
        "Satuan": satuan,
        "Siapkan jam 4 pagi": round(avg_pagi, 1),
        "Tambah jam 12 siang": round(avg_siang, 1),
        "Total/hari": round(avg_pagi + avg_siang, 1),
    })

if not baris_jadwal:
    st.info("Belum ada produk di tab Produk yang cocok dengan histori penjualan.")
else:
    baris_jadwal.sort(key=lambda b: b["Total/hari"], reverse=True)
    dipakai = bulan_ada_pagi[:jadwal_bulan]
    st.caption(
        f"Data **{jadwal_cabang}** dipakai dari {len(dipakai)} bulan terakhir yang ada: "
        f"{', '.join(dipakai)}."
    )
    st.dataframe(pd.DataFrame(baris_jadwal), use_container_width=True, hide_index=True, height=420)
