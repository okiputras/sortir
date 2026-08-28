"""
Script SEKALI JALAN untuk scrape hasil pencarian Tokopedia (nama produk,
harga, rating, jumlah terjual, nama+lokasi toko) -- dipakai buat riset
produk yang laris di marketplace tapi belum ada di katalog sendiri
(cocokkan manual hasilnya ke tab Produk / katalog Olshopin).

Kenapa Tokopedia, bukan Shopee: Shopee NUTUP halaman pencarian di balik
login wall, bahkan buat browser biasa (headless ataupun bukan) -- sudah
dicoba, langsung dilempar ke "Masuk Diperlukan". Tokopedia sejauh ini
masih bisa diakses tanpa login sama sekali.

Kenapa lewat browser beneran (headless Chrome + DevTools Protocol),
bukan requests/urllib biasa: hasil pencarian Tokopedia di-render lewat
JavaScript sisi client -- HTML mentah dari server gak punya data produk
apapun, cuma shell kosong.

Cara kerja: buka Chrome headless, navigate ke URL pencarian Tokopedia,
tunggu JS-nya render, lalu ambil innerText semua <a> yang ngarah ke
tokopedia.com dan cukup panjang (>=3 baris) -- itu pola kartu produk di
halaman hasil pencarian (badge diskon / nama / harga / rating / terjual
/ nama toko, masing-masing baris terpisah).

Syarat:
    - Google Chrome terinstall (default path macOS, ubah CHROME_PATH
      kalau OS/lokasi beda).
    - pip install websocket-client requests   (bukan dependency app,
      sengaja TIDAK ditambah ke requirements.txt biar gak numpang ke
      deploy Railway -- ini murni tool riset lokal).

Jalankan:
    python3 tokopedia_search.py "madu grosir" "kurma date crown"
    python3 tokopedia_search.py "knorr bumbu grosir" --n 15
    python3 tokopedia_search.py "madu grosir" --json hasil_madu.json
"""
import argparse
import json
import re
import subprocess
import time

import requests
import websocket

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9333
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_EXTRACT_JS = """
(function(){
  var links = Array.from(document.querySelectorAll('a[href*="tokopedia.com"]'));
  var seen = new Set();
  var out = [];
  links.forEach(function(a){
    var text = a.innerText.trim();
    if (!text || seen.has(text)) return;
    if (text.split('\\n').length < 3) return;
    seen.add(text);
    var img = a.querySelector('img');
    var gambar = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
    out.push({text: text, gambar: gambar});
  });
  return JSON.stringify(out.slice(0, %d));
})()
"""


