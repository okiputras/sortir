"""
Cocokkan katalog Yulia Frozen Food (hasil yulia_frozenfood_scraper.py) ke
katalog Produk Airin -- cari produk frozen food yg dijual Yulia tapi BELUM
di-stock Airin (peluang sourcing/restock baru dari supplier ini).

Beda sama product_intelligence/ (yg nyari demand-side dari Tokopedia): ini
riset SUPPLY-side -- Yulia itu supplier grosir, bukan sinyal permintaan
pasar, jadi gak ada "terjual"/rating buat Opportunity Score kayak di sana.
Output cuma daftar gap + harga grosir Yulia per kategori, biar owner yg
nilai worth-direstock atau nggak berdasarkan pengalaman toko sendiri.

Reuse fuzzy-matching dari product_intelligence/matching.py (load_airin_catalog,
match_batch) -- normalize_name() di situ didesain buat buang satuan kemasan
(gr/kg/pcs/dus/karton) yg juga muncul di penamaan Yulia, jadi cukup pakai
ulang tanpa modifikasi.

CATATAN: katalog Airin yg dipakai cuma SULFAT (DATA_BARANG_sulfat_terbaru.xls
-- satu2nya yg ada lokal). PIRANHA gak dicek krn filenya gak ada di repo ini;
kalau perlu, jalankan ulang dgn --airin nunjuk ke file PIRANHA kalau sudah ada.

Jalankan:
    python3 yulia_frozenfood_scraper.py --csv /tmp/yulia_semua_produk.csv   # scrape dulu kalau blm ada
    python3 yulia_gap_analysis.py --yulia-csv /tmp/yulia_semua_produk.csv
    python3 yulia_gap_analysis.py --csv-out hasil_gap_yulia.csv
"""
import argparse
import csv

import pandas as pd

from product_intelligence.matching import load_airin_catalog, match_batch

DEFAULT_AIRIN_FILE = "DATA_BARANG_sulfat_terbaru.xls"
DEFAULT_YULIA_CSV = "/tmp/yulia_semua_produk.csv"


def run_gap_analysis(yulia_csv: str = DEFAULT_YULIA_CSV, airin_file: str = DEFAULT_AIRIN_FILE) -> pd.DataFrame:
    print(f"1/3 Baca katalog Airin dari {airin_file} ...")
    airin_df = load_airin_catalog(airin_file)
    print(f"    {len(airin_df)} produk Airin dimuat.")

    print(f"2/3 Baca katalog Yulia dari {yulia_csv} ...")
    yulia_df = pd.read_csv(yulia_csv)
    yulia_df = yulia_df.dropna(subset=["nama"]).drop_duplicates(subset=["nama"]).reset_index(drop=True)
    print(f"    {len(yulia_df)} produk Yulia dimuat.")

    print("3/3 Matching ke katalog Airin ...")
    matched = match_batch(yulia_df, airin_df, nama_col="nama")

    gap = matched[matched["status_airin"] == "BELUM_TERSEDIA"].copy()
    gap = gap.sort_values(["kategori", "harga_grosir"], ascending=[True, True])
    matched.attrs["gap"] = gap
    matched.attrs["airin_df"] = airin_df
    return matched


def print_report(matched: pd.DataFrame, top_per_kategori: int = 10) -> None:
    gap = matched.attrs["gap"]
    total = len(matched)
    n_sama = (matched["status_airin"] == "SAMA_PRODUK").sum()
    n_verifikasi = (matched["status_airin"] == "PERLU_VERIFIKASI").sum()
    n_gap = len(gap)

    print(f"\n{'=' * 90}\nRINGKASAN\n{'=' * 90}")
    print(f"Total produk Yulia dicek : {total}")
    print(f"  Sudah ada di Airin     : {n_sama} ({n_sama/total*100:.0f}%)")
    print(f"  Perlu verifikasi manual: {n_verifikasi} ({n_verifikasi/total*100:.0f}%)")
    print(f"  BELUM ada di Airin (gap): {n_gap} ({n_gap/total*100:.0f}%)")

    print(f"\n{'=' * 90}\nGAP PER KATEGORI (produk Yulia yg belum ada di Airin)\n{'=' * 90}")
    for kat, grup in gap.groupby("kategori"):
        print(f"\n--- {kat} ({len(grup)} produk) ---")
        for _, r in grup.head(top_per_kategori).iterrows():
            harga = f"Rp{int(r['harga_grosir']):,}".replace(",", ".") if pd.notna(r["harga_grosir"]) else "?"
            print(f"  {r['nama']} -- {harga}/{r.get('ukuran', '?')}")
        if len(grup) > top_per_kategori:
            print(f"  ... +{len(grup) - top_per_kategori} produk lainnya")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yulia-csv", default=DEFAULT_YULIA_CSV, help="Path CSV hasil yulia_frozenfood_scraper.py.")
    ap.add_argument("--airin", default=DEFAULT_AIRIN_FILE, help="Path file master Airin (.xls).")
    ap.add_argument("--csv-out", metavar="FILE", help="Simpan SEMUA hasil (matched, termasuk yg udah ada) ke CSV.")
    ap.add_argument("--gap-csv-out", metavar="FILE", help="Simpan CUMA daftar gap ke CSV.")
    ap.add_argument("--top", type=int, default=10, help="Berapa produk ditampilkan per kategori (default 10).")
    args = ap.parse_args()

    matched = run_gap_analysis(args.yulia_csv, args.airin)
    print_report(matched, top_per_kategori=args.top)

    if args.csv_out:
        matched.to_csv(args.csv_out, index=False)
        print(f"\nSemua hasil matching disimpan ke {args.csv_out}")
    if args.gap_csv_out:
        matched.attrs["gap"].to_csv(args.gap_csv_out, index=False)
        print(f"Daftar gap disimpan ke {args.gap_csv_out}")


if __name__ == "__main__":
    main()
