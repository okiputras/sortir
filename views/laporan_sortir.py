"""
Laporan Sortir -- ringkasan mingguan untuk owner: produk paling boros,
tren minggu ini vs minggu lalu, perbandingan cabang, dan estimasi
dampaknya ke margin/profit.

Dikunci login yang sama dengan Pengeluaran Operasional (session
"ops_authenticated"), karena isinya data margin/profit yang sensitif.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import load_laporan, load_sortir

JAKARTA = ZoneInfo("Asia/Jakarta")

DEFAULT_MARGIN_PCT = 12.8  # dari analisis data riil Kasir Pintar April 2026

st.title("📉 Laporan Sortir")

# --- LOGIN GATE (session sama dgn Pengeluaran Operasional) ---
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False

if not st.session_state.ops_authenticated:
    st.info("Halaman ini khusus owner. Silakan login dulu.")
    import os

    auth_username = os.environ.get("OPS_USERNAME", "oki")
    auth_password = os.environ.get("OPS_PASSWORD", "oki")
    with st.form("sortir_report_login_form"):
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


def classify_satuan(qtys: pd.Series) -> str:
    """Tebak satuan produk dari pola angka Qty aslinya -- lebih akurat
    daripada nebak dari nama (nama "kg an" di katalog tidak konsisten,
    ada produk kg beneran yang namanya tidak nyebut "kg" sama sekali,
    mis. "BENGKOANG", "jeruk nipis"). Kalau pernah tercatat pecahan,
    berarti ditimbang (Kg); kalau selalu bilangan bulat, berarti
    dihitung per ikat/pcs."""
    return "Kg" if any(abs(q - round(q)) > 1e-9 for q in qtys if pd.notna(q)) else "Ikat/Pcs"


# --- load data ---
try:
    with st.spinner("Memuat data..."):
        sortir_records = load_sortir()
        laporan_records = load_laporan()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

if not sortir_records:
    st.info("Belum ada data Sortir sama sekali.")
    st.stop()

df = pd.DataFrame(sortir_records)
df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors="coerce")
df["Subtotal"] = pd.to_numeric(df["Subtotal"], errors="coerce").fillna(0)
df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(0)
df = df.dropna(subset=["Tanggal"])
df["minggu"] = df["Tanggal"].dt.to_period("W")

# --- filter cabang ---
cabang_list = sorted(df["Cabang"].dropna().unique().tolist())
cabang_selected = st.selectbox("Cabang", ["Semua Cabang"] + cabang_list)
df_f = df if cabang_selected == "Semua Cabang" else df[df["Cabang"] == cabang_selected]

if df_f.empty:
    st.warning("Tidak ada data untuk cabang ini.")
    st.stop()

# --- tentukan minggu ini & minggu lalu dari data yang ada ---
minggu_tersedia = sorted(df_f["minggu"].unique())
minggu_ini = minggu_tersedia[-1]
minggu_lalu = minggu_tersedia[-2] if len(minggu_tersedia) >= 2 else None

df_minggu_ini = df_f[df_f["minggu"] == minggu_ini]
total_minggu_ini = df_minggu_ini["Subtotal"].sum()

today = datetime.now(JAKARTA).date()
minggu_ini_selesai = today > minggu_ini.end_time.date()
hari_terlewat = (min(today, minggu_ini.end_time.date()) - minggu_ini.start_time.date()).days + 1

st.caption(f"Minggu berjalan: {minggu_ini.start_time.date()} – {minggu_ini.end_time.date()}")
if not minggu_ini_selesai:
    st.warning(
        f"⚠️ Minggu ini **belum selesai** (baru hari ke-{hari_terlewat} dari 7) — "
        "perbandingan \"vs minggu lalu\" di bawah ini belum adil (minggu lalu sudah penuh 7 hari). "
        "Baru bisa dibandingkan langsung setelah minggu ini selesai."
    )

# ======================================================================
# 1. RINGKASAN MINGGU INI VS MINGGU LALU
# ======================================================================
st.subheader("📅 Minggu Ini vs Minggu Lalu")

if minggu_lalu is not None:
    total_minggu_lalu = df_f[df_f["minggu"] == minggu_lalu]["Subtotal"].sum()
    delta = total_minggu_ini - total_minggu_lalu
    delta_pct = (delta / total_minggu_lalu * 100) if total_minggu_lalu > 0 else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Sortir Minggu Ini", format_rupiah(total_minggu_ini))
    c2.metric("Sortir Minggu Lalu", format_rupiah(total_minggu_lalu))
    c3.metric(
        "Perubahan",
        f"{delta_pct:+.1f}%" if delta_pct is not None else "-",
        delta=format_rupiah(delta),
        delta_color="inverse",  # turun = hijau (bagus), naik = merah
    )

    if delta_pct is not None:
        if delta_pct <= -10:
            st.success(f"🎉 Sortir turun {abs(delta_pct):.1f}% dari minggu lalu — usaha reduce-nya kelihatan hasilnya.")
        elif delta_pct >= 10:
            st.error(f"⚠️ Sortir naik {delta_pct:.1f}% dari minggu lalu — perlu dicek apa penyebabnya.")
        else:
            st.info("📊 Sortir relatif stabil dibanding minggu lalu.")
else:
    st.metric("Sortir Minggu Ini", format_rupiah(total_minggu_ini))
    st.caption("Belum ada data minggu lalu untuk dibandingkan.")

# ======================================================================
# 2. PER CABANG (minggu ini)
# ======================================================================
if cabang_selected == "Semua Cabang" and len(cabang_list) > 1:
    st.subheader("🏪 Per Cabang (Minggu Ini)")
    per_cabang = df_minggu_ini.groupby("Cabang")["Subtotal"].sum().sort_values(ascending=False)
    st.bar_chart(per_cabang)
    st.dataframe(
        per_cabang.reset_index().rename(columns={"Subtotal": "Total Sortir"}),
        hide_index=True,
        width="stretch",
        column_config={"Total Sortir": st.column_config.NumberColumn(format="Rp %,d")},
    )

# ======================================================================
# 3. RANKING PRODUK PALING BOROS (minggu ini)
# ======================================================================
st.subheader("🔥 Ranking Produk Paling Boros (Minggu Ini)")

# Satuan ditebak dari SELURUH riwayat produk itu (bukan cuma minggu ini)
# biar polanya lebih kelihatan/akurat, walau qty yang ditampilkan tetap
# qty minggu ini saja.
satuan_map = df_f.groupby("Produk")["Qty"].apply(classify_satuan)

ranking = (
    df_minggu_ini.groupby("Produk")
    .agg(total_rugi=("Subtotal", "sum"), qty=("Qty", "sum"), kejadian=("Subtotal", "count"))
    .sort_values("total_rugi", ascending=False)
    .reset_index()
)
ranking["Satuan"] = ranking["Produk"].map(satuan_map)
ranking["Qty"] = ranking.apply(
    lambda r: f"{r['qty']:.2f} kg" if r["Satuan"] == "Kg" else f"{r['qty']:.0f} ikat/pcs",
    axis=1,
)

if ranking.empty:
    st.caption("Belum ada data sortir minggu ini.")
else:
    st.dataframe(
        ranking[["Produk", "Satuan", "Qty", "total_rugi", "kejadian"]].rename(
            columns={"total_rugi": "Total Rugi", "kejadian": "Jumlah Kejadian"}
        ).head(15),
        hide_index=True,
        width="stretch",
        column_config={"Total Rugi": st.column_config.NumberColumn(format="Rp %,d")},
    )

    top3 = ranking.head(3)
    sering = ranking.sort_values("kejadian", ascending=False).head(3)
    st.warning(
        "👉 **Fokus utama** (nilai rugi terbesar): "
        + ", ".join(top3["Produk"].tolist())
        + "\n\n👉 **Paling sering muncul** (hampir tiap hari, cek proses order/simpan): "
        + ", ".join(sering["Produk"].tolist())
    )

# ======================================================================
# 4. INSIGHT & REKOMENDASI AKSI
# ======================================================================
st.subheader("🎯 Insight & Rekomendasi Aksi")

pivot = df_f.groupby(["Produk", "minggu"])["Subtotal"].sum().unstack(fill_value=0)
pivot = pivot.reindex(columns=minggu_tersedia, fill_value=0)
n_minggu = len(minggu_tersedia)

if n_minggu < 2:
    st.caption(
        "Butuh minimal 2 minggu data untuk insight berulang/lonjakan/rekomendasi kurangi order. "
        "Baru ada 1 minggu data."
    )
else:
    if n_minggu < 4:
        st.caption(
            f"ℹ️ Baru ada {n_minggu} minggu data, jadi status \"Berulang\" & saran di bawah ini masih "
            "**awal/kasar** -- gampang sekali produk kelihatan \"berulang\" padahal cuma kebetulan muncul "
            "di kedua-duanya. Makin akurat & bisa dipercaya setelah 4+ minggu data terkumpul. "
            "Untuk sekarang, pakai sebagai starting point, bukan keputusan final."
        )

    muncul_ratio = (pivot > 0).sum(axis=1) / n_minggu
    nilai_minggu_ini = pivot[minggu_ini]
    minggu_sebelum = [m for m in minggu_tersedia if m != minggu_ini]
    baseline = pivot[minggu_sebelum].mean(axis=1)

    aktif = nilai_minggu_ini[nilai_minggu_ini > 0].index
    value_rank = nilai_minggu_ini.loc[aktif].rank(pct=True)

    insight_rows = []
    for produk in aktif:
        nilai = nilai_minggu_ini[produk]
        rasio = muncul_ratio[produk]
        base = baseline[produk]
        is_berulang = rasio >= 0.66
        is_spike = base > 0 and nilai >= base * 1.5

        score = 0.5 * value_rank[produk] + 0.5 * rasio
        if score >= 0.75:
            reduce_pct = 30
        elif score >= 0.55:
            reduce_pct = 20
        elif score >= 0.35 and is_berulang:
            reduce_pct = 10
        else:
            reduce_pct = 0

        if is_berulang:
            status = "🔁 Berulang"
        elif base == 0:
            status = "🆕 Baru"
        else:
            status = "Sesekali"

        insight_rows.append(
            {
                "Produk": produk,
                "Status": status,
                "Muncul": f"{int(round(rasio * n_minggu))}/{n_minggu} minggu",
                "Nilai Minggu Ini": nilai,
                "vs Rata² Sebelumnya": f"{(nilai / base * 100 - 100):+.0f}%" if base > 0 else "baru",
                "Lonjakan": "🔺" if is_spike else "",
                "Saran": f"Kurangi order {reduce_pct}%" if reduce_pct > 0 else "Monitor saja",
            }
        )

    insight_df = pd.DataFrame(insight_rows).sort_values("Nilai Minggu Ini", ascending=False)

    spike_list = insight_df[insight_df["Lonjakan"] == "🔺"]["Produk"].tolist()
    if spike_list:
        st.error(
            "🔺 **Lonjakan tiba-tiba** (naik ≥50% dari rata-rata minggu sebelumnya, cek supplier/kualitas): "
            + ", ".join(spike_list)
        )

    reduce_list = insight_df[insight_df["Saran"] != "Monitor saja"]
    if not reduce_list.empty:
        st.warning(
            "✂️ **Kandidat kurangi order** (boros & konsisten berulang): "
            + ", ".join(f"{r['Produk']} ({r['Saran'].replace('Kurangi order ', '-')})" for _, r in reduce_list.iterrows())
        )

    st.dataframe(
        insight_df,
        hide_index=True,
        width="stretch",
        column_config={"Nilai Minggu Ini": st.column_config.NumberColumn(format="Rp %,d")},
    )
    st.caption(
        "Rasio 'Muncul' dihitung dari seluruh minggu yang ada datanya. "
        "Skor rekomendasi = 50% peringkat nilai rugi minggu ini + 50% seberapa sering berulang -- "
        "kian tinggi & kian sering, kian besar saran pengurangannya."
    )

# ======================================================================
# 5. ESTIMASI DAMPAK KE MARGIN/PROFIT
# ======================================================================
st.subheader("💰 Estimasi Dampak ke Margin/Profit")

margin_pct = st.number_input(
    "Asumsi margin kotor (%)",
    min_value=0.0,
    max_value=100.0,
    value=DEFAULT_MARGIN_PCT,
    step=0.1,
    help="Default dari analisis data transaksi Kasir Pintar April 2026 (~12.8%). Sesuaikan kalau kamu punya angka margin aktual yang lebih baru.",
)

if laporan_records:
    lap_df = pd.DataFrame(laporan_records)
    lap_df["Tanggal"] = pd.to_datetime(lap_df["Tanggal"], errors="coerce")
    for c in ["Cash", "Qris", "Debit", "Tf"]:
        lap_df[c] = pd.to_numeric(lap_df[c], errors="coerce").fillna(0)
    lap_df["minggu"] = lap_df["Tanggal"].dt.to_period("W")
    lap_df_f = lap_df if cabang_selected == "Semua Cabang" else lap_df[lap_df["Cabang"] == cabang_selected]
    # dedupe per sesi biar Cash/Qris/dst tidak ke-double-count (berulang di tiap baris item)
    sesi_unik = lap_df_f.drop_duplicates(subset="Session ID")
    sesi_minggu_ini = sesi_unik[sesi_unik["minggu"] == minggu_ini]
    omset_proxy = (sesi_minggu_ini["Cash"] + sesi_minggu_ini["Qris"] + sesi_minggu_ini["Debit"] + sesi_minggu_ini["Tf"]).sum()

    if omset_proxy > 0:
        margin_kotor = omset_proxy * margin_pct / 100
        margin_bersih = margin_kotor - total_minggu_ini
        pct_tergerus = (total_minggu_ini / margin_kotor * 100) if margin_kotor > 0 else None

        c1, c2, c3 = st.columns(3)
        c1.metric("Omset Minggu Ini (estimasi)", format_rupiah(omset_proxy))
        c2.metric("Margin Kotor (estimasi)", format_rupiah(margin_kotor))
        c3.metric(
            "Margin Tergerus Sortir",
            f"{pct_tergerus:.1f}%" if pct_tergerus is not None else "-",
            delta=f"-{format_rupiah(total_minggu_ini)}",
        )
        st.caption(
            "Omset di sini estimasi kasar dari Cash+Qris+Debit+Tf yang tercatat di Laporan Harian, "
            "bisa kurang akurat kalau ada sesi yang belum lengkap diisi."
        )
        st.success(
            f"Dari margin kotor ~{format_rupiah(margin_kotor)} minggu ini, "
            f"**{format_rupiah(total_minggu_ini)} ({pct_tergerus:.1f}%) hilang karena sortir** — "
            f"margin bersih sebenarnya ~{format_rupiah(margin_bersih)}."
        )
    else:
        st.caption("Belum cukup data Laporan Harian minggu ini untuk estimasi omset.")
else:
    st.caption("Belum ada data Laporan Harian sama sekali untuk estimasi omset.")

# ======================================================================
# 6. TREN HARIAN (semua data yang ada)
# ======================================================================
st.subheader("📈 Tren Sortir Harian")
harian = df_f.groupby(df_f["Tanggal"].dt.date)["Subtotal"].sum()
st.line_chart(harian)
