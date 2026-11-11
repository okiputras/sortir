"""
Uji hitungan kartu konsinyasi (konsinyasi.py). Tanpa Streamlit/Google Sheets.

Jalankan:
    python3 tests/test_konsinyasi.py      (tanpa pytest)
    pytest tests/                          (kalau pytest terpasang)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import konsinyasi as K  # noqa: E402


def _kunjungan(sesi, tanggal, jam, stok_akhir, terjual, bayar, status, cabang="SULFAT"):
    return {
        "Session ID": sesi, "Cabang": cabang, "Supplier ID": "S1", "Supplier": "Bu Sri", "Produk ID": "P1",
        "Tanggal": tanggal, "Timestamp": f"{tanggal} {jam}", "Stok Akhir": stok_akhir,
        "Terjual": terjual, "Bayar": bayar, "Status Bayar": status,
    }


def test_kunjungan_pertama_belum_ada_yang_terjual():
    assert K.hitung(None, None, 20, 2500) == {"terjual": 0.0, "stok_akhir": 20.0, "bayar": 0.0}


def test_kunjungan_berikutnya_sama_dengan_rumus_kartu_kertas():
    h = K.hitung(20, 8, 12, 2500)  # sisa dihitung sebelum barang baru ditaruh
    assert h == {"terjual": 12.0, "stok_akhir": 20.0, "bayar": 30000.0}
    sisa_kertas = 8 + 12  # kartu kertas: sisa sesudah barang baru ditaruh
    assert (20 + 12) - sisa_kertas == h["terjual"]


def test_periksa_menolak_isian_yang_mustahil():
    salah = K.periksa([
        {"produk": "lontong", "stok_lama": 20.0, "sisa": 25.0, "masuk": None},  # sisa > stok lama
        {"produk": "botok", "stok_lama": 5.0, "sisa": None, "masuk": 10.0},     # ada stok, sisa tidak dihitung
        {"produk": "lepet", "stok_lama": None, "sisa": None, "masuk": None},    # tidak diisi -> dilewati
        {"produk": "kue", "stok_lama": None, "sisa": -1.0, "masuk": 3.0},       # minus
        {"produk": "pastel", "stok_lama": 0.0, "sisa": None, "masuk": 6.0},     # stok 0: cukup isi masuk
    ])
    assert len(salah) == 3
    assert "lontong" in salah[0] and "botok" in salah[1] and "kue" in salah[2]


def test_baris_diisi_menghitung_hanya_yang_diisi():
    isi = K.baris_diisi([
        {"produk": "pastel", "stok_lama": 0.0, "sisa": None, "masuk": 6.0, "harga": 2000},
        {"produk": "lepet", "stok_lama": 3.0, "sisa": None, "masuk": None, "harga": 2000},
        {"produk": "botok", "stok_lama": 10.0, "sisa": 4.0, "masuk": 0.0, "harga": 1000},
    ])
    assert [b["produk"] for b in isi] == ["pastel", "botok"]
    assert isi[0]["stok_akhir"] == 6 and isi[1]["terjual"] == 6 and isi[1]["bayar"] == 6000


def test_urutan_waktu_jam_tanpa_nol_dan_format_tanggal():
    assert K.kunci_waktu("2026-08-04", "2026-08-04 7:58:35") < K.kunci_waktu("2026-08-04", "2026-08-04 10:00:00")
    assert K.kunci_waktu("11/11/2026", "")[:3] == (2026, 11, 11)


def test_stok_terakhir_sesi_terakhir_dan_rekap():
    data = [
        _kunjungan("a", "2026-11-01", "9:00:00", 20, 0, 0, "Dibayar tunai"),
        _kunjungan("b", "2026-11-03", "10:00:00", 15, 12, 30000, "Belum dibayar"),
        _kunjungan("c", "2026-11-03", "9:00:00", 99, 1, 2500, "Dibayar tunai"),
        _kunjungan("d", "2026-11-05", "9:00:00", 7, 3, 7500, "Dibayar tunai", cabang="PIRANHA"),
    ]
    assert K.stok_terakhir(data, "SULFAT") == {"P1": 15.0}  # 10:00 lebih akhir dari 9:00
    assert K.stok_terakhir(data, "PIRANHA") == {"P1": 7.0}
    assert K.sesi_terakhir(data, "SULFAT", "S1") == "b"
    r = K.rekap(data, "SULFAT", "2026-11")[0]
    assert (r["Kunjungan"], r["Terjual"], r["Bayar"], r["Belum dibayar"], r["Sudah dibayar"]) == (3, 13.0, 32500.0, 30000.0, 2500.0)


def test_angka_dari_sel():
    assert K.angka("2,5") == 2.5 and K.angka("12") == 12.0 and K.angka(7) == 7.0
    assert K.angka("") is None and K.angka(None) is None and K.angka(float("nan")) is None and K.angka("abc") is None


if __name__ == "__main__":
    uji = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for f in uji:
        f()
        print("ok ", f.__name__)
    print(f"{len(uji)} uji lulus")
