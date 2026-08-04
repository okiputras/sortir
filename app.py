"""
Entry point. Navigasi antar halaman ada di sini; isi tiap halaman ada di
folder views/.

Jalankan:
    source venv/bin/activate
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Toko Sayur", page_icon="🥬", layout="centered")

pg = st.navigation(
    [
        st.Page(
            "views/laporan_transaksi_harian.py",
            title="Laporan Transaksi Harian",
            icon="🧾",
            default=True,
        ),
        st.Page("views/input_sortir.py", title="Input Sortir", icon="🥬"),
        st.Page(
            "views/pengeluaran_operasional.py",
            title="Pengeluaran Operasional",
            icon="🔒",
        ),
        st.Page("views/laporan_sortir.py", title="Laporan Sortir", icon="📉"),
    ]
)
pg.run()
