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
# 3b. % DARI OMSET (+ margin gabungan Sortir+Operasional)
# ======================================================================
st.subheader("💰 % dari Omset & Dampak Margin")

margin_pct = st.number_input(
    "Asumsi margin kotor (%)",
    min_value=0.0,
    max_value=100.0,
    value=DEFAULT_MARGIN_PCT,
    step=0.1,
    help="Default dari analisis data transaksi Kasir Pintar April 2026 (~12.8%).",
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

if omset_proxy <= 0:
    st.caption(f"Belum cukup data Laporan Harian {tipe_periode.lower()} ini untuk estimasi omset.")
else:
    margin_kotor = omset_proxy * margin_pct / 100

    c1, c2 = st.columns(2)
    c1.metric("Omset (estimasi)", format_rupiah(omset_proxy))
    c2.metric("Operasional / Omset", f"{total_periode / omset_proxy * 100:.1f}%")

    if not kategori_summary.empty:
        kat_pct_omset = kategori_summary.copy()
        kat_pct_omset["% dari Omset"] = kat_pct_omset["total"] / omset_proxy * 100
        st.dataframe(
            kat_pct_omset[["Kategori", "total", "% dari Omset"]].rename(columns={"total": "Total"}),
            hide_index=True,
            width="stretch",
            column_config={
                "Total": st.column_config.NumberColumn(format="Rp %,d"),
                "% dari Omset": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        gaji_row = kat_pct_omset[kat_pct_omset["Kategori"] == "Gaji Karyawan"]
        if not gaji_row.empty:
            gaji_pct = gaji_row.iloc[0]["% dari Omset"]
            if gaji_pct > 20:
                st.warning(f"⚠️ Gaji Karyawan {gaji_pct:.1f}% dari omset -- di atas rentang sehat (~15-20%) untuk retail.")
            else:
                st.caption(f"Gaji Karyawan: {gaji_pct:.1f}% dari omset (rentang sehat retail biasanya ~15-20%).")

    # gabungan sortir + operasional vs margin
    total_sortir_periode = 0.0
    if sortir_records:
        s_df = pd.DataFrame(sortir_records)
        s_df["Tanggal"] = pd.to_datetime(s_df["Tanggal"], errors="coerce")
        s_df["Subtotal"] = pd.to_numeric(s_df["Subtotal"], errors="coerce").fillna(0)
        s_df["periode"] = s_df["Tanggal"].dt.to_period(freq)
        s_df_f = s_df if cabang_selected == "Semua Cabang" else s_df[s_df["Cabang"] == cabang_selected]
        total_sortir_periode = s_df_f[s_df_f["periode"] == periode_terpilih]["Subtotal"].sum()

    total_kebocoran = total_periode + total_sortir_periode
    if margin_kotor > 0:
        pct_kebocoran = total_kebocoran / margin_kotor * 100
        st.markdown(
            f"**Total kebocoran non-stok (Sortir + Operasional): {format_rupiah(total_kebocoran)}** "
            f"= {format_rupiah(total_sortir_periode)} sortir + {format_rupiah(total_periode)} operasional"
        )
        st.error(
            f"📉 Dari margin kotor ~{format_rupiah(margin_kotor)}, **{pct_kebocoran:.1f}% tergerus** "
            f"sortir+operasional gabungan -- margin bersih sebenarnya ~{format_rupiah(margin_kotor - total_kebocoran)}."
        )
    st.caption(
        "Omset estimasi kasar dari Cash+Qris+Debit+Tf di Laporan Harian, bisa kurang akurat kalau ada sesi belum lengkap."
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
