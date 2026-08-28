"""
Peta kategori/subkategori Tokopedia yang relevan buat kebutuhan Airin
Freshmart -- toko grosir/sayur eceran (BUKAN toko serba-ada), lihat definisi
bisnis di CLAUDE.md root repo.

Sumber: https://www.tokopedia.com/p (29 kategori top-level Tokopedia, dicek
2026-08-28 via scrape headless -- lihat product_intelligence/discovery.py
buat cara scrape-nya). 7 kategori top-level yang SECARA UMUM masuk akal
buat toko grosir/sembako/sayur dibuka satu-satu utk lihat subkategorinya;
22 sisanya (Elektronik, Fashion x4, Otomotif, Properti, Gaming, Buku, dst)
langsung dibuang tanpa dicek lebih dalam krn jelas gak nyambung.

Kegunaan: referensi buat nentuin cakupan riset produk baru -- baik buat
nambah KATEGORI_QUERIES di discovery.py (skema search-keyword sekarang),
atau (opsi lebih akurat ke depan) scrape LANGSUNG dari halaman kategori
Tokopedia (https://www.tokopedia.com/p/<kategori>/<subkategori>, bisa
diurutkan by "Terlaris") drpd nembak keyword pencarian -- kategori resmi
Tokopedia lebih lengkap & gak kena masalah keyword yg salah nyasar
(mis. "grosir" nyasar ke toko tas, lihat catatan di discovery.py).
"""

# --------------------------------------------------------------------------
# kategori top-level yang RELEVAN (dibuka subkategorinya) + yang DIKECUALIKAN
# --------------------------------------------------------------------------
KATEGORI_COCOK = {
    "makanan-minuman": {
        "nama": "Makanan & Minuman",
        "alasan": "Inti bisnis Airin -- sembako, bumbu, minuman kemasan, sayur/buah segar.",
        "subkategori": {
            "sayur": "Sayur",
            "buah": "Buah",
            "daging": "Daging",
            "bumbu-bahan-masakan": "Bumbu & Bahan Masakan",
            "beras-shirataki-dan-porang": "Beras, Shirataki dan Porang",
            "makanan-kering": "Makanan Kering",
            "mie-pasta": "Mie & Pasta",
            "makanan-ringan": "Makanan Ringan",
            "makanan-sarapan": "Makanan Sarapan",
            "minuman": "Minuman",
            "bahan-kue": "Bahan Kue",
        },
        "subkategori_dikecualikan": {
            "kue": "kue jadi/bakery -- bukan bahan mentah yg dijual Airin",
            "makanan-jadi": "makanan siap-saji, di luar model sortir/eceran toko",
            "hampers-parsel-dan-paket-makanan": "parsel/gift, bukan kebutuhan harian",
            "produk-mengandung-babi": "di luar cakupan produk toko",
        },
    },
    "rumah-tangga": {
        "nama": "Rumah Tangga",
        "alasan": "Kebutuhan harian yg lazim dijual minimarket/toko sembako (deterjen, sabun cuci).",
        "subkategori": {
            "kebersihan": "Kebersihan",
            "laundry": "Laundry",
            "kebutuhan-rumah": "Kebutuhan Rumah",
        },
        "subkategori_dikecualikan": {
            "dekorasi": "furniture/dekor, bukan consumable",
            "furniture": "furniture, bukan consumable",
            "kamar-mandi": "perlengkapan/furnitur kamar mandi, bukan consumable",
            "kamar-tidur": "furniture, bukan consumable",
            "ruang-tamu-keluarga": "furniture, bukan consumable",
            "taman": "di luar cakupan toko",
            "tempat-penyimpanan": "produk tahan lama/non-consumable, prioritas rendah",
            "travel": "di luar cakupan toko",
        },
    },
    "perawatan-tubuh": {
        "nama": "Perawatan Tubuh",
        "alasan": "Toiletries dasar yg lazim ada di rak minimarket/toko sembako.",
        "subkategori": {
            "perlengkapan-mandi": "Perlengkapan Mandi",
            "perawatan-rambut": "Perawatan Rambut",
            "kesehatan-gigi-mulut": "Kesehatan Gigi & Mulut",
            "produk-kewanitaan": "Produk Kewanitaan",
            "grooming": "Grooming",
        },
        "subkategori_dikecualikan": {
            "parfum-cologne-fragrance": "produk gift/premium, bukan segmen toko sembako",
            "perawatan-kaki-tangan": "niche, bukan consumable harian",
            "perawatan-kuku": "niche, bukan consumable harian",
            "perawatan-kulit": "segmen skincare, biasanya di luar rak toko sembako",
            "perawatan-mata": "niche/medis",
            "perawatan-telinga": "niche/medis",
        },
    },
    "ibu-bayi": {
        "nama": "Ibu & Bayi",
        "alasan": "Popok & susu formula termasuk item repeat-purchase tinggi di toko sembako.",
        "subkategori": {
            "popok": "Popok",
            "aksesori-popok": "Aksesori Popok",
            "susu-bayi-anak": "Susu Bayi & Anak",
            "makanan-bayi": "Makanan Bayi",
        },
        "subkategori_dikecualikan": {
            "aktivitas-bayi": "mainan/perlengkapan, bukan consumable",
            "makanan-susu-ibu-hamil": "niche, volume rendah utk toko kecil",
            "peralatan-perlengkapan-menyusui": "alat, bukan consumable repeat-buy",
            "perawatan-bayi": "tumpang tindih sama Perawatan Tubuh, cek per-produk aja",
            "perlengkapan-perawatan-ibu": "niche",
            "perlengkapan-makan-bayi": "alat, bukan consumable",
            "perlengkapan-mandi-bayi": "tumpang tindih Perawatan Tubuh",
            "perlengkapan-tidur-bayi": "furniture/alat",
            "stroller-alat-bantu-bawa-bayi": "barang tahan lama/mahal, di luar segmen",
            "tempat-sampah-popok-isi-ulang": "alat, bukan consumable",
        },
    },
    "kesehatan": {
        "nama": "Kesehatan",
        "alasan": "Obat OTC & vitamin umum sering jadi item impulse-buy di toko sembako.",
        "subkategori": {
            "obat-obatan": "Obat - Obatan",
            "vitamin-suplemen": "Vitamin & Suplemen",
            "masker-medis-pelindung-wajah": "Masker Medis & Pelindung Wajah",
            "perlengkapan-kebersihan": "Perlengkapan Kebersihan",
        },
        "subkategori_dikecualikan": {
            "essential-oil": "niche",
            "kesehatan-wanita": "niche/medis, volume rendah",
            "perlengkapan-medis": "peralatan medis, di luar segmen",
            "produk-dewasa": "sensitif, di luar cakupan toko",
            "suplemen-diet": "niche",
            "tes-kehamilan-dan-masa-subur": "niche",
            "tulang-otot-sendi": "niche/medis",
        },
    },
    "dapur": {
        "nama": "Dapur",
        "alasan": "Sebagian besar kategori ini alat masak/kitchenware (bukan consumable) -- CUMA 2 subkategori yg relevan.",
        "subkategori": {
            "kemasan-makanan-dan-minuman": "Kemasan Makanan dan Minuman (plastik wrap, kemasan take-away)",
            "penyimpanan-makanan": "Penyimpanan Makanan (plastik ziplock, wadah sekali pakai)",
        },
        "subkategori_dikecualikan": {
            "aksesoris-dapur": "alat, bukan consumable",
            "alat-masak-khusus": "alat, bukan consumable",
            "bekal": "alat/kemasan tahan lama",
            "peralatan-baking": "alat, bukan consumable",
            "peralatan-dapur": "alat, bukan consumable",
            "peralatan-makan-minum": "alat, bukan consumable",
            "peralatan-masak": "alat, bukan consumable",
            "perlengkapan-cuci-piring": "alat (spons/rak) -- deterjen cuci piringnya ada di Rumah Tangga > Kebersihan",
        },
    },
}

