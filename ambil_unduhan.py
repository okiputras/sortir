"""
Pindahkan file laporan Kasir Pintar dari ~/Downloads ke folder cabangnya.

Kenapa manual-lalu-otomatis: file .xls bertingkat transaksi hanya bisa diunduh
lewat tombol yang dijaga captcha di /account/laporan. Captcha itu kontrol
anti-otomasi milik Kasir Pintar dan TIDAK ditembus di sini -- kamu yang
mengkliknya sekali di browser biasa, script ini mengurus sisanya: mengenali
cabangnya, memeriksa isinya, menaruhnya di folder yang benar.

Cabang dikenali dari ID toko di nama file, bukan dari tebakan:
    Laporan_1647357_01_09_2026_17_09_2026.xls  -> SULFAT
    Laporan_2577435_01_09_2026_17_09_2026.xls  -> PIRANHA

Isinya diperiksa dulu (harus punya sheet TransaksiBarang dan terbaca xlrd),
jadi file yang rusak atau salah jenis tidak ikut masuk dan mengotori folder
yang jadi sumber PenjualanBulanan.

Pakai:
    python3 ambil_unduhan.py                 # lihat apa yang akan dipindah
    python3 ambil_unduhan.py --pindah        # pindahkan
    python3 ambil_unduhan.py --pindah --backfill   # lalu sinkronkan PenjualanBulanan
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
UNDUHAN = os.path.expanduser("~/Downloads")
CABANG = {"1647357": ("SULFAT", "data-sulfat"),
          "2577435": ("PIRANHA", "data-piranha")}
POLA = re.compile(r"^Laporan_(\d+)_(\d{2}_\d{2}_\d{4})_(\d{2}_\d{2}_\d{4})", re.I)


def _periksa(path):
    """Balikin (jumlah_baris, None) kalau file laporan sah, atau (0, alasan)."""
    try:
        import xlrd
    except ImportError:
        return 0, "xlrd belum terpasang"
    try:
        wb = xlrd.open_workbook(path, ignore_workbook_corruption=True)
    except Exception as e:
        return 0, f"tidak terbaca ({str(e)[:40]})"
    if "TransaksiBarang" not in wb.sheet_names():
        return 0, f"tidak ada sheet TransaksiBarang (isinya {wb.sheet_names()})"
    sh = wb.sheet_by_name("TransaksiBarang")
    # baris terakhir tiap file adalah baris TOTAL berkode kosong -- bukan penjualan
    return max(0, sh.nrows - 2), None


def _rentang(nama):
    """(mulai, akhir) sebagai date, dari nama file. None kalau tidak cocok."""
    from datetime import date
    m = POLA.match(nama)
    if not m:
        return None
    def d(s):
        h, b, t = s.split("_")
        return date(int(t), int(b), int(h))
    return d(m.group(2)), d(m.group(3))


def _bentrok(folder, nama):
    """Nama file lain di folder yang rentang tanggalnya beririsan.

    Memeriksa nama file saja tidak cukup: Kasir Pintar membiarkan kita mengunduh
    rentang apa pun, jadi 09_08-15_08 bisa menabrak 01_08-10_08 yang sudah ada.
    Kalau keduanya masuk, penjualan hari yang beririsan terhitung DUA KALI di
    PenjualanBulanan -- dan itu tidak kelihatan sampai angkanya dipakai.
    """
    r = _rentang(nama)
    if not r:
        return []
    a, b = r
    out = []
    d = os.path.join(DIR, folder)
    for lain in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not lain.lower().endswith(".xls"):
            continue
        rl = _rentang(lain)
        if rl and a <= rl[1] and rl[0] <= b:
            out.append(lain)
    return out


def cari():
    if not os.path.isdir(UNDUHAN):
        sys.exit(f"Folder unduhan tidak ada: {UNDUHAN}")
    out = []
    for nama in os.listdir(UNDUHAN):
        m = POLA.match(nama)
        if not m or not nama.lower().endswith(".xls"):
            continue
        tid = m.group(1)
        if tid not in CABANG:
            out.append((nama, None, None, f"ID toko {tid} tidak dikenal"))
            continue
        cab, folder = CABANG[tid]
        # "(1)" dari unduhan ganda dibuang supaya nama seragam dgn yang lama
        bersih = re.sub(r"\s*\(\d+\)(?=\.xls$)", "", nama)
        tujuan = os.path.join(DIR, folder, bersih)
        n, salah = _periksa(os.path.join(UNDUHAN, nama))
        if salah:
            out.append((nama, cab, tujuan, salah))
        elif os.path.exists(tujuan):
            out.append((nama, cab, tujuan, f"sudah ada di {folder}/"))
        elif not n:
            out.append((nama, cab, tujuan, "kosong, tidak ada transaksi"))
        else:
            tabrak = _bentrok(folder, bersih)
            out.append((nama, cab, tujuan,
                        f"BERIRISAN dgn {tabrak[0]}" if tabrak else None))
        out[-1] = out[-1] + (n,)
    return sorted(out, key=lambda r: r[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pindah", action="store_true", help="benar-benar pindahkan")
    ap.add_argument("--salin", action="store_true", help="salin, jangan pindahkan")
    ap.add_argument("--backfill", action="store_true",
                    help="jalankan backfill_penjualan.py setelah memindah")
    a = ap.parse_args()

    ketemu = cari()
    if not ketemu:
        print(f"Tidak ada file Laporan_*.xls di {UNDUHAN}")
        return

    siap = []
    print(f"{'file':52} {'cabang':8} {'baris':>7}  status")
    for nama, cab, tujuan, salah, n in ketemu:
        print(f"{nama[:50]:52} {(cab or '-'):8} {n:>7,}  {salah or 'SIAP'}")
        if not salah:
            siap.append((nama, tujuan))

    if not siap:
        print("\nTidak ada yang perlu dipindah.")
        return
    if not (a.pindah or a.salin):
        print(f"\n[SIMULASI] {len(siap)} file siap. Tambahkan --pindah untuk menjalankan.")
        return

    for nama, tujuan in siap:
        os.makedirs(os.path.dirname(tujuan), exist_ok=True)
        (shutil.copy2 if a.salin else shutil.move)(os.path.join(UNDUHAN, nama), tujuan)
        print(f"  -> {os.path.relpath(tujuan, DIR)}")
    print(f"\n{len(siap)} file {'disalin' if a.salin else 'dipindah'}.")

    if a.backfill:
        cab = sorted({"SULFAT" if "sulfat" in t else "PIRANHA" for _, t in siap})
        for c in cab:
            print(f"\n--- backfill {c} ---")
            subprocess.run([sys.executable, os.path.join(DIR, "backfill_penjualan.py"),
                            "--cabang", c], check=False)


if __name__ == "__main__":
    main()