def _launch_chrome():
    proc = subprocess.Popen(
        [
            CHROME_PATH, "--headless=new", "--disable-gpu",
            f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*",
            "--window-size=1400,1200", f"--user-agent={UA}", "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        try:
            requests.get(f"http://localhost:{CDP_PORT}/json/version", timeout=1)
            return proc
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    raise RuntimeError("Chrome CDP tidak nyala dalam 10 detik.")


class _CdpTab:
    def __init__(self):
        tab = requests.put(f"http://localhost:{CDP_PORT}/json/new?about:blank").json()
        self.ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=20)
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        return self._id

    def recv_until(self, target_id, timeout=20):
        self.ws.settimeout(2)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == target_id:
                    return msg
            except Exception:
                continue
        return None

    def close(self):
        self.ws.close()


_SCROLL_JS = "window.scrollTo(0, document.body.scrollHeight); document.body.scrollHeight"


# Kode `ob` (order-by) dropdown "Urutkan" di halaman pencarian Tokopedia --
# ditemukan dgn cara klik dropdown-nya beneran di browser & baca URL hasilnya
# (gak didokumentasikan resmi di manapun). ob=5 = "Ulasan" (urut byk ulasan/
# review dulu) -- dipakai default krn produk yg BANYAK diulas biasanya juga
# yg beneran laku & kepercayaan pembeli tinggi (high-value), bukan sekadar
# nyangkut di kata kunci pencarian kayak default "Paling Sesuai".
OB_ULASAN = 5


def search_tokopedia(
    query: str, n: int = 20, wait_seconds: float = 5.5, retries: int = 2, urutkan_ulasan: bool = True,
) -> list[dict]:
    """Cari `query` di Tokopedia, kembalikan sampai `n` produk sbg list dict:
    {nama, harga, harga_asli, diskon_persen, rating, terjual, toko, lokasi, gambar, raw}.

    Diamati: query yg PERSIS sama kadang balik "produk nggak ditemukan" kalau
    ditembak berturut-turut cepat (kemungkinan rate-limit halus di sisi
    Tokopedia, bukan blokir keras/CAPTCHA -- gak ada pola pasti). Makanya
    ada retry otomatis dgn jeda sblm nyerah beneran.

    Grid produk Tokopedia di-lazy-load pas discroll (virtualized) -- tanpa
    scroll, cuma kartu yg muat di viewport awal yg beneran ke-render ke DOM
    (~15 produk), sisanya gak ada di HTML sama sekali walau `n` diminta lebih
    besar. Makanya sblm ekstraksi kita scroll ke bawah berkali-kali (jumlah
    scroll disesuaikan sama `n`) biar makin banyak kartu ke-trigger render.

    `urutkan_ulasan=True` (default) nambah `&ob=5` ke URL pencarian biar hasil
    diurutkan by jumlah ulasan -- lihat OB_ULASAN di atas."""
    n_scroll = min(10, max(1, (n - 1) // 10))
    for attempt in range(retries + 1):
        tab = _CdpTab()
        try:
            tab.send("Page.enable")
            tab.ws.recv()
            url = f"https://www.tokopedia.com/search?st=product&q={requests.utils.quote(query)}"
            if urutkan_ulasan:
                url += f"&ob={OB_ULASAN}"
            nav_id = tab.send("Page.navigate", {"url": url})
            tab.recv_until(nav_id)
            time.sleep(wait_seconds)

            for _ in range(n_scroll):
                scroll_id = tab.send("Runtime.evaluate", {"expression": _SCROLL_JS})
                tab.recv_until(scroll_id)
                time.sleep(1.3)

            ev_id = tab.send("Runtime.evaluate", {"expression": _EXTRACT_JS % n, "returnByValue": True})
            r = tab.recv_until(ev_id)
            raw_cards = json.loads(r["result"]["result"]["value"]) if r else []
        finally:
            tab.close()

        if raw_cards or attempt == retries:
            return [_parse_card(c) for c in raw_cards]
        time.sleep(3 + attempt * 2)  # jeda makin lama tiap retry
    return []


_PROMO_PREFIXES = ("Hemat ", "Bisa COD", "+", "PreOrder")


def _parse_card(card: dict) -> dict:
    """Kartu produk Tokopedia render sbg baris innerText berurutan, tapi
    JUMLAH barisnya beda-beda (gak semua produk punya badge diskon/promo/
    lokasi toko) -- jadi tiap baris diklasifikasi by POLA-nya (bukan by
    posisi index tetap), lalu apapun yg gak kena pola apapun dianggap
    nama produk (baris pertama nya) atau toko+lokasi (baris SISA di akhir,
    urutan asli: toko dulu baru lokasi, kalau cuma sisa 1 baris berarti
    toko tanpa lokasi -- kejadian utk toko resmi brand mis. "Unilever
    Food Solutions"). `gambar` diambil terpisah di JS (src <img> di dalam
    kartu), bukan dari innerText -- gak ikut proses klasifikasi baris."""
    text = card["text"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    out = {
        "nama": None, "harga": None, "harga_asli": None, "diskon_persen": None,
        "rating": None, "terjual": None, "toko": None, "lokasi": None,
        "gambar": card.get("gambar") or None, "raw": text,
    }
    harga_lines = []
    sisa = []
    for line in lines:
        if re.fullmatch(r"\d{1,3}%", line):
            out["diskon_persen"] = int(line.rstrip("%"))
        elif line.startswith("Rp"):
            harga_lines.append(line)
        elif re.fullmatch(r"\d\.\d", line):
            out["rating"] = float(line)
        elif "terjual" in line.lower():
            out["terjual"] = line.replace(" terjual", "").strip()
        elif line.startswith(_PROMO_PREFIXES):
            continue  # baris promo ("Hemat s.d 8%...", "Bisa COD", dst) -- dibuang
        else:
            sisa.append(line)

    if harga_lines:
        out["harga"] = harga_lines[0]
        if len(harga_lines) > 1:
            out["harga_asli"] = harga_lines[1]

    # baris pertama yg tersisa = nama produk; sisanya (kalau ada) = toko [+ lokasi]
    if sisa:
        out["nama"] = sisa[0]
        ekor = sisa[1:]
        if len(ekor) >= 2:
            out["toko"], out["lokasi"] = ekor[0], ekor[1]
        elif len(ekor) == 1:
            out["toko"] = ekor[0]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queries", nargs="+", help="Kata kunci pencarian, satu atau lebih (dikutip kalau ada spasi).")
    ap.add_argument("--n", type=int, default=15, help="Maks produk per query (default 15).")
    ap.add_argument("--json", metavar="FILE", help="Simpan hasil mentah ke file JSON, selain print ke layar.")
    args = ap.parse_args()

    chrome_proc = _launch_chrome()
    all_results = {}
    try:
        for i_q, q in enumerate(args.queries):
            if i_q > 0:
                time.sleep(2)  # jeda antar query, biar gak keliatan kayak spam ke Tokopedia
            print(f"\n{'=' * 20} {q} {'=' * 20}")
            hasil = search_tokopedia(q, n=args.n)
            all_results[q] = hasil
            if not hasil:
                print("  (kosong -- coba jalankan ulang query ini sendirian kalau perlu)")
            for i, p in enumerate(hasil, 1):
                print(f"{i:2d}. {p['nama']}")
                print(f"    {p['harga']}" + (f" (coret {p['harga_asli']})" if p['harga_asli'] else ""))
                print(f"    rating {p['rating']} | {p['terjual']} terjual | {p['toko']} ({p['lokasi']})")
    finally:
        chrome_proc.terminate()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\nHasil mentah disimpan ke {args.json}")


if __name__ == "__main__":
    main()
