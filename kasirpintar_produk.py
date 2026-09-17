"""
Tambah / ubah / hapus produk di Kasir Pintar lewat sesi yang sudah login.

Sesinya diambil dari kasirpintar_state.json -- lihat kasirpintar_session.py
soal cara mengisinya (login manual di browser sendiri, salin cookie).

PENGAMAN: semua perintah di sini MENULIS ke sistem kasir yang dipakai sehari-hari,
jadi defaultnya cuma SIMULASI. Tidak ada yang benar-benar tersimpan sampai kamu
menambahkan --yakin. Untuk `ubah`, nilai lama vs baru ditampilkan dulu supaya
kelihatan persis apa yang berubah.

Alur yang dipakai (hasil penelusuran halamannya sendiri, Sep 2026):
  tambah : buka /account/product/add           -> klik #saveDefault
  ubah   : buka /account/edit_barang_detail/<kode> -> klik #submit_update<id>
  hapus  : GET  /account/hapus_barang_by_kode/<kode>

Dua jebakan yang bikin `tambah` gagal diam-diam kalau tidak ditangani:
  1. field product_type DISABLED sampai tombol Simpan diklik -- jadi form
     harus di-KLIK tombolnya, bukan dipanggil form.submit() langsung.
  2. Auto SKU tidak terisi sendiri kalau form diisi secara program; kode
     barang wajib diisi manual, kalau tidak ditolak "Kode Barang Kosong!".

Pakai:
  python3 kasirpintar_produk.py tambah "Nama Barang" KODE --beli 1000 --jual 1500 [--yakin]
  python3 kasirpintar_produk.py ubah KODE --jual 2000 [--beli 1500] [--nama "X"] [--yakin]
  python3 kasirpintar_produk.py hapus KODE [--yakin]
  python3 kasirpintar_produk.py lihat KODE
"""
import argparse
import os
import sys

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kasirpintar_state.json")
BASE = "https://kasirpintar.co.id"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
# field form edit -> nama argumen di CLI
FIELD = {"nama": "nama_barang", "beli": "harga_beli", "jual": "harga_jual",
         "kategori": "kategori", "rak": "letak_rak", "diskon": "diskon",
         "stok_min": "stok_minim", "keterangan": "keterangan"}


def _buka(p):
    if not os.path.exists(STATE):
        sys.exit("Belum ada sesi. Jalankan dulu: python3 kasirpintar_session.py impor")
    br = p.firefox.launch(headless=True)
    return br, br.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")


def _pw():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright belum terpasang: pip3 install --user playwright")
    return sync_playwright


def _simpan_sesi(ctx):
    try:
        ctx.storage_state(path=STATE)
        os.chmod(STATE, 0o600)
    except Exception:
        pass


def lihat(kode, _ctx=None):
    """Baca data produk sekarang. Balikin dict, atau None kalau tidak ada."""
    def _baca(page):
        page.goto(f"{BASE}/account/edit_barang_detail/{kode}", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)
        if "/login" in page.url:
            sys.exit("Sesi habis -- perbarui cookie lewat kasirpintar_session.py impor")
        return page.evaluate("""(() => {
            const f = document.querySelector('form[action*="/account/edit_barang/"]');
            if (!f) return null;
            const g = n => (f.querySelector(`[name="${n}"]`) || {}).value ?? null;
            return {id_barang:(f.id||'').replace('form_edit','')||null, kode:g('kode_barang'), nama:g('nama_barang'),
                    kategori:g('kategori'), beli:g('harga_beli'), jual:g('harga_jual'),
                    stok:g('stok'), stok_min:g('stok_minim'), rak:g('letak_rak'),
                    diskon:g('diskon'), keterangan:g('keterangan'), show_toko:g('show_toko')};
        })()""")
    if _ctx is not None:
        return _baca(_ctx.new_page())
    with _pw()() as p:
        br, ctx = _buka(p)
        d = _baca(ctx.new_page())
        _simpan_sesi(ctx)
        br.close()
    return d


def _tampil(d, judul="Data produk"):
    if not d:
        print("  (produk tidak ditemukan)")
        return
    print(f"  {judul}:")
    for k in ("kode", "nama", "kategori", "beli", "jual", "stok", "rak"):
        if d.get(k) not in (None, ""):
            print(f"    {k:<10}: {d[k]}")


def tambah(nama, kode, beli=0, jual=0, stok=0, satuan="pcs", kategori=None,
           sembunyikan=True, yakin=False):
    print(f"TAMBAH produk\n  nama : {nama}\n  kode : {kode}\n  beli : {beli}\n  jual : {jual}\n"
          f"  stok : {stok}\n  toko : {'disembunyikan' if sembunyikan else 'ditampilkan'}")
    if not yakin:
        print("\n[SIMULASI] tidak ada yang disimpan. Tambahkan --yakin untuk benar-benar membuat.")
        return
    with _pw()() as p:
        br, ctx = _buka(p)
        page = ctx.new_page()
        page.goto(f"{BASE}/account/product/add", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)
        if "/login" in page.url:
            sys.exit("Sesi habis -- perbarui cookie dulu.")
        page.fill("[name=name]", nama)
        page.fill("[name=sku]", kode)          # wajib: auto-SKU tidak jalan kalau diisi program
        page.fill("[name=purchase_price]", str(beli))
        page.fill("[name=sell_price]", str(jual))
        page.fill("[name=quantity]", str(stok))
        page.fill("[name=unit]", satuan)
        if kategori:
            try:
                page.select_option("[name=category]", label=kategori)
            except Exception:
                print(f"  (kategori '{kategori}' tidak ada di daftar, dilewati)")
        try:
            page.select_option("[name=show_store]", "1" if sembunyikan else "0")
        except Exception:
            pass
        page.click("#saveDefault", timeout=20_000)   # HARUS diklik, bukan form.submit()
        page.wait_for_timeout(9000)
        ok = "/account/database" in page.url
        _simpan_sesi(ctx)
        br.close()
    print("\nBERHASIL dibuat." if ok else "\nGAGAL -- form ditolak (cek nama/kode, mungkin kode sudah dipakai).")


