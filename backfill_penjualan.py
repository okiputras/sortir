"""
Script SEKALI JALAN untuk nge-sync ulang tab "PenjualanBulanan" di Google
Sheet dari file .xls Kasir Pintar mentah di data-sulfat/ dan data-piranha/.

Kenapa perlu: tab "PenjualanBulanan" cuma di-seed otomatis dari
sales_history_seed.json SEKALI, pas tab itu pertama kali dibuat (lihat
sales_history._ws()) -- kalau tab itu sudah ada dari sebelum PIRANHA
ditambahkan / sebelum data SULFAT di-dedupe ulang, perubahan itu TIDAK
pernah kepakai ke sheet yang live.

PENTING -- desain beda dari versi pertama: versi awal manggil
sales_history.replace_month() per (cabang,bulan,periode) -- itu artinya
clear() + tulis ulang SELURUH sheet 42x berturut-turut (7 bulan x 3
periode x 2 cabang), dan kalau koneksi putus PAS DI TENGAH salah satu
panggilan (antara clear() dan append_rows() selesai), seluruh sheet
ketinggalan KOSONG -- itu beneran kejadian pas dites.

Versi ini: agregasi SEMUA (cabang, bulan, periode) dulu di memori (murah,
lokal), baru clear() SEKALI, lalu tulis dalam beberapa batch kecil biar
kalau satu batch gagal krn network, tinggal retry batch itu -- bukan
resiko ngosongin seluruh sheet lagi.

Syarat sebelum jalankan (sama seperti setup_gsheet.py):
    - service_account.json / .streamlit/secrets.toml / env var GCP_SERVICE_ACCOUNT
      sudah ada, DAN spreadsheet_id.txt / env var SPREADSHEET_ID sudah diisi.
    - Folder data-sulfat/ dan data-piranha/ berisi file .xls Kasir Pintar
      (sheet "TransaksiBarang").

Jalankan:
    python3 backfill_penjualan.py            # proses SULFAT + PIRANHA
    python3 backfill_penjualan.py --dry-run  # cuma tampilkan ringkasan, tidak menulis apa-apa
"""
import argparse
import glob
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sales_upload import parse_transaksi
import sales_history as SH

FOLDERS = {
    "SULFAT": "data-sulfat",
    "PIRANHA": "data-piranha",
}
JAKARTA = ZoneInfo("Asia/Jakarta")
BATCH_SIZE = 3000  # baris per append_rows call
MAX_RETRY = 5


def build_agg(folder: str) -> dict:
    """Replikasi PERSIS logic agregasi di views/update_harga.py (bagian
    Upload Data Penjualan): dedupe baris identik (Timestamp+Nama+Jumlah+Total)
    antar file dalam folder yang sama, lalu grup per bulan & pecah Pagi/Siang."""
    files = sorted(glob.glob(f"{folder}/*.xls"))
    if not files:
        raise SystemExit(f"Tidak ada file .xls di {folder}/ -- cek lagi foldernya.")

    agg = {}
    seen_baris = set()
    for fp in files:
        with open(fp, "rb") as f:
            df = parse_transaksi(f.read())

        kunci = list(zip(df["Timestamp"], df["Nama"], df["Jumlah"], df["Total"]))
        baru_mask = [k not in seen_baris for k in kunci]
        df = df[baru_mask]
        seen_baris.update(k for k, is_baru in zip(kunci, baru_mask) if is_baru)

        for bulan, grp in df.groupby(df["Timestamp"].dt.strftime("%Y-%m")):
            slot = agg.setdefault(bulan, {"tanggal": set(), "Total": {}, "Pagi": {}, "Siang": {}})
            slot["tanggal"].update(grp["Timestamp"].dt.date)
            potongan = {
                "Total": grp,
                "Pagi": grp[grp["Timestamp"].dt.hour < 12],
                "Siang": grp[grp["Timestamp"].dt.hour >= 12],
            }
            for periode, bagian in potongan.items():
                for nama, qty in bagian.groupby("Nama")["Jumlah"].sum().items():
                    slot[periode][nama] = slot[periode].get(nama, 0) + qty
    return agg


def _retry(fn, desc):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == MAX_RETRY:
                raise
            wait = 2 ** attempt
            print(f"  [{desc}] gagal (percobaan {attempt}/{MAX_RETRY}): {e} -- retry dalam {wait}s")
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Cuma tampilkan ringkasan, tidak menulis ke sheet.")
    args = ap.parse_args()

    ts = datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S")
    all_rows = []
    for cabang, folder in FOLDERS.items():
        print(f"\n=== {cabang} ({folder}/) ===")
        agg = build_agg(folder)
        for bulan in sorted(agg):
            hari = len(agg[bulan]["tanggal"])
            n_produk = len(agg[bulan]["Total"])
            print(f"  {bulan}: {hari} hari, {n_produk} produk")
            for periode in ("Total", "Pagi", "Siang"):
                for nama, qty in agg[bulan][periode].items():
                    all_rows.append({
                        "Cabang": cabang, "Bulan": bulan, "Periode": periode,
                        "Produk": nama, "Qty": qty, "Hari": hari, "Timestamp": ts,
                    })

    print(f"\nTotal baris siap ditulis: {len(all_rows)}")

    if args.dry_run:
        print("[dry-run] Tidak ada yang ditulis ke sheet.")
        return

    ws = _retry(SH._ws, "buka sheet")

    print("Menghapus isi sheet lama...")
    _retry(ws.clear, "clear")
    _retry(lambda: ws.update([SH.HEADER], "A1"), "tulis header")

    n_batch = (len(all_rows) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(all_rows), BATCH_SIZE):
        batch = all_rows[i:i + BATCH_SIZE]
        idx = i // BATCH_SIZE + 1
        rows_2d = [[r.get(c, "") for c in SH.HEADER] for r in batch]
        _retry(lambda: ws.append_rows(rows_2d, value_input_option="USER_ENTERED"),
               f"batch {idx}/{n_batch}")
        print(f"  batch {idx}/{n_batch} tersimpan ({len(batch)} baris)")

    print(f"\nSelesai -- {len(all_rows)} baris tersimpan di PenjualanBulanan.")


if __name__ == "__main__":
    main()
