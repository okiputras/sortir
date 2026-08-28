"""
Daftar kategori & search query terkurasi manual (BUKAN di-generate AI/LLM
tiap run -- lihat catatan di product_intelligence/__init__.py kenapa).
Edit KATEGORI_QUERIES langsung buat nambah/ubah cakupan riset.

Query di bawah dibangun dari nama SUBKATEGORI LEVEL-3 resmi Tokopedia
(dicek 2026-08-28 dgn buka tiap halaman /p/<kategori>/<subkategori> beneran
& baca daftar sub-subkategorinya -- bukan tebakan lagi kayak versi
sebelumnya). Ini penting krn taksonomi Tokopedia kadang gak intuitif:
mis. deterjen/sabun cuci piring/pembersih lantai itu SEMUA di bawah
Kesehatan > Perlengkapan Kebersihan, BUKAN Rumah Tangga > Laundry (yg
isinya cuma alat -- jemuran, setrika, gantungan baju). Versi lama sempat
nembak "deterjen bubuk grosir" ke kategori yg salah krn asumsi struktur
kategorinya keliru.

Query di sini pakai istilah kategori asli (kadang tanpa embel2 "grosir")
krn nama kategori resmi sendiri sudah cukup spesifik buat nge-match
listing yg tepat -- "grosir" ditambah HANYA di komoditas yg emang lazim
dibeli bulk (beras, minyak, madu, dst), bukan dipaksa di semua query kayak
sebelumnya.

Kategori/grouping DITARIK dari tokopedia_kategori_airin.py (KATEGORI_COCOK),
TAPI sengaja BUANG Sayur/Buah/Daging -- produk segar disuplai lokal harian
(lihat views/jadwal_sayur.py), bukan barang yg "ditemukan" dari marketplace.
Juga BUANG subkategori yg ternyata isinya alat/equipment bukan consumable
pas dicek level-3-nya (mis. Rumah Tangga > Laundry & > Kebersihan isinya
mayoritas alat -- ember, sapu, jemuran, setrika -- bukan barang abis pakai).
"""
from typing import Optional

import pandas as pd

from tokopedia_search import _launch_chrome, search_tokopedia

KATEGORI_QUERIES = {
    # -- Makanan & Minuman > Bumbu & Bahan Masakan --
    "bumbu masak instan": ["bumbu masak instan", "kaldu penyedap rasa"],
    "sambal & saus": ["aneka sambal", "saus dressing"],
    "minyak & santan": ["minyak goreng", "santan kelapa"],
    "kecap & terasi": ["kecap manis", "terasi"],

    # -- Makanan & Minuman > lainnya --
    "beras": ["beras putih 5kg grosir", "beras merah"],
    "abon & kerupuk": ["abon sapi", "kerupuk"],
    "kacang & biji-bijian": ["kacang kering", "biji-bijian"],
    "mie instan": ["mie instan", "mie telur"],
    "pasta & bihun": ["aneka pasta", "bihun soun"],
    "biskuit & cokelat": ["biskuit wafer", "cokelat batang"],
    "keripik & camilan": ["keripik", "kacang camilan"],
    "sereal & oat": ["sereal sarapan", "oat"],
    "roti & selai": ["roti tawar", "selai"],
    "kopi": ["kopi kemasan", "kopi bubuk"],
    "teh & sirup": ["teh celup", "sirup"],
    "susu kental manis": ["susu kental manis"],
    "madu": ["madu murni", "madu grosir"],
    "kurma": ["kurma date crown", "kurma grosir 1kg"],
    "air mineral": ["air mineral galon", "air mineral botol"],
    "bahan kue": ["baking powder", "ragi instan", "coklat bubuk masak"],

    # -- Kesehatan > Perlengkapan Kebersihan (taksonomi asli utk consumable
    # kebersihan rumah -- BUKAN Rumah Tangga > Laundry/Kebersihan yg isinya
    # alat) --
    "deterjen": ["deterjen bubuk", "deterjen cair"],
    "sabun cuci piring": ["sabun cuci piring"],
    "pembersih lantai & karbol": ["pembersih lantai", "karbol"],
    "pewangi pakaian": ["pewangi pelembut pakaian"],
    "pengharum ruangan": ["pengharum ruangan"],
    "tisu": ["tissue", "tisu basah"],
    "anti nyamuk & serangga": ["pest control rumah", "obat nyamuk"],

    # -- Perawatan Tubuh --
    "sabun mandi": ["sabun mandi batang", "sabun mandi cair"],
    "shampoo & conditioner": ["shampoo sachet", "conditioner rambut"],
    "pasta gigi & sikat gigi": ["pasta gigi", "sikat gigi"],
    "pembalut wanita": ["pembalut wanita"],
    "alat cukur": ["alat cukur pria", "krim cukur"],

    # -- Ibu & Bayi --
    "popok bayi": ["popok sekali pakai", "pampers"],
    "susu formula": ["susu formula bayi", "susu pertumbuhan anak"],
    "makanan bayi": ["bubur bayi instan", "biskuit bayi"],

    # -- Kesehatan > Obat-Obatan (cuma jenis OTC yg lazim dijual toko,
    # BUKAN kategori resep/penyakit kronis -- lihat komentar exclude di
    # tokopedia_kategori_airin.py) --
    "obat warung": ["obat sakit kepala demam", "obat batuk pilek", "obat mual pencernaan"],
    "vitamin & suplemen": ["multivitamin", "vitamin c", "vitamin d"],
    "masker medis": ["masker medis"],

    # -- Dapur > Penyimpanan Makanan (consumable aja, alat/wadah dibuang) --
    "plastik & aluminium foil": ["plastic wrap", "aluminium foil", "plastik klip"],
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
