"""Rencana kategori untuk produk PIRANHA yang masih kosong.

Ambang kepercayaannya BUKAN tebakan -- diambil dari uji 5-fold (uji3.py) yang
menyembunyikan 20% label PIRANHA lalu menebaknya kembali:
    nama sama persis   -> 99,6% benar (700/703)
    sinyal kata gap>=2 -> 93,8% benar (178 kasus)
Di bawah gap 2 akurasinya jatuh di bawah 90%, jadi diserahkan ke owner.

Pemulusannya Laplace berbasis ukuran kosakata. Versi sebelumnya memakai
(c+0.12)/(nk+1.2), yang diam-diam MENGHADIAHI kategori langka: untuk nama yang
tak satu katanya dikenali, kategori berisi 1 produk ('permen') selalu menang,
dan 97 produk dapat usulan asal-asalan. Laplace menaikkan akurasi 62,7% -> 78,1%.

Script ini TIDAK menulis apa pun ke Kasir Pintar.
"""
import collections, json, math, re, xlrd

SP = "/private/tmp/claude-501/-Users-okiputra-Documents-sortir/da2ed3d3-4c68-4bbc-926e-f9da1bb06a9f/scratchpad"
GAP_AMAN = 2.0
ALPHA = 0.05
STOP = set("""dan atau isi pcs pak bks btl kg gr gram ml liter ltr renceng sachet sct
kecil besar sedang super spesial baru new the a an of x""".split())


def load(f):
    sh = xlrd.open_workbook(f, ignore_workbook_corruption=True).sheet_by_name("barang")
    h = [str(c.value).strip() for c in sh.row(0)]
    i = {k: h.index(k) for k in ("kode_barang_edit", "nama_barang_edit", "kategori",
                                 "harga_beli_edit", "harga_jual_edit", "stok_edit")}
    out = []
    for r in range(2, sh.nrows):
        kode = str(sh.cell_value(r, i["kode_barang_edit"])).strip()
        if re.fullmatch(r"\d+\.0", kode):      # xlrd bikin barcode numerik jadi float
            kode = kode[:-2]
        def num(k):
            try: return float(sh.cell_value(r, i[k]) or 0)
            except Exception: return 0.0
        out.append(dict(kode=kode, nama=str(sh.cell_value(r, i["nama_barang_edit"])).strip(),
                        kategori=str(sh.cell_value(r, i["kategori"])).strip(),
                        beli=num("harga_beli_edit"), jual=num("harga_jual_edit"),
                        stok=num("stok_edit")))
    return out


def kata(n):
    n = re.sub(r"[^a-z0-9\s]", " ", n.lower())
    return [w for w in n.split() if len(w) > 2 and not w.isdigit() and w not in STOP]


def bangun(data):
    pn = collections.defaultdict(collections.Counter)
    pk = collections.defaultdict(collections.Counter)
    nk = collections.Counter()
    vocab = set()
    for p in data:
        pn[p["nama"].lower()][p["kategori"]] += 1
        nk[p["kategori"]] += 1
        for w in set(kata(p["nama"])):
            pk[p["kategori"]][w] += 1
            vocab.add(w)
    kk = collections.defaultdict(set)
    for k, c in pk.items():
        for w in c:
            kk[w].add(k)
    return pn, pk, nk, kk, len(data), len(vocab)


def tebak(nama, M):
    pn, pk, nk, kk, total, V = M
    c = pn.get(nama.lower())
    if c:
        return c.most_common(1)[0][0], 999.0, "persis"
    ws = set(kata(nama))
    if not ws:
        return None, 0.0, "kosong"
    skor = {}
    for k in nk:
        s = math.log(nk[k] / total)
        for w in ws:
            # makin sedikit kategori yang memakai kata ini, makin kuat sinyalnya
            bobot = 1.0 / (1 + math.log(1 + len(kk.get(w, ()))))
            s += bobot * math.log((pk[k][w] + ALPHA) / (nk[k] + ALPHA * V))
        skor[k] = s
    u = sorted(skor.items(), key=lambda x: -x[1])
    return u[0][0], u[0][1] - u[1][1], "sinyal"


def main():
    pir = load(f"{SP}/piranha_cek.xls")
    sul = load(f"{SP}/sulfat_cek.xls")
    latih = [p for p in pir + sul if p["kategori"]]
    kosong = [p for p in pir if not p["kategori"]]
    kat_pir = {p["kategori"] for p in pir if p["kategori"]}
    M = bangun(latih)

    rencana, tanya = [], []
    for p in kosong:
        k, gap, d = tebak(p["nama"], M)
        r = {"kode": p["kode"], "nama": p["nama"], "kategori": k or "", "dasar": d,
             "gap": None if gap >= 999 else round(gap, 2),
             "beli": p["beli"], "jual": p["jual"], "stok": p["stok"],
             "baru": bool(k) and k not in kat_pir}
        (rencana if (d == "persis" or gap >= GAP_AMAN) else tanya).append(r)

    json.dump(rencana, open(f"{SP}/rencana_piranha.json", "w"), ensure_ascii=False, indent=1)
    json.dump(tanya, open(f"{SP}/tanya_piranha.json", "w"), ensure_ascii=False, indent=1)

    np_ = sum(1 for r in rencana if r["dasar"] == "persis")
    ns = len(rencana) - np_
    print(f"bahan belajar               : {len(latih)} produk berlabel")
    print(f"produk PIRANHA tanpa kategori: {len(kosong)}")
    print(f"  bisa diterapkan langsung   : {len(rencana)}")
    print(f"     nama sama persis        : {np_:4}  (akurasi terukur 99,6%)")
    print(f"     sinyal kata gap>=2      : {ns:4}  (akurasi terukur 93,8%)")
    print(f"  perlu keputusan owner      : {len(tanya)}")
    bar = sorted({r["kategori"] for r in rencana if r["baru"]})
    print(f"  kategori baru perlu dibuat : {bar or 'tidak ada'}")
    print(f"  perkiraan meleset          : ~{round(np_*0.004 + ns*0.062)} dari {len(rencana)}")
    print("\nsebaran usulan otomatis:")
    for k, n in collections.Counter(r["kategori"] for r in rencana).most_common():
        print(f"   {n:4}  {k}")
    print(f"\nyang perlu ditanya, dikelompokkan menurut tebakan terbaiknya:")
    for k, n in collections.Counter(r["kategori"] or "(tak terbaca)" for r in tanya).most_common(18):
        print(f"   {n:4}  ~{k}")


if __name__ == "__main__":
    main()