# --------------------------------------------------------------------------
# kategori top-level yang DIKECUALIKAN SELURUHNYA (gak dibuka subkategorinya)
# --------------------------------------------------------------------------
KATEGORI_DIKECUALIKAN_TOTAL = {
    "perawatan-hewan": "Airin toko sembako/sayur, bukan pet shop -- dicek, isinya 100% produk hewan peliharaan.",
    "audio-kamera-elektronik-lainnya": "elektronik, di luar cakupan toko",
    "buku": "di luar cakupan toko",
    "elektronik": "di luar cakupan toko",
    "fashion-anak-bayi": "fashion, di luar cakupan toko",
    "fashion-muslim": "fashion, di luar cakupan toko",
    "fashion-pria": "fashion, di luar cakupan toko",
    "fashion-wanita": "fashion, di luar cakupan toko",
    "film-musik": "di luar cakupan toko",
    "gaming": "di luar cakupan toko",
    "handphone-tablet": "di luar cakupan toko",
    "kecantikan": "kosmetik/makeup -- beda segmen dari toiletries dasar di Perawatan Tubuh",
    "komputer-laptop": "di luar cakupan toko",
    "logam-mulia": "di luar cakupan toko",
    "mainan-hobi": "di luar cakupan toko",
    "office-stationery": "di luar cakupan toko",
    "olahraga": "di luar cakupan toko",
    "otomotif": "di luar cakupan toko",
    "perlengkapan-pesta": "di luar cakupan toko",
    "pertukangan": "di luar cakupan toko",
    "properti": "di luar cakupan toko",
    "tiket-travel-voucher": "di luar cakupan toko",
    "virtual-products": "di luar cakupan toko",
}
