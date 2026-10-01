"""Tarik seluruh master produk lewat endpoint JSON halaman Database.

Lebih enak dari export .xls: tidak lewat file, ada kategori dan updated_at,
dan bisa diambil bertahap. Endpoint-nya sumber DataTables milik halaman itu
sendiri (/account/getJsonDatabase) -- bukan API tersembunyi, cuma request
yang sama dengan yang dilakukan halaman waktu tabelnya digulir.

Pakai:
    KP_STATE=kasirpintar_state_x.json /usr/bin/python3 kasirpintar_json.py keluar.json
"""
import json
import os
import sys
from urllib.parse import urlencode

BASE = "https://kasirpintar.co.id"
HAL = f"{BASE}/account/database"
API = f"{BASE}/account/getJsonDatabase"
STATE = os.environ.get("KP_STATE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "kasirpintar_state.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
# urutan kolom harus sama dengan yang dikirim halaman; server memakainya
# untuk menentukan kolom mana yang boleh diurutkan dan dicari
KOL = ["", "link_gambar", "kode_barang", "nama_barang", "kategori", "harga_jual",
       "harga_beli", "stok", "diskon", "jenis_harga", "", "", "updated_at"]


def _muatan(start, length):
    d = {"draw": 1, "start": start, "length": length,
         "order[0][column]": 2, "order[0][dir]": "asc",
         "search[value]": "", "search[regex]": "false"}
    for i, n in enumerate(KOL):
        d[f"columns[{i}][data]"] = n
        d[f"columns[{i}][name]"] = n
        d[f"columns[{i}][searchable]"] = "true" if n in ("kode_barang", "nama_barang") else "false"
        d[f"columns[{i}][orderable]"] = "true" if n else "false"
        d[f"columns[{i}][search][value]"] = ""
        d[f"columns[{i}][search][regex]"] = "false"
    return urlencode(d)


def tarik(keluar=None, per=500):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(f"playwright tidak ada di {sys.executable}\n"
                 f"  /usr/bin/python3 {os.path.basename(__file__)}")
    semua, total = [], None
    with sync_playwright() as pw:
        br = pw.firefox.launch(headless=True)
        ctx = br.new_context(storage_state=STATE, user_agent=UA, locale="id-ID")
        pg = ctx.new_page()
        pg.goto(HAL, wait_until="domcontentloaded", timeout=60_000)
        pg.wait_for_timeout(2500)
        if "/login" in pg.url:
            sys.exit("Sesi habis -- ambil cookie baru lalu 'impor' lagi.")
        tok = pg.evaluate("document.querySelector('meta[name=csrf-token]')?.content")
        if not tok:
            sys.exit("CSRF token tidak ketemu.")
        head = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-CSRF-TOKEN": tok, "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE, "Referer": HAL}
        while total is None or len(semua) < total:
            r = ctx.request.post(API, data=_muatan(len(semua), per), headers=head)
            if r.status != 200:
                sys.exit(f"gagal (status {r.status}): {r.body()[:200]}")
            j = r.json()
            total = j.get("recordsTotal", 0)
            batch = j.get("data", [])
            if not batch:
                break          # server berhenti memberi -- jangan berputar selamanya
            semua.extend(batch)
            print(f"  {len(semua)}/{total}", flush=True)
        try:
            from kasirpintar_session import _simpan_sesi
            _simpan_sesi(ctx)
        except Exception:
            pass
        br.close()
    nama = keluar or "produk.json"
    with open(nama, "w", encoding="utf-8") as f:
        json.dump(semua, f, ensure_ascii=False)
    print(f"Tersimpan: {nama} ({len(semua)} produk)")
    return semua


if __name__ == "__main__":
    tarik(sys.argv[1] if len(sys.argv) > 1 else None)
