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

with st.expander("⚙️ Pengaturan lanjutan (buffer, kecualikan bulan)"):
    buffer_pct = st.number_input(
        "Buffer keamanan (%)", min_value=0, max_value=100, value=10, step=5,
        key="jadwal_buffer",
        help="Ditambahkan ke rata-rata bertren sebelum jadi rekomendasi, biar tidak pas-pasan.",
    )
    bulan_dikecualikan = st.multiselect(
        "Kecualikan bulan tertentu dari perhitungan (mis. bulan puasa)",
        options=bulan_ada_pagi, default=[], key="jadwal_exclude",
    )

produk_rows = get_spreadsheet().worksheet("Produk").get_all_values()[1:]
# trend_avg_qty -> {nama_norm: (nama_asli, rata2_flat, rata2_tren, slope)}; pakai
# rata2_tren (bukan flat) supaya cabang yg lagi tren naik/turun (bukan stagnan)
# tidak ketarik ke rata-rata lama yg sudah tidak mewakili kondisi sekarang.
pagi_map = SH.trend_avg_qty(jadwal_cabang, months=jadwal_bulan, periode="Pagi",
                             exclude_bulan=bulan_dikecualikan)
siang_map = SH.trend_avg_qty(jadwal_cabang, months=jadwal_bulan, periode="Siang",
                              exclude_bulan=bulan_dikecualikan)

baris_jadwal = []
for row in produk_rows:
    nama = row[0] if row else ""
    if not str(nama).strip():
        continue
    tipe_cell = row[3] if len(row) > 3 else ""
    satuan = tipe_cell.strip() if tipe_cell else "-"
    is_kg = S.resolve_kg(nama, tipe_cell)  # sama persis dgn logika sinkronisasi harga
    n = S.norm(nama)
    vp = pagi_map.get(n) or pagi_map.get(S._strip_kg(n))
    vs = siang_map.get(n) or siang_map.get(S._strip_kg(n))
    if not vp and not vs:
        continue  # tidak ada histori sama sekali -- tidak usah ditampilkan
    tren_pagi = vp[2] if vp else 0.0
    tren_siang = vs[2] if vs else 0.0
    pagi_dipakai = tren_pagi * (1 + buffer_pct / 100)
    siang_dipakai = tren_siang * (1 + buffer_pct / 100)
    baris_jadwal.append({
        "Produk": nama,
        "Satuan": satuan,
        "Siapkan jam 4 pagi": round(pagi_dipakai, 1),
        "Tambah jam 12 siang": round(siang_dipakai, 1),
        "Total/hari": round(pagi_dipakai + siang_dipakai, 1),
        "_is_kg": is_kg,  # internal -- cuma dipakai buat urutan, dibuang sblm tampil
    })

if not baris_jadwal:
    st.info("Belum ada produk di tab Produk yang cocok dengan histori penjualan.")
else:
    # satuan dulu, baru kg an -- dlm tiap kelompok diurutkan dari yg paling laris
    baris_jadwal.sort(key=lambda b: (b["_is_kg"], -b["Total/hari"]))
    dipakai = [b for b in bulan_ada_pagi if b not in bulan_dikecualikan][:jadwal_bulan]
    st.caption(
        f"Data **{jadwal_cabang}** dipakai dari {len(dipakai)} bulan terakhir yang ada: "
        f"{', '.join(dipakai)}"
        + (f" ({len(bulan_dikecualikan)} bulan dikecualikan)" if bulan_dikecualikan else "")
        + f". Sudah + buffer {buffer_pct}%."
    )
    df_jadwal = pd.DataFrame(baris_jadwal).drop(columns=["_is_kg"])
    st.dataframe(df_jadwal, use_container_width=True, hide_index=True, height=420)
