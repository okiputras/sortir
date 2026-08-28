"""
Daftar kategori & search query terkurasi manual (BUKAN di-generate AI/LLM
tiap run -- lihat catatan di product_intelligence/__init__.py kenapa).
Edit KATEGORI_QUERIES langsung buat nambah/ubah cakupan riset.

Query dipilih dari pengalaman riset manual sebelumnya: kata "grosir" doang
gampang ke-match penjual TAS/kemasan (bukan bahan pokok), jadi tiap query
sengaja gabungin nama produk/brand spesifik + "grosir" di beberapa,
pencarian umum kategori di yang lain -- baca komentar tiap kategori.
"""
from typing import Optional

import pandas as pd

from tokopedia_search import _launch_chrome, search_tokopedia

KATEGORI_QUERIES = {
    "madu": ["madu grosir", "madu murni 1kg"],
    "kurma": ["kurma date crown", "kurma grosir 1kg"],
    "bumbu instan": ["knorr bumbu grosir", "royco bumbu grosir", "totole bumbu"],
    "abon": ["abon sapi grosir", "abon ayam crunchy"],
    "makanan kering": ["kacang kering grosir", "kismis grosir", "granola grosir"],
    "kopi": ["kopi sachet grosir", "kopi kapal api grosir"],
    "mie instan": ["mie sedaap grosir", "pop mie grosir"],
    "minuman kemasan": ["teh kotak grosir", "sirup marjan grosir"],
    "snack": ["snack kiloan grosir", "keripik kentang grosir"],
    "household": ["sabun cuci piring grosir", "pewangi pakaian grosir"],
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
