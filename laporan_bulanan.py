"""Rakit data tutup buku bulanan dua cabang -> JSON untuk halaman laporan.

Dipakai tiap awal bulan, sesudah berkas transaksi bulan yang baru lewat
dipindah ke data-sulfat/ dan data-piranha/ (lihat ambil_unduhan.py).

Yang dihitung: omzet, untung kotor, margin, struk per bulan; untung bersih
sesudah sortir dan operasional; penjualan per kategori beserta 10 produk
terlaris tiap kategori; dan perbandingan dengan bulan sebelumnya.

TIGA HAL YANG GAMPANG BIKIN ANGKANYA SALAH, dan sudah ditangani di sini:

  1. Tiap berkas laporan punya baris TOTAL di kaki yang Kode & Nama Barang-nya
     kosong. Kalau ikut terbaca, omzet jadi dua kali lipat.
  2. Berkas mingguan bisa beririsan tanggalnya. Satu baris transaksi yang sama
     muncul di dua berkas dihitung sekali saja, lewat sidik (kode transaksi,
     kode barang, timestamp).
  3. Kategori dibaca dari katalog SEKARANG lewat kode barang, bukan dari
     kategori yang tercatat di transaksi. September 2026 ratusan produk baru
     diisi kategorinya; kalau dibaca apa adanya, kategori "(kosong)" terlihat
     runtuh dari Rp47,8 juta ke Rp3,0 juta -- itu perpindahan label, bukan
     penurunan penjualan.

Pakai:
    python3 laporan_bulanan.py 2026-09                     # bulan tertentu
    python3 laporan_bulanan.py 2026-09 --keluar data.json
    python3 laporan_bulanan.py 2026-09 --katalog-sulfat sul.json --katalog-piranha pir.json

Katalog produk (untuk kategori) ditarik dengan kasirpintar_json.py. Kalau tidak
diberikan, kategori diambil apa adanya dari transaksi -- hasilnya masih benar
untuk omzet/untung, tapi perbandingan antar bulan per kategori jadi tidak sah.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
SUMBER = {"SULFAT": "data-sulfat/Laporan_*.xls", "PIRANHA": "data-piranha/Laporan_*.xls"}

# Produk yang sengaja TIDAK ikut dihitung (permintaan owner). Dicocokkan PERSIS
# per nama, huruf besar-kecil diabaikan -- jangan pakai pencocokan sebagian:
# "candi" juga mengenai "bakso candi", produk lain yang harus tetap ikut.
KECUALIKAN = {"pisang candi", "pisang kepok"}

# Produk yang berganti nama/kode di tengah jalan. Dibuang dari daftar penggerak
# saja (bukan dari total), karena penurunannya semu: barangnya pindah nama.
MIGRASI = {"daun pre", "daun pre kg an"}


def _bersih_kode(k):
    k = str(k).strip()
    return k[:-2] if re.fullmatch(r"\d+\.0", k) else k


def _dikecualikan(nama):
    return str(nama).strip().lower() in KECUALIKAN


def baca_transaksi(cabang, bulan_set):
    """Semua baris transaksi untuk bulan-bulan yang diminta, sudah dibersihkan."""
    import xlrd
    out, sudah = [], set()
    for f in sorted(glob.glob(os.path.join(DIR, SUMBER[cabang]))):
        try:
            sh = xlrd.open_workbook(f, ignore_workbook_corruption=True).sheet_by_name("TransaksiBarang")
        except Exception:
            continue
        H = {str(c.value).strip(): i for i, c in enumerate(sh.row(0))}
        for r in range(1, sh.nrows):
            v = sh.row(r)
            kode = _bersih_kode(v[H["Kode Barang"]].value)
            nama = str(v[H["Nama Barang"]].value).strip()
            if not kode and not nama:
                continue                       # baris TOTAL di kaki berkas
            if _dikecualikan(nama):
                continue
            t = str(v[H["Timestamp"]].value).strip()
            if not re.match(r"\d{4}-\d{2}-\d{2}", t) or t[:7] not in bulan_set:
                continue
            sidik = (str(v[H["Kode Transaksi"]].value).strip(), kode, t)
            if sidik in sudah:
                continue                       # berkas beririsan
            sudah.add(sidik)
            g = lambda k: float(v[H[k]].value or 0)
            q = g("Jumlah")
            out.append({"tgl": t[:10], "bulan": t[:7], "kode": kode, "nama": nama,
                        "kat_lama": str(v[H["Kategori"]].value).strip().lower(),
                        "qty": q, "omzet": q * g("Harga Jual"),
                        "untung": q * (g("Harga Jual") - g("Harga Beli")),
                        "struk": str(v[H["Kode Transaksi"]].value).strip()})
    return out


def peta_kategori(path):
    if not path or not os.path.exists(path):
        return {}
    d = {}
    for p in json.load(open(path, encoding="utf-8")):
        k = _bersih_kode(p.get("kode_barang"))
        if k:
            d[k] = (str(p.get("kategori") or "").strip().lower() or "(belum berkategori)")
    return d


def _norm_produk(n):
    n = re.sub(r"[^a-z0-9 ]", " ", str(n).lower())
    n = re.sub(r"\b(kg\s*an|kgan|kg|an|pack|pck)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def beban_bulanan(bulan, transaksi=None):
    """Sortir & operasional bulan itu dari Google Sheet. {cabang: (sortir, opex, rinci)}

    Nilai sortir DIHITUNG ULANG memakai harga beli asli dari transaksi bulan itu,
    bukan kolom "Harga Satuan" di form Input Sortir. Kolom itu sering diisi di
    bawah modal sebenarnya -- tomat pernah dicatat Rp3.000/kg padahal modalnya
    Rp4.000/kg -- sehingga kerugiannya terlihat lebih kecil dari kenyataan.
    Diukur pada September 2026: form meremehkan 12,7% di SULFAT dan 5,8% di
    PIRANHA. Baris yang produknya tidak ketemu di transaksi tetap memakai nilai
    form, karena tidak ada pembanding yang lebih baik.
    """
    try:
        from gsheet_client import load_sortir, load_operasional
    except Exception as e:
        print(f"  (sortir/operasional dilewati -- {str(e)[:60]})", file=sys.stderr)
        return {}
    import statistics
    # harga beli asli per produk, dari transaksi bulan yang sama
    harga = collections.defaultdict(lambda: collections.defaultdict(list))
    for cab, rows in (transaksi or {}).items():
        for r in rows:
            if r["bulan"] == bulan and r["qty"] > 0:
                hb = (r["omzet"] - r["untung"]) / r["qty"]
                if hb > 0:
                    harga[cab][_norm_produk(r["nama"])].append(hb)

    hasil = {}
    srt = collections.defaultdict(float)
    for r in load_sortir():
        if str(r.get("Tanggal", ""))[:7] != bulan:
            continue
        cab = r.get("Cabang")
        try:
            q = float(str(r.get("Qty") or 0).replace(",", ""))
            sub_form = float(str(r.get("Subtotal") or 0).replace(",", ""))
        except ValueError:
            continue
        kand = harga.get(cab, {}).get(_norm_produk(r.get("Produk", "")))
        srt[cab] += q * statistics.median(kand) if kand else sub_form
    ops = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in load_operasional():
        if str(r.get("Tanggal", ""))[:7] == bulan:
            try:
                ops[r.get("Cabang")][str(r.get("Kategori") or "(kosong)")] += \
                    float(str(r.get("Nominal") or 0).replace(",", ""))
            except ValueError:
                pass
    for cab in set(srt) | set(ops):
        rinci = sorted(ops[cab].items(), key=lambda x: -x[1])
        hasil[cab] = (round(srt[cab]), round(sum(ops[cab].values())),
                      [[k, round(v)] for k, v in rinci])
    return hasil


def bulan_sebelum(b):
    y, m = map(int, b.split("-"))
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"


def rakit(bulan, katalog):
    sblm = bulan_sebelum(bulan)
    beban = None     # diisi sesudah transaksi dibaca
    out = {"periode": bulan, "bulan_sebelum": sblm, "kecuali": sorted(KECUALIKAN),
           "ring": {}, "kat": {}, "bersih": {}, "gerak": {}, "rugi": {},
           "bulan": {}, "paruh": {}}
    semua_cab, rows_cab = {}, {}
    for cab in SUMBER:
        rows_cab[cab] = baca_transaksi(cab, {bulan, sblm})
        semua_cab[cab] = baca_transaksi(
            cab, {f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)})
    beban = beban_bulanan(bulan, rows_cab)

    for cab in SUMBER:
        kat = peta_kategori(katalog.get(cab))
        rows = rows_cab[cab]
        semua = semua_cab[cab]
        per_bulan = collections.defaultdict(lambda: [0.0, 0.0, set(), set()])
        for r in semua:
            x = per_bulan[r["bulan"]]
            x[0] += r["omzet"]; x[1] += r["untung"]; x[2].add(r["tgl"]); x[3].add(r["struk"])
        out["bulan"][cab] = [{"b": b, "omzet": round(v[0]), "untung": round(v[1]),
                              "hari": len(v[2]), "struk": len(v[3]),
                              "perhari": round(v[0] / len(v[2])) if v[2] else 0,
                              "margin": round(v[1] / v[0] * 100, 2) if v[0] else 0}
                             for b, v in sorted(per_bulan.items())]
        ini = per_bulan.get(bulan, [0.0, 0.0, set(), set()])
        lalu = per_bulan.get(sblm, [0.0, 0.0, set(), set()])
        out["ring"][cab] = {
            "omzet": round(ini[0]), "untung": round(ini[1]),
            "margin": round(ini[1] / ini[0] * 100, 2) if ini[0] else 0,
            "hari": len(ini[2]), "struk": len(ini[3]),
            "perhari": round(ini[0] / len(ini[2])) if ini[2] else 0,
            "d_omzet": round((ini[0] - lalu[0]) / lalu[0] * 100, 1) if lalu[0] else None,
            "d_untung": round((ini[1] - lalu[1]) / lalu[1] * 100, 1) if lalu[1] else None,
            "d_margin": round((ini[1] / ini[0] - lalu[1] / lalu[0]) * 100, 2)
                        if ini[0] and lalu[0] else None,
        }
        # bulan dengan margin terbaik -- jadi pembanding "untung yang hilang"
        kandidat = [(b, v) for b, v in per_bulan.items() if v[0] > 0]
        pb, pv = max(kandidat, key=lambda x: x[1][1] / x[1][0])
        mp = pv[1] / pv[0]
        out["ring"][cab]["puncak_bln"] = pb
        out["ring"][cab]["puncak_margin"] = round(mp * 100, 2)
        out["ring"][cab]["hilang"] = round(ini[0] * mp - ini[1])
        # paruh pertama vs kedua bulan ini
        hari_ini = collections.defaultdict(lambda: [0.0, 0.0, set()])
        for r in semua:
            if r["bulan"] != bulan:
                continue
            x = hari_ini[r["tgl"]]
            x[0] += r["omzet"]; x[1] += r["untung"]; x[2].add(r["struk"])
        batas = f"{bulan}-15"

        def _paruh(pilih):
            v = [x for t, x in hari_ini.items() if pilih(t)]
            o = sum(x[0] for x in v); u = sum(x[1] for x in v)
            s = sum(len(x[2]) for x in v); n = len(v) or 1
            return {"perhari": round(o / n), "margin": round(u / o * 100, 2) if o else 0,
                    "struk": round(s / n), "hari": len(v)}
        out["paruh"][cab] = {"p1": _paruh(lambda t: t <= batas),
                             "p2": _paruh(lambda t: t > batas)}
        # per kategori + 10 terlaris
        agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        prod = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0.0]))
        for r in rows:
            k = kat.get(r["kode"]) or (r["kat_lama"] or "(belum berkategori)")
            a = agg[r["bulan"]][k]; a[0] += r["omzet"]; a[1] += r["untung"]
            if r["bulan"] == bulan:
                p = prod[k][r["nama"]]
                p[0] += r["qty"]; p[1] += r["omzet"]; p[2] += r["untung"]
        baris = []
        for k, v in agg[bulan].items():
            av = agg[sblm].get(k)
            baris.append({"k": k, "o": round(v[0]), "u": round(v[1]),
                          "m": round(v[1] / v[0] * 100, 1) if v[0] else 0,
                          "ao": round(av[0]) if av else None,
                          "au": round(av[1]) if av else None,
                          "do": round((v[0] - av[0]) / av[0] * 100, 1) if av and av[0] else None,
                          "du": round((v[1] - av[1]) / av[1] * 100, 1) if av and av[1] else None,
                          "top": [[n, round(x[0], 1), round(x[1]), round(x[2])]
                                  for n, x in sorted(prod[k].items(), key=lambda y: -y[1][1])[:10]]})
        baris.sort(key=lambda x: -x["o"])
        out["kat"][cab] = baris
        # penggerak untung per produk
        pu = collections.defaultdict(lambda: collections.defaultdict(float))
        po = collections.defaultdict(lambda: collections.defaultdict(float))
        pq = collections.defaultdict(lambda: collections.defaultdict(float))
        for r in rows:
            pu[r["bulan"]][r["nama"]] += r["untung"]
            po[r["bulan"]][r["nama"]] += r["omzet"]
            pq[r["bulan"]][r["nama"]] += r["qty"]

        def _mg(b, n):
            o = po[b].get(n, 0)
            return round(pu[b].get(n, 0) / o * 100, 1) if o else None
        g = []
        for n in set(pu[bulan]) | set(pu[sblm]):
            if n.strip().lower() in MIGRASI:
                continue
            g.append({"n": n, "d": round(pu[bulan].get(n, 0) - pu[sblm].get(n, 0)),
                      "au": round(pu[sblm].get(n, 0)), "su": round(pu[bulan].get(n, 0)),
                      "am": _mg(sblm, n), "sm": _mg(bulan, n),
                      "aq": round(pq[sblm].get(n, 0), 1), "sq": round(pq[bulan].get(n, 0), 1)})
        g.sort(key=lambda x: x["d"])
        out["gerak"][cab] = {"turun": g[:8], "naik": g[-6:][::-1]}
        out["rugi"][cab] = sorted(
            [{"n": n, "omzet": round(po[bulan][n]), "untung": round(pu[bulan][n]),
              "qty": round(pq[bulan][n], 1)}
             for n in po[bulan] if po[bulan][n] > 200_000 and pu[bulan][n] <= 0],
            key=lambda x: x["untung"])
        # bersih
        s, o, rinci = beban.get(cab, (0, 0, []))
        # dipakai halaman utk memperingatkan kalau nilai form meremehkan sortir
        b = ini[1] - s - o
        out["bersih"][cab] = {"omzet": round(ini[0]), "kotor": round(ini[1]),
                              "margin_kotor": round(ini[1] / ini[0] * 100, 2) if ini[0] else 0,
                              "sortir": s, "opex": o, "opex_rinci": rinci,
                              "bersih": round(b),
                              "margin_bersih": round(b / ini[0] * 100, 2) if ini[0] else 0}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bulan", help="bulan yang dilaporkan, format YYYY-MM")
    ap.add_argument("--keluar", default=None, help="file JSON hasilnya")
    ap.add_argument("--katalog-sulfat", default=None)
    ap.add_argument("--katalog-piranha", default=None)
    a = ap.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}", a.bulan):
        sys.exit("format bulan harus YYYY-MM, mis. 2026-09")
    hasil = rakit(a.bulan, {"SULFAT": a.katalog_sulfat, "PIRANHA": a.katalog_piranha})
    nama = a.keluar or f"laporan_{a.bulan}.json"
    with open(nama, "w", encoding="utf-8") as f:
        json.dump(hasil, f, ensure_ascii=False)
    print(f"Tersimpan: {nama}")
    for cab, v in hasil["bersih"].items():
        print(f"  {cab:8} omzet Rp{v['omzet']:,} | kotor {v['margin_kotor']}% "
              f"| bersih Rp{v['bersih']:,} ({v['margin_bersih']}%)".replace(",", "."))
    if not any(v["opex"] for v in hasil["bersih"].values()):
        print("  (operasional kosong -- margin bersih belum bisa dipercaya)")


if __name__ == "__main__":
    main()