def ubah(kode, yakin=False, **baru):
    baru = {k: v for k, v in baru.items() if v is not None}
    if not baru:
        sys.exit("Tidak ada yang diubah. Contoh: --jual 2000")
    with _pw()() as p:
        br, ctx = _buka(p)
        page = ctx.new_page()
        page.goto(f"{BASE}/account/edit_barang_detail/{kode}", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)
        if "/login" in page.url:
            sys.exit("Sesi habis -- perbarui cookie dulu.")
        lama = page.evaluate("""(() => {
            const f = document.querySelector('form[action*="/account/edit_barang/"]');
            if (!f) return null;
            const g = n => (f.querySelector(`[name="${n}"]`) || {}).value ?? null;
            const idp = (f.id || '').replace('form_edit', '') || null;
            return {id_barang:idp, nama:g('nama_barang'), beli:g('harga_beli'),
                    jual:g('harga_jual'), kategori:g('kategori'), rak:g('letak_rak'),
                    diskon:g('diskon'), stok_min:g('stok_minim'), keterangan:g('keterangan')};
        })()""")
        if not lama:
            br.close()
            sys.exit(f"Produk kode '{kode}' tidak ditemukan.")
        print(f"UBAH produk kode '{kode}' ({lama['nama']})")
        for k, v in baru.items():
            print(f"  {k:<10}: {lama.get(k)}  ->  {v}")
        if not yakin:
            br.close()
            print("\n[SIMULASI] tidak ada yang disimpan. Tambahkan --yakin untuk menerapkan.")
            return
        for k, v in baru.items():
            page.fill(f"[name={FIELD[k]}]", str(v))
        sel = (f"#submit_update{lama['id_barang']}" if lama.get("id_barang")
               else "button[id^=submit_update]")
        page.click(sel, timeout=20_000)
        page.wait_for_timeout(9000)
        ok = "/login" not in page.url
        _simpan_sesi(ctx)
        br.close()
    print("\nTersimpan." if ok else "\nGAGAL menyimpan.")


def hapus(kode, yakin=False):
    d = lihat(kode)
    if not d:
        sys.exit(f"Produk kode '{kode}' tidak ditemukan.")
    print(f"HAPUS produk kode '{kode}'")
    _tampil(d, "yang akan dihapus")
    if not yakin:
        print("\n[SIMULASI] belum dihapus. Tambahkan --yakin untuk benar-benar menghapus.")
        return
    with _pw()() as p:
        br, ctx = _buka(p)
        page = ctx.new_page()
        page.goto(f"{BASE}/account/hapus_barang_by_kode/{kode}", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        # jangan percaya teks halaman (pesannya dimunculkan JS & tidak selalu
        # kebaca) -- buka lagi halaman editnya, kalau formnya hilang berarti
        # produknya memang sudah tidak ada.
        masih = lihat(kode, _ctx=ctx) is not None
        _simpan_sesi(ctx)
        br.close()
    print("\nGAGAL -- produk masih ada." if masih else "\nTerhapus (sudah diverifikasi).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    t = sub.add_parser("tambah", help="tambah produk baru")
    t.add_argument("nama"); t.add_argument("kode")
    t.add_argument("--beli", default=0); t.add_argument("--jual", default=0)
    t.add_argument("--stok", default=0); t.add_argument("--satuan", default="pcs")
    t.add_argument("--kategori"); t.add_argument("--tampilkan", action="store_true",
                                                 help="tampilkan di toko (default disembunyikan)")
    t.add_argument("--yakin", action="store_true")

    u = sub.add_parser("ubah", help="ubah produk yang sudah ada")
    u.add_argument("kode")
    for k in FIELD:
        u.add_argument(f"--{k}")
    u.add_argument("--yakin", action="store_true")

    h = sub.add_parser("hapus", help="hapus produk"); h.add_argument("kode")
    h.add_argument("--yakin", action="store_true")

    l = sub.add_parser("lihat", help="lihat data produk"); l.add_argument("kode")

    a = ap.parse_args()
    if a.cmd == "tambah":
        tambah(a.nama, a.kode, a.beli, a.jual, a.stok, a.satuan, a.kategori,
               sembunyikan=not a.tampilkan, yakin=a.yakin)
    elif a.cmd == "ubah":
        ubah(a.kode, yakin=a.yakin, **{k: getattr(a, k) for k in FIELD})
    elif a.cmd == "hapus":
        hapus(a.kode, yakin=a.yakin)
    elif a.cmd == "lihat":
        _tampil(lihat(a.kode), f"Produk '{a.kode}'")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
