"""
Terapkan perubahan harga beli/jual massal ke Kasir Pintar, dari file rencana.

Rencananya dibuat dari keputusan owner di halaman perbandingan harga; script ini
TIDAK menebak apa pun -- hanya menerapkan apa yang sudah ada di rencana, dan
hanya untuk cabang yang cocok dengan sesi yang sedang dipakai.

Satu sesi browser dipakai ulang untuk semua produk. Aman diulang: produk yang
harganya sudah sesuai rencana dilewati, jadi kalau terputus di tengah tinggal
dijalankan lagi.

PENGAMAN -- pelajaran dari pengisian kategori dulu:
  * Halaman edit bisa menahan submit lewat modal peringatan (#fixHarga kalau
    harga jual di bawah beli, #notif_kode kalau kode barang berubah). Tombol
    lanjutnya milik halaman itu sendiri dan diklik di sini, seperti yang
    dilakukan orang lewat browser.
  * Klik tombol simpan TIDAK dihitung sebagai berhasil. Tiap produk dibaca
    ulang setelah disimpan; kalau harganya tidak berubah, dilaporkan GAGAL.
    Versi lama menghitung klik sebagai sukses dan melaporkan "berhasil" untuk
    perubahan yang sebenarnya ditolak form.

Pakai:
    RENCANA=hasil_analisa/rencana_harga_piranha.json \
    KP_STATE=kasirpintar_state_now.json \
    /usr/bin/python3 terapkan_harga.py 3      # uji 3 produk dulu
    ... tanpa angka untuk semua
"""
import json
import os
import re
import sys

BASE = "https://kasirpintar.co.id"
DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("KP_STATE") or os.path.join(DIR, "kasirpintar_state.json")
RENCANA = os.environ.get("RENCANA") or os.path.join(DIR, "hasil_analisa", "rencana_harga.json")
LOG = os.path.join(DIR, "hasil_analisa", "log_harga.txt")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # Playwright ada di python SISTEM; dgn virtualenv aktif ia tak terlihat.
        sys.exit(f"playwright tidak ada di {sys.executable}\n"
                 f"Jalankan pakai python sistem:\n"
                 f"  /usr/bin/python3 {os.path.basename(__file__)}")

    plan = json.load(open(RENCANA, encoding="utf-8"))
    for p in plan:
        # barcode numerik terbaca "8992696521834.0" waktu xls-nya diparse
        if re.fullmatch(r"\d+\.0", str(p["kode"])):
            p["kode"] = str(p["kode"])[:-2]
    batas = int(sys.argv[1]) if len(sys.argv) > 1 else len(plan)
    plan = plan[:batas]
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = open(LOG, "a", encoding="utf-8")

    def catat(s):
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()

    cabang = sorted({p.get("cabang", "?") for p in plan})
    catat(f"--- mulai: {len(plan)} produk, cabang {', '.join(cabang)} ---")
    ok = gagal = lewat = 0
    with sync_playwright() as pw:
        br = pw.firefox.launch(headless=True)
        ctx = br.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")
        page = ctx.new_page()
        for i, p in enumerate(plan, 1):
            try:
                page.goto(f"{BASE}/account/edit_barang_detail/{p['kode']}",
                          wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1400)
                if "/login" in page.url:
                    catat("SESI HABIS -- berhenti. Jalankan lagi dgn cookie baru.")
                    break
                info = page.evaluate("""(() => {
                    const f = document.querySelector('form[action*="/account/edit_barang/"]');
                    if (!f) return null;
                    const g = n => (f.querySelector(`[name="${n}"]`) || {}).value ?? null;
                    const a = x => parseFloat(String(x ?? "").replace(/[^0-9.]/g, "")) || 0;
                    return {id:(f.id||'').replace('form_edit',''), nama:g('nama_barang'),
                            beli:a(g('harga_beli')), jual:a(g('harga_jual'))};
                })()""")
                if not info:
                    catat(f"[{i}] {p['nama'][:30]}: form tidak ketemu"); gagal += 1; continue
                if info["beli"] == p["beli"] and info["jual"] == p["jual"]:
                    lewat += 1; continue

                page.fill("form[action*='/account/edit_barang/'] [name=harga_beli]", str(p["beli"]))
                page.fill("form[action*='/account/edit_barang/'] [name=harga_jual]", str(p["jual"]))
                page.click(f"#submit_update{info['id']}", timeout=25_000)
                # modal peringatan punya tombol lanjutnya sendiri
                for tombol in ("#submit_harga", "#force_submit_code"):
                    try:
                        page.wait_for_selector(tombol, state="visible", timeout=1500)
                        page.click(tombol, timeout=5000)
                        break
                    except Exception:
                        pass
                page.wait_for_timeout(2200)

                # buktikan tersimpan, jangan percaya kliknya
                page.goto(f"{BASE}/account/edit_barang_detail/{p['kode']}",
                          wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1200)
                kini = page.evaluate("""(() => {
                    const f = document.querySelector('form[action*="/account/edit_barang/"]');
                    if (!f) return null;
                    const a = x => parseFloat(String(x ?? "").replace(/[^0-9.]/g, "")) || 0;
                    const g = n => (f.querySelector(`[name="${n}"]`) || {}).value;
                    return {beli:a(g('harga_beli')), jual:a(g('harga_jual'))};
                })()""")
                if kini and kini["beli"] == p["beli"] and kini["jual"] == p["jual"]:
                    catat(f"[{i}] {p['nama'][:30]}: {p['beli_lama']:,} / {p['jual_lama']:,}"
                          f" -> {p['beli']:,} / {p['jual']:,}")
                    ok += 1
                else:
                    catat(f"[{i}] {p['nama'][:30]}: TIDAK tersimpan "
                          f"(masih {kini['beli']:,} / {kini['jual']:,})" if kini else
                          f"[{i}] {p['nama'][:30]}: TIDAK tersimpan")
                    gagal += 1
            except Exception as e:
                catat(f"[{i}] {p['nama'][:30]}: {str(e).splitlines()[0][:70]}")
                gagal += 1
        try:
            ctx.storage_state(path=STATE)
            os.chmod(STATE, 0o600)
        except Exception:
            pass
        br.close()
    catat(f"SELESAI: berhasil={ok} gagal={gagal} sudah-sesuai={lewat} dari {len(plan)}")


if __name__ == "__main__":
    main()
