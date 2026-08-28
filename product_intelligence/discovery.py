"""
Daftar kategori & search query terkurasi manual (BUKAN di-generate AI/LLM
tiap run -- lihat catatan di product_intelligence/__init__.py kenapa).
Edit KATEGORI_QUERIES langsung buat nambah/ubah cakupan riset.

Query dipilih dari pengalaman riset manual sebelumnya: kata "grosir" doang
gampang ke-match penjual TAS/kemasan (bukan bahan pokok), jadi tiap query
sengaja gabungin nama produk/brand spesifik + "grosir" di beberapa,
pencarian umum kategori di yang lain -- baca komentar tiap kategori.

Kategori/grouping di bawah DITARIK dari tokopedia_kategori_airin.py
(KATEGORI_COCOK -- hasil scrape+kurasi struktur kategori resmi Tokopedia yg
cocok buat toko sembako/grosir spt Airin), TAPI sengaja BUANG Sayur/Buah/
Daging dari sana -- produk segar itu disuplai lokal harian (lihat
views/jadwal_sayur.py), bukan barang yg "ditemukan" & di-restock dari
marketplace kayak barang kemasan di bawah ini.
"""
from typing import Optional

import pandas as pd

from tokopedia_search import _launch_chrome, search_tokopedia

KATEGORI_QUERIES = {
    # -- Makanan & Minuman (kemasan/kering, BUKAN sayur/buah/daging segar) --
    "madu": ["madu grosir", "madu murni 1kg"],
    "kurma": ["kurma date crown", "kurma grosir 1kg"],
    "bumbu & bahan masakan": ["knorr bumbu grosir", "royco bumbu grosir", "totole bumbu"],
    "abon": ["abon sapi grosir", "abon ayam crunchy"],
    "makanan kering": ["kacang kering grosir", "kismis grosir", "granola grosir"],
    "kopi": ["kopi sachet grosir", "kopi kapal api grosir"],
    "mie & pasta": ["mie sedaap grosir", "pop mie grosir", "pasta spaghetti grosir"],
    "minuman kemasan": ["teh kotak grosir", "sirup marjan grosir"],
    "makanan ringan": ["snack kiloan grosir", "keripik kentang grosir"],
    "makanan sarapan": ["sereal sarapan grosir", "oatmeal quaker grosir"],
    "beras & shirataki": ["beras premium 5kg grosir", "beras shirataki grosir"],
    "bahan kue": ["tepung terigu grosir", "ragi fermipan grosir"],

    # -- Rumah Tangga --
    "kebersihan rumah": ["sabun cuci piring grosir", "pewangi pakaian grosir"],
    "laundry": ["deterjen bubuk grosir", "pelicin pakaian grosir"],
    "kebutuhan rumah": ["kantong plastik grosir", "tisu grosir"],

    # -- Perawatan Tubuh --
    "perlengkapan mandi": ["sabun mandi grosir", "shampoo sachet grosir"],
    "perawatan rambut": ["shampoo grosir", "minyak rambut grosir"],
    "kesehatan gigi & mulut": ["pasta gigi grosir", "sikat gigi grosir"],
    "produk kewanitaan": ["pembalut grosir", "pantyliner grosir"],
    "grooming": ["pisau cukur grosir", "silet cukur grosir"],

    # -- Ibu & Bayi --
    "popok": ["popok bayi grosir", "pampers grosir"],
    "aksesori popok": ["tisu basah bayi grosir", "kapas bayi grosir"],
    "susu bayi & anak": ["susu formula grosir", "susu kental manis grosir"],
    "makanan bayi": ["bubur bayi grosir", "biskuit bayi grosir"],

    # -- Kesehatan --
    "obat-obatan": ["obat warung grosir", "paracetamol grosir"],
    "vitamin & suplemen": ["vitamin c grosir", "multivitamin grosir"],
    "masker medis": ["masker medis grosir", "masker kesehatan grosir"],
    "perlengkapan kebersihan": ["hand sanitizer grosir", "tisu antiseptik grosir"],

    # -- Dapur (cuma consumable, bukan alat masak -- lihat KATEGORI_COCOK) --
    "kemasan makanan": ["plastik wrap grosir", "kantong kresek grosir"],
    "penyimpanan makanan": ["plastik ziplock grosir", "wadah makanan sekali pakai grosir"],
}


def run_discovery(kategori_list: Optional[list] = None, n_per_query: int = 12) -> pd.DataFrame:
    """Jalankan semua query di KATEGORI_QUERIES (atau cuma yg namanya ada
    di `kategori_list` kalau diisi), gabung hasilnya jadi satu DataFrame
    dgn kolom tambahan 'kategori' & 'query'. Satu Chrome dipakai bareng
    utk semua query (lebih cepat drpd buka-tutup Chrome tiap kategori)."""
    kategori_terpilih = kategori_list or list(KATEGORI_QUERIES)
    tidak_dikenal = set(kategori_terpilih) - set(KATEGORI_QUERIES)
    if tidak_dikenal:
        raise ValueError(
            f"Kategori gak dikenal: {tidak_dikenal}. Pilihan: {list(KATEGORI_QUERIES)}"
        )

    proc = _launch_chrome()
    baris = []
    try:
        for kat in kategori_terpilih:
            for q in KATEGORI_QUERIES[kat]:
                print(f"  mencari: {q} ...")
                hasil = search_tokopedia(q, n=n_per_query)
                for h in hasil:
                    h["kategori"] = kat
                    h["query"] = q
                    baris.append(h)
    finally:
        proc.terminate()

    return pd.DataFrame(baris)
