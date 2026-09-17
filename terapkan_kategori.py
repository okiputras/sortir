"""
Terapkan kategori massal ke produk Kasir Pintar, dari hasil_analisa/rencana_kategori.json.

Rencananya dibuat dari usulan otomatis + koreksi manual owner (file Numbers),
lihat riwayat percakapan. Script ini TIDAK menebak apa pun -- hanya menerapkan
apa yang sudah ada di rencana.

Satu sesi browser dipakai ulang untuk semua produk. Kalau browser dibuka-tutup
tiap produk, 257 produk butuh berjam-jam; dengan sesi yang sama sekitar 20 menit.

Aman diulang: produk yang kategorinya sudah sesuai rencana akan dilewati, jadi
kalau terputus di tengah tinggal jalankan lagi.

Pakai:
    python3 terapkan_kategori.py 3      # uji 3 produk pertama dulu
    python3 terapkan_kategori.py        # semua
"""
import json
import os
import sys

BASE = "https://kasirpintar.co.id"
DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(DIR, "kasirpintar_state.json")
RENCANA = os.environ.get("RENCANA") or os.path.join(DIR, "hasil_analisa", "rencana_kategori.json")
LOG = os.path.join(DIR, "hasil_analisa", "log_kategori.txt")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def main():
    from playwright.sync_api import sync_playwright

    import re
    plan = json.load(open(RENCANA, encoding="utf-8"))
    # Barcode yang tersimpan sbg ANGKA di Kasir Pintar terbaca "8992696521834.0"
    # waktu xls-nya diparse (xlrd balikin float). Kode aslinya tanpa ".0" --
    # kalau tidak dibuang, halaman editnya tidak ketemu & produknya terlewat.
    for _p in plan:
        if re.fullmatch(r"\d+\.0", str(_p["kode"])):
            _p["kode"] = str(_p["kode"])[:-2]
    batas = int(sys.argv[1]) if len(sys.argv) > 1 else len(plan)
    kat_baru = sorted({p["kategori"] for p in plan if p.get("baru")})
    plan = plan[:batas]
    log = open(LOG, "a", encoding="utf-8")

    def catat(s):
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()

    catat(f"--- mulai: {len(plan)} produk ---")
    with sync_playwright() as pw:
        br = pw.firefox.launch(headless=True)
        ctx = br.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")
        page = ctx.new_page()

        # 1. buat kategori baru yang belum ada
        page.goto(f"{BASE}/account/kategori", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        if "/login" in page.url:
            catat("Sesi habis. Perbarui cookie dulu (kasirpintar_session.py impor).")
            return
        tok = page.evaluate("document.querySelector('form[action*=tambah_kategori] [name=_token]')?.value")
        sudah = page.inner_text("body").lower()
        for k in kat_baru:
            if k.lower() in sudah:
                catat(f"kategori '{k}' sudah ada")
                continue
            r = ctx.request.post(f"{BASE}/account/tambah_kategori",
                                 form={"_token": tok, "mode": "add", "nama": k},
                                 headers={"Referer": f"{BASE}/account/kategori"})
            catat(f"buat kategori '{k}': status {r.status}")

        # 2. terapkan per produk
        ok = gagal = lewat = 0
        for i, p in enumerate(plan, 1):
            try:
                page.goto(f"{BASE}/account/edit_barang_detail/{p['kode']}",
                          wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1400)
                if "/login" in page.url:
                    catat("SESI HABIS -- berhenti. Jalankan lagi setelah cookie diperbarui.")
                    break
                info = page.evaluate("""(() => {
                    const f = document.querySelector('form[action*="/account/edit_barang/"]');
                    if (!f) return null;
                    const s = f.querySelector('[name=kategori]');
                    return {id:(f.id||'').replace('form_edit',''), kat:s?s.value:null,
                            opsi:s?[...s.options].map(o=>o.value):[]};
                })()""")
                if not info:
                    catat(f"[{i}] {p['nama'][:30]}: form tidak ketemu"); gagal += 1; continue
                if info["kat"] == p["kategori"]:
                    lewat += 1; continue
                if p["kategori"] not in info["opsi"]:
                    catat(f"[{i}] {p['nama'][:30]}: opsi '{p['kategori']}' tidak ada di dropdown")
                    gagal += 1; continue
                page.select_option("form[action*='/account/edit_barang/'] [name=kategori]", p["kategori"])
                page.click(f"#submit_update{info['id']}", timeout=25_000)
                page.wait_for_timeout(2200)
                ok += 1
                if i % 25 == 0:
                    catat(f"  ... {i}/{len(plan)} (ok={ok} gagal={gagal} lewat={lewat})")
            except Exception as e:
                catat(f"[{i}] {p['nama'][:30]}: {str(e).splitlines()[0][:70]}")
                gagal += 1
        ctx.storage_state(path=STATE)
        os.chmod(STATE, 0o600)
        br.close()
    catat(f"SELESAI: berhasil={ok} gagal={gagal} sudah-sesuai={lewat} dari {len(plan)}")


if __name__ == "__main__":
    main()
