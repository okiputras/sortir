"""
Orkestrasi: discovery -> matching -> scoring -> ranking -> output.
CLI entry point utama buat riset produk baru.

Jalankan:
    python3 -m product_intelligence.pipeline
    python3 -m product_intelligence.pipeline --kategori madu kurma
    python3 -m product_intelligence.pipeline --airin DATA_BARANG_piranha.xls --csv hasil.csv
"""
import argparse

import pandas as pd

from product_intelligence.discovery import KATEGORI_QUERIES, run_discovery
from product_intelligence.matching import load_airin_catalog, match_batch
from product_intelligence.scoring import (
    build_alasan, extract_brand, opportunity_score, parse_harga, priority_label, retail_fit,
)

DEFAULT_AIRIN_FILE = "DATA_BARANG_sulfat_terbaru.xls"


def run_pipeline(kategori_list=None, n_per_query: int = 12, airin_file: str = DEFAULT_AIRIN_FILE) -> pd.DataFrame:
    print(f"1/4 Baca katalog Airin dari {airin_file} ...")
    airin_df = load_airin_catalog(airin_file)
    print(f"    {len(airin_df)} produk Airin dimuat.")

    print("2/4 Discovery: cari produk di Tokopedia per kategori ...")
    tokped_df = run_discovery(kategori_list, n_per_query=n_per_query)
    tokped_df = tokped_df.dropna(subset=["nama"]).drop_duplicates(subset=["nama"]).reset_index(drop=True)
    print(f"    {len(tokped_df)} produk unik ditemukan.")

    print("3/4 Matching ke katalog Airin ...")
    matched = match_batch(tokped_df, airin_df, nama_col="nama")

    print("4/4 Scoring & filter Retail Fit ...")
    matched["harga_int"] = matched["harga"].map(parse_harga)
    matched["lolos_retail_fit"] = matched.apply(lambda r: retail_fit(r["nama"], r["harga_int"]), axis=1)

    kandidat = matched[
        (matched["status_airin"] == "BELUM_TERSEDIA") & (matched["lolos_retail_fit"])
    ].copy()

    skor_rows = []
    for _, row in kandidat.iterrows():
        sub = opportunity_score(row.to_dict(), airin_df, row["kategori"])
        skor_rows.append(sub)
    skor_df = pd.DataFrame(skor_rows)
    kandidat = pd.concat([kandidat.reset_index(drop=True), skor_df.reset_index(drop=True)], axis=1)

    kandidat["brand"] = kandidat["nama"].map(extract_brand)
    kandidat["prioritas"] = kandidat["total"].map(priority_label)
    kandidat["alasan"] = [
        build_alasan(row.to_dict(), row.to_dict(), row["kategori"]) for _, row in kandidat.iterrows()
    ]

    # satu brand+kategori yg mirip -> ambil skor tertinggi doang, biar gak dobel varian
    kandidat = kandidat.sort_values("total", ascending=False)
    kandidat = kandidat.drop_duplicates(subset=["kategori", "toko"], keep="first")

    matched.attrs["kandidat"] = kandidat
    matched.attrs["airin_df"] = airin_df
    return matched


def print_report(matched: pd.DataFrame, top_n: int = 20) -> None:
    kandidat = matched.attrs["kandidat"]
    kandidat_top = kandidat.head(top_n)

    print(f"\n{'=' * 100}\nHASIL: {len(kandidat)} kandidat produk (setelah filter Retail Fit & dedup), top {top_n}\n{'=' * 100}")
    cols = ["nama", "kategori", "harga", "terjual", "rating", "total", "prioritas"]
    for i, (_, r) in enumerate(kandidat_top.iterrows(), 1):
        print(f"\n{i}. [{r['prioritas']}] {r['nama']}")
        print(f"   Kategori: {r['kategori']} | Harga: {r['harga']} | Terjual: {r['terjual']} | Rating: {r['rating']} | Score: {r['total']}")
        print(f"   Toko: {r['toko']} ({r['lokasi']})")
        print(f"   Alasan: {r['alasan']}")

    print(f"\n{'=' * 100}\nINSIGHT\n{'=' * 100}")
    if not kandidat.empty:
        print("\n1. Kategori dgn gap terbanyak:")
        print(kandidat["kategori"].value_counts().head(5).to_string())

        print("\n2. Rekomendasi coba duluan (top 5):")
        for i, (_, r) in enumerate(kandidat.head(5).iterrows(), 1):
            print(f"   {i}. {r['nama']} (score {r['total']})")

        n_prioritas_tinggi = (kandidat["prioritas"] == "🔥 PRIORITAS TINGGI").sum()
        print(f"\n3. {n_prioritas_tinggi} produk masuk PRIORITAS TINGGI.")
        print(f"   Saran: mulai dari 5-8 produk top-score buat batch test-order pertama,")
        print(f"   evaluasi repeat-purchase-nya sebelum nambah lagi.")
    else:
        print("Gak ada kandidat lolos filter -- coba kategori lain atau longgarkan Retail Fit.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kategori", nargs="+", choices=list(KATEGORI_QUERIES), help="Kategori yg dicek (default: semua).")
    ap.add_argument("--n", type=int, default=12, help="Maks produk per query Tokopedia (default 12).")
    ap.add_argument("--airin", default=DEFAULT_AIRIN_FILE, help="Path file master Airin (.xls).")
    ap.add_argument("--csv", metavar="FILE", help="Simpan SEMUA hasil (matched, bukan cuma kandidat) ke CSV.")
    ap.add_argument("--top", type=int, default=20, help="Berapa kandidat teratas yg ditampilkan (default 20).")
    args = ap.parse_args()

    matched = run_pipeline(args.kategori, n_per_query=args.n, airin_file=args.airin)
    print_report(matched, top_n=args.top)

    if args.csv:
        matched.to_csv(args.csv, index=False)
        print(f"\nSemua hasil (termasuk yg sudah ada/difilter) disimpan ke {args.csv}")


if __name__ == "__main__":
    main()
