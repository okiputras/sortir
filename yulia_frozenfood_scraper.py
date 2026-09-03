"""
Script SEKALI JALAN utk scrape SEMUA produk di yuliafrozenfood.com (supplier
frozen food) -- nama, ukuran/isi kemasan, daftar harga bertingkat (grosir),
gambar, per kategori. Dipakai buat riset: cocokkan katalog supplier ini ke
Produk Airin, cari produk frozen food yg dijual supplier tapi belum di-stock
Airin (peluang restock/sourcing baru).

Beda dgn tokopedia_search.py: situs ini HTML statis biasa (bukan render JS
sisi client), jadi cukup `requests` + BeautifulSoup -- gak perlu headless
Chrome/CDP.

Struktur situs (dicek manual 2026-08-28):
    - Kategori: https://yuliafrozenfood.com/?category_id=<ID>
    - Pagination per kategori: &page=0, &page=1, dst (page-item terakhir yg
      non-disabled = halaman terakhir; kalau gak ada produk di halaman itu,
      berarti sudah lewat batas).
    - Kartu produk: <div class="card product-card"> berisi nama
      (.card-title), ukuran/isi (.card-text), gambar (<img>), dan daftar
      harga bertingkat "Harga 1/2/3/.." (ul.price-list li) -- makin banyak
      beli makin murah/pcs, harga TERMURAH (harga tertinggi tier) dipakai
      sbg representasi grosir.

Syarat: pip install beautifulsoup4 requests (bukan dependency app, sama spt
tokopedia_search.py -- gak ditambah ke requirements.txt).

Jalankan:
    python3 yulia_frozenfood_scraper.py
    python3 yulia_frozenfood_scraper.py --kategori "Semua Bakso" "Semua Nugget"
    python3 yulia_frozenfood_scraper.py --csv hasil_yulia.csv
"""
import argparse
import html as html_module
import json
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://yuliafrozenfood.com/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_kategori_list() -> dict:
    """{"Semua Bakso": 9, "Semua Nugget": 8, ...} -- ditarik dari link
    kategori di homepage (?category_id=N). Beberapa category_id muncul 2x
    di HTML dgn label beda (mis. nav pill "Semua Bakso" + link lain
    "Bakso") -- disatukan per category_id, pilih yg berawalan "Semua" kalau
    ada biar gak ke-scrape dobel."""
    r = requests.get(BASE_URL, headers={"User-Agent": UA}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    by_id = {}
    for a in soup.find_all("a", href=re.compile(r"\?category_id=\d+")):
        m = re.search(r"category_id=(\d+)", a["href"])
        nama = html_module.unescape(a.get_text(strip=True))
        if not m or not nama:
            continue
        cid = int(m.group(1))
        if cid not in by_id or nama.startswith("Semua"):
            by_id[cid] = nama
    return {nama: cid for cid, nama in by_id.items()}


def _parse_harga_list(card) -> list:
    """Balikin list int harga per tier (Harga 1, Harga 2, dst) dari
    ul.price-list -- tier terakhir = harga termurah/grosir."""
    harga = []
    for li in card.select("ul.price-list li"):
        span = li.find("span")
        if not span:
            continue
        digits = re.sub(r"[^\d]", "", span.get_text())
        if digits:
            harga.append(int(digits))
    return harga


def _get_with_retry(url: str, retries: int = 6) -> requests.Response:
    """Situs ini nge-rate-limit ("Terlalu banyak request, coba lagi nanti",
    HTTP 429) berbasis JENDELA WAKTU KUMULATIF -- makin lama proses jalan
    (bukan cuma makin cepat request-nya), makin gampang ke-trigger, jadi
    retry harus nunggu CUKUP lama (bukan cuma beberapa detik) biar jendela
    limitnya reset. Diamati: retry pendek (5-20 detik) gak cukup & bikin
    kategori keliru kebaca "habis" padahal sebenernya masih diblokir."""
    r = None
    for attempt in range(retries):
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        if r.status_code == 429:
            time.sleep(15 + attempt * 15)
            continue
        return r
    return r


class RateLimited(Exception):
    pass


def _scrape_page(category_id: int, page: int) -> list:
    url = f"{BASE_URL}?category_id={category_id}&page={page}"
    r = _get_with_retry(url)
    if r.status_code == 429:
        # Masih diblokir stlh semua retry -- JANGAN dianggap "halaman
        # kosong = kategori habis", krn itu bakal bikin sisa produk hilang
        # diam-diam. Lempar error biar scrape_kategori tau bedanya.
        raise RateLimited(f"Masih 429 stlh semua retry: {url}")
    soup = BeautifulSoup(r.text, "html.parser")
    produk = []
    for card in soup.select("div.card.product-card"):
        title_el = card.select_one(".card-title")
        if not title_el:
            continue
        nama = title_el.get_text(strip=True)
        ukuran_el = card.select_one(".card-text")
        ukuran = ukuran_el.get_text(strip=True) if ukuran_el else None
        img_el = card.find("img")
        gambar = img_el["src"] if img_el and img_el.get("src") else None
        harga_list = _parse_harga_list(card)
        produk.append({
            "nama": nama,
            "ukuran": ukuran,
            "harga_satuan": harga_list[0] if harga_list else None,
            "harga_grosir": harga_list[-1] if harga_list else None,
            "gambar": gambar,
        })
    return produk


def scrape_kategori(nama_kategori: str, category_id: int, max_page: int = 50) -> list:
    """Scrape semua halaman dari satu kategori sampai halaman kosong
    ketemu (situs gak expose total halaman di HTML dgn jelas, jadi
    berhenti pas satu halaman gak balikin produk apapun)."""
    semua = []
    for page in range(max_page):
        produk = _scrape_page(category_id, page)
        if not produk:
            break
        for p in produk:
            p["kategori"] = nama_kategori
        semua.extend(produk)
        time.sleep(1.5)  # naikin lagi -- limitnya kumulatif per-jendela-waktu, bukan per-request
    return semua


def scrape_semua(kategori_filter=None, kategori_retries: int = 3) -> list:
    """Scrape tiap kategori satu-satu; kalau satu kategori masih kena
    RateLimited stlh semua retry per-halaman, tunggu jeda PANJANG (limitnya
    kumulatif per-jendela-waktu, cuma nunggu bantu) lalu ulangi kategori itu
    dari awal -- max `kategori_retries` kali sblm nyerah & lapor kategori
    itu kemungkinan gak lengkap."""
    kategori = get_kategori_list()
    if kategori_filter:
        tidak_dikenal = set(kategori_filter) - set(kategori)
        if tidak_dikenal:
            raise ValueError(f"Kategori gak dikenal: {tidak_dikenal}. Pilihan: {list(kategori)}")
        kategori = {k: v for k, v in kategori.items() if k in kategori_filter}

    hasil = []
    gagal = []
    for i, (nama, cid) in enumerate(kategori.items()):
        if i > 0:
            time.sleep(3)  # jeda antar kategori, ngasih napas ke jendela rate-limit
        print(f"  scraping kategori: {nama} (id={cid}) ...")
        for attempt in range(kategori_retries):
            try:
                produk = scrape_kategori(nama, cid)
                break
            except RateLimited as e:
                tunggu = 30 + attempt * 30
                print(f"    kena rate-limit ({e}), tunggu {tunggu}s lalu ulangi kategori ini ...")
                time.sleep(tunggu)
        else:
            print(f"    !! GAGAL total stlh {kategori_retries}x percobaan -- kategori ini kemungkinan gak lengkap")
            gagal.append(nama)
            produk = []
        print(f"    -> {len(produk)} produk")
        hasil.extend(produk)

    if gagal:
        print(f"\n!! Kategori yg gagal lengkap: {gagal} -- coba jalankan ulang khusus kategori ini nanti.")

    # Diamati: urutan produk per kategori kadang GESER antar-request (situs
    # kemungkinan sort by "terakhir diupdate" yg berubah real-time), jadi
    # 2 fetch halaman berurutan bisa overlap & sama produk ke-scrape 2x.
    # Dedup di akhir drpd nyoba bikin pagination-nya deterministik (di luar
    # kendali kita, situs pihak ketiga).
    sebelum = len(hasil)
    seen = set()
    unik = []
    for p in hasil:
        key = (p["kategori"], p["nama"])
        if key in seen:
            continue
        seen.add(key)
        unik.append(p)
    if sebelum != len(unik):
        print(f"\nDedup: {sebelum - len(unik)} baris duplikat dibuang ({sebelum} -> {len(unik)}).")
    return unik


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kategori", nargs="+", help="Nama kategori persis (lihat --list-kategori). Default: semua.")
    ap.add_argument("--list-kategori", action="store_true", help="Cuma tampilkan daftar kategori & keluar.")
    ap.add_argument("--csv", metavar="FILE", help="Simpan hasil ke CSV.")
    ap.add_argument("--json", metavar="FILE", help="Simpan hasil mentah ke JSON.")
    args = ap.parse_args()

    if args.list_kategori:
        for nama, cid in get_kategori_list().items():
            print(f"{cid:3d}  {nama}")
        return

    hasil = scrape_semua(args.kategori)
    print(f"\nTOTAL: {len(hasil)} produk dari {len(set(p['kategori'] for p in hasil))} kategori")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(hasil, f, ensure_ascii=False, indent=2)
        print(f"Disimpan ke {args.json}")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["kategori", "nama", "ukuran", "harga_satuan", "harga_grosir", "gambar"])
            w.writeheader()
            w.writerows(hasil)
        print(f"Disimpan ke {args.csv}")


if __name__ == "__main__":
    main()
