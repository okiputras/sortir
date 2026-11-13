"""
Entry point. Navigasi antar halaman ada di sini; isi tiap halaman ada di
folder views/.

Jalankan:
    source venv/bin/activate
    streamlit run app.py
"""

import streamlit as st

# Layout diatur sekali saja per run, di bawah, sesudah halamannya diketahui.
st.set_page_config(page_title="Toko Sayur", page_icon="🥬")

pg = st.navigation(
    [
        st.Page(
            "views/laporan_transaksi_harian.py",
            title="Laporan Transaksi Harian",
            icon="🧾",
            default=True,
        ),
        st.Page("views/input_sortir.py", title="Input Sortir", icon="🥬"),
        st.Page("views/kartu_konsinyasi.py", title="Kartu Konsinyasi", icon="🤝"),
        st.Page("views/jadwal_sayur.py", title="Jadwal Sayur Pagi/Siang", icon="⏰"),
        st.Page(
            "views/pengeluaran_operasional.py",
            title="Pengeluaran Operasional",
            icon="🔒",
        ),
        st.Page("views/laporan_sortir.py", title="Laporan Sortir", icon="📉"),
        st.Page("views/laporan_operasional.py", title="Laporan Operasional", icon="📊"),
        st.Page("views/update_harga.py", title="Update Harga (Olshopin)", icon="💰"),
    ]
)

# Jangan panggil st.set_page_config(layout=...) di halaman: kalau app.py dan
# halaman sama-sama mengatur layout dalam satu run, frontend Streamlit bisa
# menelan salah satunya dan layout berganti lebar/sempit tiap klik.
HALAMAN_LEBAR = {"kartu_konsinyasi"}  # tabel kartu 11 kolom, Sisa Tagihan di kanan
st.set_page_config(layout="wide" if pg.url_path in HALAMAN_LEBAR else "centered")
pg.run()
