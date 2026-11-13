"""
Hitungan kartu konsinyasi (barang titipan supplier) -- murni, tanpa Streamlit
atau Google Sheets, supaya bisa diuji terpisah. Dipakai views/kartu_konsinyasi.py.

Alur di toko: supplier datang -> sisa barang titipannya di rak dihitung
SEBELUM barang baru ditaruh -> yang terjual dibayar -> barang baru ditaruh.

    Terjual    = Stok lama - Sisa
    Bayar      = Terjual x Harga titip
    Stok akhir = Sisa + Masuk            (= stok lama kunjungan berikutnya)

Ini sama dengan rumus kartu kertas, Terjual = (Stok lama + Masuk) - Sisa,
asalkan "Sisa" di kartu kertas dihitung SESUDAH barang baru ditaruh -- angka
itu adalah Stok akhir di sini. Halaman sengaja meminta sisa SEBELUM barang
baru ditaruh supaya tidak ada dua cara menghitung yang bisa tertukar.

Kunjungan pertama sebuah produk (belum ada riwayat): Terjual = 0, dan sisa
yang terhitung dianggap stok awal.
"""

import re

STATUS_BAYAR = ("Dibayar tunai", "Dibayar transfer", "Belum dibayar")


def angka(value):
    """Angka dari sel sheet/editor; kosong atau bukan angka -> None.
    Menerima "2,5" (koma desimal) maupun 2.5."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)  # NaN -> None
    teks = str(value).strip().replace(" ", "")
    if not teks:
        return None
    if "," in teks and "." not in teks:
        teks = teks.replace(",", ".")
    try:
        return float(teks)
    except ValueError:
        return None


def kunci_waktu(tanggal, timestamp) -> tuple:
    """Urutan kronologis dari kolom Tanggal + Timestamp. Sheet bisa
    mengembalikan jam tanpa nol di depan ("2026-08-04 7:58:35"), jadi
    dibandingkan sebagai angka, bukan teks."""
    def bagian(teks):
        return [int(x) for x in re.findall(r"\d+", str(teks or ""))]

    t = bagian(tanggal)[:3]
    if len(t) == 3 and t[0] < 100:  # dd/mm/yyyy -> yyyy, mm, dd
        t = [t[2], t[1], t[0]]
    return tuple(t + [0] * (3 - len(t))) + tuple((bagian(timestamp)[3:6] + [0, 0, 0])[:3])


def stok_terakhir(kunjungan: list, cabang: str) -> dict:
    """{Produk ID: Stok akhir} dari kunjungan terakhir tiap produk di cabang
    ini. Produk yang belum pernah dicatat tidak ada di hasil (= kunjungan
    pertama)."""
    terakhir = {}
    for r in kunjungan:
        if r.get("Cabang") != cabang:
            continue
        pid = str(r.get("Produk ID") or "").strip()
        if not pid:
            continue
        kunci = kunci_waktu(r.get("Tanggal"), r.get("Timestamp"))
        if pid not in terakhir or kunci >= terakhir[pid][0]:
            terakhir[pid] = (kunci, angka(r.get("Stok Akhir")) or 0.0)
    return {pid: stok for pid, (_, stok) in terakhir.items()}


def hitung(stok_lama, sisa, masuk, harga) -> dict:
    """Satu baris kartu. stok_lama None = kunjungan pertama produk ini."""
    sisa = sisa or 0.0
    masuk = masuk or 0.0
    terjual = 0.0 if stok_lama is None else stok_lama - sisa
    return {"terjual": terjual, "stok_akhir": sisa + masuk, "bayar": terjual * (harga or 0.0)}


def periksa(baris: list) -> list:
    """Pesan kesalahan untuk baris yang diisi. baris: dict produk, stok_lama,
    sisa, masuk (None = tidak diisi). Baris yang sisa & masuknya kosong
    dilewati (produk itu tidak dihitung kali ini)."""
    salah = []
    for b in baris:
        sisa, masuk, lama = b.get("sisa"), b.get("masuk"), b.get("stok_lama")
        if sisa is None and masuk is None:
            continue
        nama = b.get("produk", "")
        if (sisa or 0) < 0 or (masuk or 0) < 0:
            salah.append(f"{nama}: angka tidak boleh minus.")
        elif lama and sisa is None:
            salah.append(f"{nama}: isi Sisa dulu (hitung barangnya di rak), stok lama masih {lama:g}.")
        elif lama is not None and sisa is not None and sisa > lama:
            salah.append(
                f"{nama}: sisa {sisa:g} lebih banyak dari stok lama {lama:g}. "
                "Hitung ulang, atau ada barang masuk yang dulu belum dicatat."
            )
    return salah


def baris_diisi(baris: list) -> list:
    """Baris yang benar-benar diisi (sisa atau masuk), dengan hasil hitungannya."""
    hasil = []
    for b in baris:
        if b.get("sisa") is None and b.get("masuk") is None:
            continue
        h = hitung(b.get("stok_lama"), b.get("sisa"), b.get("masuk"), b.get("harga"))
        hasil.append({**b, "sisa": b.get("sisa") or 0.0, "masuk": b.get("masuk") or 0.0, **h})
    return hasil


def urut(kunjungan: list) -> list:
    """Kunjungan diurutkan dari yang paling lama."""
    return sorted(kunjungan, key=lambda r: kunci_waktu(r.get("Tanggal"), r.get("Timestamp")))


def sesi_terakhir(kunjungan: list, cabang: str, supplier_id: str):
    """Session ID kunjungan terakhir supplier ini di cabang ini (atau None)."""
    milik = [r for r in kunjungan if r.get("Cabang") == cabang and str(r.get("Supplier ID")) == str(supplier_id)]
    return urut(milik)[-1]["Session ID"] if milik else None


def belum_lunas(row: dict) -> bool:
    return str(row.get("Status Bayar", "")).strip().lower().startswith("belum")


def per_sesi(kunjungan: list) -> list:
    """Satu ringkasan per kunjungan (Session ID), urut dari yang paling lama:
    Bayar = jumlah semua produk di kunjungan itu."""
    sesi = {}
    for r in urut(kunjungan):
        s = sesi.setdefault(r["Session ID"], {
            "Session ID": r["Session ID"], "Tanggal": r.get("Tanggal"), "Timestamp": r.get("Timestamp"),
            "Supplier ID": str(r.get("Supplier ID") or ""), "Supplier": r.get("Supplier") or "-",
            "Petugas": r.get("Petugas") or "-", "Bayar": 0.0, "Belum": belum_lunas(r),
            "Status Bayar": r.get("Status Bayar") or "", "Tanggal Bayar": r.get("Tanggal Bayar") or "",
        })
        s["Bayar"] += angka(r.get("Bayar")) or 0.0
    return list(sesi.values())


def tagihan(sesi: dict) -> float:
    """Uang yang masih harus dibayar dari satu kunjungan (0 kalau sudah dibayar)."""
    return sesi["Bayar"] if sesi["Belum"] and sesi["Bayar"] > 0 else 0.0


def sisa_tagihan_berjalan(kunjungan: list) -> dict:
    """{Session ID: total tagihan belum dibayar sampai dengan kunjungan itu},
    berjalan dari kunjungan paling lama. Kunjungan terakhir = sisa tagihan
    sekarang. Kunjungan yang sudah dibayar tidak menambah sisa."""
    jalan, hasil = 0.0, {}
    for s in per_sesi(kunjungan):
        jalan += tagihan(s)
        hasil[s["Session ID"]] = jalan
    return hasil


def belum_dibayar(kunjungan: list, cabang: str, supplier_id: str) -> list:
    """Kunjungan supplier ini di cabang ini yang tagihannya belum dibayar
    (Bayar > 0), urut dari yang paling lama."""
    milik = [r for r in kunjungan if r.get("Cabang") == cabang and str(r.get("Supplier ID")) == str(supplier_id)]
    return [s for s in per_sesi(milik) if tagihan(s) > 0]


def tagihan_per_supplier(kunjungan: list, cabang: str) -> list:
    """Sisa tagihan tiap supplier di cabang ini, dari semua bulan."""
    per = {}
    for s in per_sesi([r for r in kunjungan if r.get("Cabang") == cabang]):
        if tagihan(s) <= 0:
            continue
        t = per.setdefault(s["Supplier ID"], {"Supplier": s["Supplier"], "Kunjungan": 0, "Sisa Tagihan": 0.0, "Sejak": s["Tanggal"]})
        t["Kunjungan"] += 1
        t["Sisa Tagihan"] += tagihan(s)
    return sorted(per.values(), key=lambda t: -t["Sisa Tagihan"])


def rekap(kunjungan: list, cabang: str, bulan: str) -> list:
    """Ringkasan per supplier untuk cabang & bulan "YYYY-MM"."""
    per = {}
    for r in kunjungan:
        if r.get("Cabang") != cabang:
            continue
        k = kunci_waktu(r.get("Tanggal"), r.get("Timestamp"))
        if f"{k[0]:04d}-{k[1]:02d}" != bulan:
            continue
        s = per.setdefault(r.get("Supplier") or "-", {"Supplier": r.get("Supplier") or "-", "sesi": set(), "Terjual": 0.0,
                                                      "Bayar": 0.0, "Sudah dibayar": 0.0, "Belum dibayar": 0.0})
        bayar = angka(r.get("Bayar")) or 0.0
        s["sesi"].add(r.get("Session ID"))
        s["Terjual"] += angka(r.get("Terjual")) or 0.0
        s["Bayar"] += bayar
        if str(r.get("Status Bayar", "")).startswith("Belum"):
            s["Belum dibayar"] += bayar
        else:
            s["Sudah dibayar"] += bayar
    hasil = []
    for s in per.values():
        s["Kunjungan"] = len(s.pop("sesi"))
        hasil.append(s)
    return sorted(hasil, key=lambda s: -s["Bayar"])
