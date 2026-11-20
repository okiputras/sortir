"""
Uji label bulan PenjualanBulanan (sales_history.py). Tanpa Google Sheets:
sheet-nya diganti tiruan kecil di memori.

Jalankan:
    python3 tests/test_sales_history.py   (tanpa pytest)
    pytest tests/                          (kalau pytest terpasang)
"""

import logging
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)  # st.cache_data di luar `streamlit run` cerewet

import sales_history as SH  # noqa: E402


class _SheetTiruan:
    """Cukup untuk load_all & replace_month: baca semua, clear, header, append."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]

    def get_all_records(self):
        return [dict(r) for r in self.rows]

    def clear(self):
        self.rows = []

    def update(self, values, rng):
        assert values == [SH.HEADER] and rng == "A1"

    def append_rows(self, values, value_input_option=None):
        self.rows += [dict(zip(SH.HEADER, v)) for v in values]


def _pakai(rows):
    sheet = _SheetTiruan(rows)
    SH._ws = lambda: sheet
    SH.load_all.clear()
    return sheet


def _baris(bulan, produk, qty, hari, periode="Siang"):
    return {"Cabang": "PIRANHA", "Bulan": bulan, "Produk": produk, "Qty": qty, "Hari": hari,
            "Timestamp": "2026-11-01 10:00:00", "Periode": periode}


def test_bulan_rapi():
    assert SH._bulan_rapi("2026-9") == "2026-09"
    assert SH._bulan_rapi(" 2026-9 ") == "2026-09"
    assert SH._bulan_rapi("2026-09") == "2026-09"
    assert SH._bulan_rapi("2026-11") == "2026-11"
    assert SH._bulan_rapi("2026-09-01") == "2026-09"
    assert SH._bulan_rapi(46266) == "2026-09"      # nomor seri tanggal Sheets utk 1 Sep 2026
    assert SH._bulan_rapi("") == "" and SH._bulan_rapi("Total") == "Total"


def test_bulan_terpecah_tidak_jadi_bulan_terbaru():
    # Kejadian 1-20 Nov 2026: September PIRANHA Siang terbelah jadi '2026-09' dan '2026-9'.
    benar = [_baris("2026-08", "bayam", 186, 31), _baris("2026-09", "bayam", 188, 30),
             _baris("2026-10", "bayam", 210, 31), _baris("2026-09", "kangkung", 150, 30)]
    terbelah = [dict(r, Bulan="2026-9") if r["Produk"] == "kangkung" else r for r in benar]

    _pakai(benar)
    harap = SH.trend_avg_qty("PIRANHA", months=3, periode="Siang")
    _pakai(terbelah)
    assert {r["Bulan"] for r in SH.load_all()} == {"2026-08", "2026-09", "2026-10"}
    assert SH.trend_avg_qty("PIRANHA", months=3, periode="Siang") == harap
    assert SH.bulan_terupload("PIRANHA", "Siang") == {"2026-08", "2026-09", "2026-10"}


def test_replace_month_menimpa_label_pendek():
    sheet = _pakai([_baris("2026-9", "selada air", 99, 30), _baris("2026-09", "bayam", 99, 30),
                    _baris("2026-09", "bayam", 500, 30, periode="Total")])
    SH.replace_month("PIRANHA", "2026-09", {"bayam": 188, "selada air": 66}, 30, periode="Siang")
    siang = sorted((r["Bulan"], r["Produk"], r["Qty"]) for r in sheet.rows if r["Periode"] == "Siang")
    assert siang == [("2026-09", "bayam", 188), ("2026-09", "selada air", 66)]
    assert [r["Qty"] for r in sheet.rows if r["Periode"] == "Total"] == [500]   # periode lain utuh


if __name__ == "__main__":
    uji = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for f in uji:
        f()
        print("ok ", f.__name__)
    print(f"{len(uji)} uji lulus")
