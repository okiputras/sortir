"""
Airin Product Intelligence -- riset produk marketplace (Tokopedia) yang
laris tapi belum ada di katalog Airin, di-ranking pakai Opportunity Score.

TOOL RISET LOKAL, BUKAN BAGIAN APP YANG DI-DEPLOY. Sengaja dipisah dari
app.py/views/ -- Tokopedia scraping gak reliable (bisa kena rate-limit
kosong, lihat catatan di tokopedia_search.py), jadi gak pantas nempel ke
aplikasi produksi yang staff pakai tiap hari. Jalankan manual dari laptop
kapan owner mau riset produk baru.

Modul:
    matching.py   -- baca katalog Airin (DATA_BARANG*.xls) + normalisasi
                      nama + fuzzy match ke hasil Tokopedia
    scoring.py     -- Opportunity Score & Retail Fit filter
    discovery.py   -- daftar kategori/query kurasi + jalanin pencarian
                      (bungkus tokopedia_search.py yg sudah ada)
    pipeline.py    -- orkestrasi discovery -> matching -> scoring -> ranking,
                      CLI entry point
    dashboard.py   -- Streamlit dashboard (jalan terpisah dari app.py)

Cara pakai cepat:
    python3 -m product_intelligence.pipeline --kategori madu kurma bumbu
    streamlit run product_intelligence/dashboard.py
"""
