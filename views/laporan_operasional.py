"""
Laporan Operasional -- ringkasan untuk owner: breakdown pengeluaran
operasional (listrik, PDAM, gaji karyawan, dll) per kategori, tren
periode ini vs sebelumnya, dan perbandingan cabang. Bisa dilihat per
minggu atau per bulan, dan bisa pilih periode mana saja dari histori
yang ada.

Dikunci login yang sama dengan Pengeluaran Operasional & Laporan Sortir
(session "ops_authenticated").
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import load_laporan, load_operasional, load_sortir

JAKARTA = ZoneInfo("Asia/Jakarta")
DEFAULT_MARGIN_PCT = 12.8  # dari analisis data riil Kasir Pintar April 2026

st.title("📊 Laporan Operasional")

# --- LOGIN GATE (session sama dgn Pengeluaran Operasional / Laporan Sortir) ---
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False

if not st.session_state.ops_authenticated:
    st.info("Halaman ini khusus owner. Silakan login dulu.")
    import os

    auth_username = os.environ.get("OPS_USERNAME", "oki")
    auth_password = os.environ.get("OPS_PASSWORD", "oki")
    with st.form("laporan_ops_login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")
        if submitted:
            if username == auth_username and password == auth_password:
                st.session_state.ops_authenticated = True
                st.rerun()
            else:
                st.error("Username atau password salah.")
    st.stop()

_, logout_col = st.columns([5, 1])
with logout_col:
    if st.button("Logout"):
        st.session_state.ops_authenticated = False
        st.rerun()


def format_rupiah(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def format_periode(p: pd.Period, tipe: str) -> str:
    if tipe == "Bulan":
        return p.strftime("%B %Y")
    return f"{p.start_time.date()} – {p.end_time.date()}"


# --- load data ---
try:
    with st.spinner("Memuat data..."):
        operasional_records = load_operasional()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

if not operasional_records:
    st.info("Belum ada data Pengeluaran Operasional sama sekali.")
    st.stop()

df = pd.DataFrame(operasional_records)
df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors="coerce")
df["Nominal"] = pd.to_numeric(df["Nominal"], errors="coerce").fillna(0)
df = df.dropna(subset=["Tanggal"])

# --- filter: cabang, tipe periode, & periode spesifik ---
f1, f2 = st.columns(2)
with f1:
    cabang_list = sorted(df["Cabang"].dropna().unique().tolist())
    cabang_selected = st.selectbox("Cabang", ["Semua Cabang"] + cabang_list)
with f2:
    tipe_periode = st.selectbox("Lihat per", ["Minggu", "Bulan"])

df_f = df if cabang_selected == "Semua Cabang" else df[df["Cabang"] == cabang_selected]

if df_f.empty:
    st.warning("Tidak ada data untuk cabang ini.")
    st.stop()

freq = "W" if tipe_periode == "Minggu" else "M"
df_f = df_f.copy()
df_f["periode"] = df_f["Tanggal"].dt.to_period(freq)

periode_tersedia = sorted(df_f["periode"].unique())
opsi_periode = list(reversed(periode_tersedia))
periode_terpilih = st.selectbox(
    f"Pilih {tipe_periode.lower()}",
    opsi_periode,
    format_func=lambda p: format_periode(p, tipe_periode),
)

idx = periode_tersedia.index(periode_terpilih)
periode_sebelumnya = periode_tersedia[idx - 1] if idx > 0 else None
is_periode_terbaru = periode_terpilih == periode_tersedia[-1]

df_periode = df_f[df_f["periode"] == periode_terpilih]
total_periode = df_periode["Nominal"].sum()

today = datetime.now(JAKARTA).date()
periode_belum_selesai = is_periode_terbaru and today <= periode_terpilih.end_time.date()

st.caption(f"Periode dipilih: {format_periode(periode_terpilih, tipe_periode)}")
if periode_belum_selesai:
    hari_terlewat = (today - periode_terpilih.start_time.date()).days + 1
    total_hari = (periode_terpilih.end_time.date() - periode_terpilih.start_time.date()).days + 1
    st.warning(
        f"⚠️ {tipe_periode} ini **belum selesai** (baru hari ke-{hari_terlewat} dari {total_hari}) — "
        f"perbandingan \"vs {tipe_periode.lower()} sebelumnya\" di bawah ini belum adil."
    )

# ======================================================================
# 1. RINGKASAN PERIODE INI VS SEBELUMNYA
# ======================================================================
st.subheader(f"📅 {tipe_periode} Ini vs {tipe_periode} Sebelumnya")

if periode_sebelumnya is not None:
    total_sebelumnya = df_f[df_f["periode"] == periode_sebelumnya]["Nominal"].sum()
    delta = total_periode - total_sebelumnya
    delta_pct = (delta / total_sebelumnya * 100) if total_sebelumnya > 0 else None

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Operasional {tipe_periode} Ini", format_rupiah(total_periode))
    c2.metric(f"Operasional {tipe_periode} Sebelumnya", format_rupiah(total_sebelumnya))
    c3.metric(
        "Perubahan",
        f"{delta_pct:+.1f}%" if delta_pct is not None else "-",
        delta=format_rupiah(delta),
        delta_color="inverse",
    )
else:
    st.metric(f"Operasional {tipe_periode} Ini", format_rupiah(total_periode))
    st.caption(f"Belum ada data {tipe_periode.lower()} sebelumnya untuk dibandingkan.")

# ======================================================================
# 1b. PROYEKSI AKHIR PERIODE (kalau periode masih berjalan)
# ======================================================================
if periode_belum_selesai and hari_terlewat > 0:
    rata_rata_harian = total_periode / hari_terlewat
    proyeksi = rata_rata_harian * total_hari
    st.info(
        f"📐 **Proyeksi akhir {tipe_periode.lower()}**: kalau polanya sama sampai hari ke-{total_hari}, "
        f"perkiraan total ~{format_rupiah(proyeksi)} "
        f"(rata-rata {format_rupiah(rata_rata_harian)}/hari × {total_hari} hari)."
    )

# ======================================================================
# 2. PER CABANG (periode terpilih)
# ======================================================================
if cabang_selected == "Semua Cabang" and len(cabang_list) > 1:
    st.subheader(f"🏪 Per Cabang ({tipe_periode} Ini)")
    per_cabang = df_periode.groupby("Cabang")["Nominal"].sum().sort_values(ascending=False)
    st.bar_chart(per_cabang)
    st.dataframe(
        per_cabang.reset_index().rename(columns={"Nominal": "Total Pengeluaran"}),
        hide_index=True,
        width="stretch",
        column_config={"Total Pengeluaran": st.column_config.NumberColumn(format="Rp %,d")},
    )

# ======================================================================
# 3. BREAKDOWN PER KATEGORI (periode terpilih)
# ======================================================================
st.subheader(f"📂 Breakdown per Kategori ({tipe_periode} Ini)")

kategori_summary = (
    df_periode.groupby("Kategori")
    .agg(total=("Nominal", "sum"), kejadian=("Nominal", "count"))
    .sort_values("total", ascending=False)
    .reset_index()
)

if kategori_summary.empty:
    st.caption(f"Belum ada data operasional {tipe_periode.lower()} ini.")
else:
    kategori_summary["pct"] = kategori_summary["total"] / kategori_summary["total"].sum() * 100
    st.bar_chart(kategori_summary.set_index("Kategori")["total"])
    st.dataframe(
        kategori_summary.rename(
            columns={"total": "Total", "kejadian": "Jumlah Transaksi", "pct": "% dari Total"}
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Total": st.column_config.NumberColumn(format="Rp %,d"),
            "% dari Total": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    # detail per kategori
    with st.expander("Lihat detail semua transaksi periode ini"):
        st.dataframe(
            df_periode[["Tanggal", "Cabang", "Kategori", "Keterangan", "Nominal"]].sort_values(
                "Nominal", ascending=False
            ),
            hide_index=True,
            width="stretch",
            column_config={"Nominal": st.column_config.NumberColumn(format="Rp %,d")},
        )

# ======================================================================
# 3b. DARI OMSET KE LABA BERSIH
# ======================================================================
# Kenapa bukan "Operasional / Omset": di toko sayur margin kotornya tipis
# (~13%), jadi biaya yang cuma 3% dari OMSET sebetulnya memakan seperempat
# LABA. Membandingkan biaya ke omset bikin semuanya kelihatan kecil. Yang
# menentukan untung-rugi adalah biaya dibanding laba kotor -- itu kolam
# yang benar-benar dipakai membayar sortir dan operasional.
st.subheader("💰 Dari Omset ke Laba Bersih")

margin_pct = st.number_input(
    "Asumsi margin kotor (%)",
    min_value=0.0,
    max_value=100.0,
    value=DEFAULT_MARGIN_PCT,
    step=0.1,
    help="Default dari analisis data transaksi Kasir Pintar April 2026 (~12.8%). "
         "Ubah kalau margin sekarang sudah beda -- semua angka di bawah ikut berubah.",
)

laporan_records = load_laporan()
sortir_records = load_sortir()

omset_proxy = 0.0
if laporan_records:
    lap_df = pd.DataFrame(laporan_records)
    lap_df["Tanggal"] = pd.to_datetime(lap_df["Tanggal"], errors="coerce")
    for c in ["Cash", "Qris", "Debit", "Tf"]:
        lap_df[c] = pd.to_numeric(lap_df[c], errors="coerce").fillna(0)
    lap_df["periode"] = lap_df["Tanggal"].dt.to_period(freq)
    lap_df_f = lap_df if cabang_selected == "Semua Cabang" else lap_df[lap_df["Cabang"] == cabang_selected]
    sesi_unik = lap_df_f.drop_duplicates(subset="Session ID")
    sesi_periode = sesi_unik[sesi_unik["periode"] == periode_terpilih]
    omset_proxy = (sesi_periode["Cash"] + sesi_periode["Qris"] + sesi_periode["Debit"] + sesi_periode["Tf"]).sum()

total_sortir_periode = 0.0
if sortir_records:
    s_df = pd.DataFrame(sortir_records)
    s_df["Tanggal"] = pd.to_datetime(s_df["Tanggal"], errors="coerce")
    s_df["Subtotal"] = pd.to_numeric(s_df["Subtotal"], errors="coerce").fillna(0)
    s_df["periode"] = s_df["Tanggal"].dt.to_period(freq)
    s_df_f = s_df if cabang_selected == "Semua Cabang" else s_df[s_df["Cabang"] == cabang_selected]
    total_sortir_periode = s_df_f[s_df_f["periode"] == periode_terpilih]["Subtotal"].sum()

# Seberapa lengkap Laporan Harian periode ini? Biaya operasional masuk sekaligus
# (gaji, sewa) sedangkan omset menumpuk hari demi hari -- jadi di awal periode
# laporan ini selalu terlihat rugi besar. Tanpa peringatan, angka -7711% dari
# omset terbaca seolah tokonya bangkrut.
# Pembandingnya panjang periode PENUH, bukan hari yang sudah lewat: gaji dan
# sewa masuk sekali untuk sebulan penuh, jadi menabrakkannya dengan omset satu
# hari selalu menghasilkan angka rugi yang tidak berarti apa-apa.
hari_terisi = 0
hari_periode = 0
if omset_proxy > 0 and laporan_records and not sesi_periode.empty:
    hari_terisi = sesi_periode["Tanggal"].dt.date.nunique()
    hari_periode = max(
        1, (periode_terpilih.end_time.date() - periode_terpilih.start_time.date()).days + 1
    )

if omset_proxy <= 0:
    st.caption(f"Belum cukup data Laporan Harian {tipe_periode.lower()} ini untuk estimasi omset.")
else:
    if hari_periode and hari_terisi < hari_periode:
        st.warning(
            f"⚠️ Laporan Harian periode ini baru terisi **{hari_terisi} dari {hari_periode} hari**. "
            f"Gaji dan sewa sudah masuk utuh untuk satu periode penuh, tapi omsetnya baru "
            f"{hari_terisi} hari — jadi laba bersih di bawah terlalu pesimis. "
            f"Pakai hitungan per hari di bawah, atau tunggu periodenya lengkap."
        )
    belum_lengkap = bool(hari_terisi and hari_periode and hari_terisi < hari_periode)
    laba_kotor = omset_proxy * margin_pct / 100
    total_beban = total_periode + total_sortir_periode
    laba_bersih = laba_kotor - total_beban
    # % dari laba kotor -- angka yang menentukan, bukan % dari omset
    pct_beban = (total_beban / laba_kotor * 100) if laba_kotor > 0 else 0.0
    pct_bersih_omset = laba_bersih / omset_proxy * 100

    # dua baris dua kolom -- empat kolom bikin angka rupiah kepotong "Rp 181.9..."
    r1a, r1b = st.columns(2)
    r1a.metric("Omset (estimasi)", format_rupiah(omset_proxy))
    r1b.metric(f"Laba kotor ({margin_pct:.1f}%)", format_rupiah(laba_kotor))
    r2a, r2b = st.columns(2)
    r2a.metric(
        "− Sortir + Operasional",
        format_rupiah(total_beban),
        delta=(f"{pct_beban:.0f}% dari laba kotor" if 0 < pct_beban < 1000
               else ">999% dari laba kotor" if pct_beban >= 1000 else None),
        delta_color="inverse",
    )
    r2b.metric(
        "= Laba bersih",
        format_rupiah(laba_bersih),
        delta=f"{pct_bersih_omset:.1f}% dari omset",
        delta_color="normal" if laba_bersih >= 0 else "inverse",
    )

    # versi "per Rp 100" -- paling gampang dibayangkan
    g100 = margin_pct
    b100 = total_beban / omset_proxy * 100
    n100 = g100 - b100
    # koma sebagai pemisah desimal -- hanya angkanya, jangan sentuh tanda baca kalimat
    def _desimal(x):
        return f"{x:.2f}".replace(".", ",")

    if not belum_lengkap:
        st.markdown(
            f"Tiap **Rp 100** yang masuk laci: **Rp {_desimal(g100)}** jadi laba kotor, "
            f"**Rp {_desimal(b100)}** habis buat sortir + operasional, "
            f"sisa **Rp {_desimal(n100)}** benar-benar jadi untung."
        )

    if belum_lengkap:
        st.markdown(
            f"**Setara per hari** (dari {hari_terisi} hari yang sudah tercatat): "
            f"omset {format_rupiah(omset_proxy / hari_terisi)}, "
            f"laba kotor {format_rupiah(laba_kotor / hari_terisi)}. "
            f"Kalau tempo ini bertahan sampai {hari_periode} hari, omset periode ini "
            f"kira-kira {format_rupiah(omset_proxy / hari_terisi * hari_periode)} dan "
            f"laba bersihnya "
            f"{format_rupiah(omset_proxy / hari_terisi * hari_periode * margin_pct / 100 - total_beban)}."
        )

    if laba_bersih < 0:
        st.error(
            f"🔴 Sampai sekarang **minus {format_rupiah(abs(laba_bersih))}**"
            + (" — tapi periode ini belum lengkap, lihat hitungan per hari di atas."
               if belum_lengkap else
               f". Laba kotor {format_rupiah(laba_kotor)} tidak cukup menutup "
               f"sortir + operasional {format_rupiah(total_beban)}.")
        )
    elif pct_beban >= 70:
        st.warning(
            f"🟠 {pct_beban:.0f}% laba kotor habis untuk sortir + operasional. "
            f"Sisa untuk pemilik cuma {format_rupiah(laba_bersih)}."
        )
    else:
        st.success(
            f"🟢 {pct_beban:.0f}% laba kotor terpakai sortir + operasional, "
            f"sisa {format_rupiah(laba_bersih)} jadi laba bersih."
        )

    # susunan laba rugi ringkas
    nan = float("nan")
    _lk = (lambda x: x / laba_kotor * 100) if laba_kotor > 0 else (lambda x: nan)
    rincian = pd.DataFrame(
        [
            {"Pos": "Omset", "Nilai": omset_proxy, "% dari Omset": 100.0, "% dari Laba Kotor": nan},
            {"Pos": f"Laba kotor (margin {margin_pct:.1f}%)", "Nilai": laba_kotor,
             "% dari Omset": margin_pct, "% dari Laba Kotor": 100.0},
            {"Pos": "− Sortir", "Nilai": -total_sortir_periode,
             "% dari Omset": -total_sortir_periode / omset_proxy * 100,
             "% dari Laba Kotor": _lk(-total_sortir_periode)},
            {"Pos": "− Operasional", "Nilai": -total_periode,
             "% dari Omset": -total_periode / omset_proxy * 100,
             "% dari Laba Kotor": _lk(-total_periode)},
            {"Pos": "= Laba bersih", "Nilai": laba_bersih,
             "% dari Omset": pct_bersih_omset,
             "% dari Laba Kotor": _lk(laba_bersih)},
        ]
    )
    rincian["Nilai"] = rincian["Nilai"].round()
    st.dataframe(
        rincian,
        hide_index=True,
        width="stretch",
        column_config={
            "Nilai": st.column_config.NumberColumn(format="Rp %,d"),
            "% dari Omset": st.column_config.NumberColumn(format="%.1f%%"),
            "% dari Laba Kotor": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    # titik impas: omset minimum supaya laba bersih nol, dgn margin ini
    if margin_pct > 0:
        omset_bep = total_beban / (margin_pct / 100)
        hari = max(1, hari_terisi)
        selisih = omset_proxy - omset_bep
        st.markdown(
            f"**Titik impas:** dengan margin {margin_pct:.1f}%, omset harus minimal "
            f"**{format_rupiah(omset_bep)}** ({format_rupiah(omset_bep / hari)}/hari dari {hari} hari data) "
            f"cuma untuk menutup sortir + operasional. "
            + (f"Omset periode ini **{format_rupiah(selisih)} di atas** titik itu."
               if selisih >= 0 else
               f"Omset periode ini **{format_rupiah(abs(selisih))} di bawah** titik itu.")
        )
        st.caption(
            f"Kalau margin naik 1 poin jadi {margin_pct + 1:.1f}%, laba bersih naik "
            f"{format_rupiah(omset_proxy * 0.01)} tanpa menambah omset sepeser pun."
        )

    # kategori: yang menentukan adalah porsi terhadap LABA KOTOR
    if not kategori_summary.empty:
        kat_pct = kategori_summary.copy()
        kat_pct["% dari Omset"] = kat_pct["total"] / omset_proxy * 100
        kat_pct["% dari Laba Kotor"] = (
            kat_pct["total"] / laba_kotor * 100 if laba_kotor > 0 else float("nan"))
        st.markdown("**Tiap kategori memakan berapa bagian laba kotor**")
        st.dataframe(
            kat_pct[["Kategori", "total", "% dari Omset", "% dari Laba Kotor"]].rename(
                columns={"total": "Total"}
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Total": st.column_config.NumberColumn(format="Rp %,d"),
                "% dari Omset": st.column_config.NumberColumn(format="%.2f%%"),
                "% dari Laba Kotor": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        gaji_row = kat_pct[kat_pct["Kategori"] == "Gaji Karyawan"]
        if not gaji_row.empty and laba_kotor > 0:
            gaji_rp = gaji_row.iloc[0]["total"]
            gaji_lk = gaji_row.iloc[0]["% dari Laba Kotor"]
            # patokan "15-20% dari omset" itu untuk ritel bermargin tebal.
            # Di sini margin kotornya ~13%, jadi patokan begitu mustahil --
            # yang dipakai porsi terhadap laba kotor.
            if gaji_lk > 60:
                st.warning(
                    f"⚠️ Gaji Karyawan memakan {gaji_lk:.0f}% laba kotor "
                    f"({format_rupiah(gaji_rp)}) -- tersisa sedikit untuk beban lain."
                )
            elif gaji_row.iloc[0]["% dari Omset"] < 2:
                st.info(
                    f"ℹ️ Gaji Karyawan tercatat cuma {format_rupiah(gaji_rp)} "
                    f"({gaji_lk:.1f}% dari laba kotor). Untuk toko seukuran ini angkanya "
                    f"terlalu kecil buat seluruh gaji -- kemungkinan sebagian gaji belum "
                    f"masuk Pengeluaran Operasional, jadi laba bersih di atas masih kelihatan "
                    f"lebih besar dari yang sebenarnya."
                )
            else:
                st.caption(f"Gaji Karyawan: {gaji_lk:.1f}% dari laba kotor ({format_rupiah(gaji_rp)}).")

    st.caption(
        "Omset estimasi kasar dari Cash+Qris+Debit+Tf di Laporan Harian, bisa kurang akurat "
        "kalau ada sesi belum lengkap. Laba kotor memakai asumsi margin di atas, bukan margin "
        "riil per produk -- angka ini pemandu arah, bukan laporan keuangan."
    )

# ======================================================================
# 4. INSIGHT KATEGORI NAIK/TURUN
# ======================================================================
if periode_sebelumnya is not None and not kategori_summary.empty:
    st.subheader("🎯 Insight")
    kat_sebelumnya = (
        df_f[df_f["periode"] == periode_sebelumnya].groupby("Kategori")["Nominal"].sum()
    )
    naik, turun = [], []
    for _, row in kategori_summary.iterrows():
        kat = row["Kategori"]
        nilai_ini = row["total"]
        nilai_lalu = kat_sebelumnya.get(kat, 0)
        if nilai_lalu > 0:
            pct = (nilai_ini - nilai_lalu) / nilai_lalu * 100
            if pct >= 20:
                naik.append(f"{kat} ({pct:+.0f}%)")
            elif pct <= -20:
                turun.append(f"{kat} ({pct:+.0f}%)")

    if naik:
        st.error("🔺 **Kategori naik signifikan** dari " + tipe_periode.lower() + " sebelumnya: " + ", ".join(naik))
    if turun:
        st.success("🎉 **Kategori turun signifikan** dari " + tipe_periode.lower() + " sebelumnya: " + ", ".join(turun))
    if not naik and not turun:
        st.info("📊 Semua kategori relatif stabil dibanding " + tipe_periode.lower() + " sebelumnya.")

# ======================================================================
# 5. TREN HARIAN (semua data yang ada)
# ======================================================================
st.subheader("📈 Tren Operasional Harian")
harian = df_f.groupby(df_f["Tanggal"].dt.date)["Nominal"].sum()
st.line_chart(harian)
