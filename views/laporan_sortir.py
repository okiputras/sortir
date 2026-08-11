"""
Laporan Sortir -- ringkasan untuk owner: produk paling boros, tren
periode ini vs sebelumnya, perbandingan cabang, dan estimasi
dampaknya ke margin/profit. Bisa dilihat per minggu atau per bulan,
dan bisa pilih periode mana saja dari histori yang ada (tidak cuma
yang terbaru).

Dikunci login yang sama dengan Pengeluaran Operasional (session
"ops_authenticated"), karena isinya data margin/profit yang sensitif.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from gsheet_client import load_laporan, load_sortir
from sales_upload import normalize_name, parse_transaksi

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


def format_periode(p: pd.Period, tipe: str) -> str:
    if tipe == "Bulan":
        return p.strftime("%B %Y")
    return f"{p.start_time.date()} – {p.end_time.date()}"


def classify_satuan(qtys: pd.Series) -> str:
    """Tebak satuan produk dari pola angka Qty aslinya -- lebih akurat
    daripada nebak dari nama (nama "kg an" di katalog tidak konsisten,
    ada produk kg beneran yang namanya tidak nyebut "kg" sama sekali,
    mis. "BENGKOANG", "jeruk nipis"). Kalau pernah tercatat pecahan,
    berarti ditimbang (Kg); kalau selalu bilangan bulat, berarti
    dihitung per ikat/pcs."""
    return "Kg" if any(abs(q - round(q)) > 1e-9 for q in qtys if pd.notna(q)) else "Ikat/Pcs"


@st.cache_data(show_spinner=False)
def parse_transaksi_cached(file_bytes: bytes) -> pd.DataFrame:
    """Cache hasil parse per isi file, biar tidak baca ulang tiap rerun."""
    return parse_transaksi(file_bytes)


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

periode_tersedia = sorted(df_f["periode"].unique())  # kronologis, terlama -> terbaru
opsi_periode = list(reversed(periode_tersedia))  # terbaru dulu buat dropdown
periode_terpilih = st.selectbox(
    f"Pilih {tipe_periode.lower()}",
    opsi_periode,
    format_func=lambda p: format_periode(p, tipe_periode),
)

idx = periode_tersedia.index(periode_terpilih)
periode_sebelumnya = periode_tersedia[idx - 1] if idx > 0 else None
is_periode_terbaru = periode_terpilih == periode_tersedia[-1]

df_periode = df_f[df_f["periode"] == periode_terpilih]
total_periode = df_periode["Subtotal"].sum()

today = datetime.now(JAKARTA).date()
periode_belum_selesai = is_periode_terbaru and today <= periode_terpilih.end_time.date()

st.caption(f"Periode dipilih: {format_periode(periode_terpilih, tipe_periode)}")
if periode_belum_selesai:
    hari_terlewat = (today - periode_terpilih.start_time.date()).days + 1
    total_hari = (periode_terpilih.end_time.date() - periode_terpilih.start_time.date()).days + 1
    st.warning(
        f"⚠️ {tipe_periode} ini **belum selesai** (baru hari ke-{hari_terlewat} dari {total_hari}) — "
        f"perbandingan \"vs {tipe_periode.lower()} sebelumnya\" di bawah ini belum adil. "
        f"Baru bisa dibandingkan langsung setelah {tipe_periode.lower()} ini selesai."
    )

# ======================================================================
# UPLOAD DATA PENJUALAN (opsional) -- buka rasio sortir & margin nyata
# ======================================================================
# File Kasir Pintar dikeluarkan per cabang & tidak punya kolom cabang,
# jadi perbandingan cuma valid kalau satu cabang spesifik lagi dipilih.
st.subheader("📤 Data Penjualan (opsional)")

sales_df = None
sales_ov = pd.DataFrame()   # transaksi pada irisan tanggal
sortir_ov = pd.DataFrame()  # sortir pada irisan tanggal yang sama
ov_start = ov_end = None

bisa_upload = not (cabang_selected == "Semua Cabang" and len(cabang_list) > 1)
if not bisa_upload:
    st.caption(
        "Untuk membandingkan sortir dengan penjualan, pilih **satu cabang** dulu "
        "di filter atas (file transaksi Kasir Pintar dikeluarkan per cabang)."
    )
else:
    up = st.file_uploader(
        f"Upload export transaksi Kasir Pintar (.xls) untuk **{cabang_selected}**",
        type=["xls"],
        help=(
            "File 'Laporan' Kasir Pintar yang berisi sheet 'TransaksiBarang'. "
            "Ekspor rentang tanggal yang mencakup periode di atas biar perbandingannya penuh."
        ),
    )
    if up is not None:
        try:
            sales_df = parse_transaksi_cached(up.getvalue())
        except ValueError as e:
            st.error(str(e))
            sales_df = None

if sales_df is not None:
    per_start = periode_terpilih.start_time.date()
    per_end = periode_terpilih.end_time.date()
    file_start = sales_df["Timestamp"].min().date()
    file_end = sales_df["Timestamp"].max().date()
    ov_start = max(per_start, file_start)
    ov_end = min(per_end, file_end)

    if ov_start > ov_end:
        st.warning(
            f"File transaksi mencakup {file_start} – {file_end}, sedangkan "
            f"{tipe_periode.lower()} yang dipilih {per_start} – {per_end}. "
            "Tidak ada tanggal yang beririsan, jadi belum bisa dibandingkan — "
            "pilih periode lain atau ekspor file untuk rentang yang sesuai."
        )
        sales_df = None
    else:
        sd = sales_df["Timestamp"].dt.date
        sales_ov = sales_df[(sd >= ov_start) & (sd <= ov_end)].copy()
        sales_ov["laba"] = (sales_ov["HargaJual"] - sales_ov["HargaBeli"]) * sales_ov["Jumlah"]
        so = df_periode["Tanggal"].dt.date
        sortir_ov = df_periode[(so >= ov_start) & (so <= ov_end)].copy()
        sortir_ov["nama_norm"] = sortir_ov["Produk"].map(normalize_name)

        st.success(
            f"✅ Data penjualan termuat ({file_start} – {file_end}). "
            f"Perbandingan dihitung pada irisan tanggal **{ov_start} – {ov_end}**."
        )
        if not (ov_start == per_start and ov_end == per_end):
            st.warning(
                f"⚠️ File hanya menutupi sebagian {tipe_periode.lower()} ini "
                f"({ov_start} – {ov_end} dari {per_start} – {per_end}). Angka sortir di "
                "bagian perbandingan & margin-nyata ikut dipotong ke rentang itu biar "
                "adil, jadi bisa lebih kecil dari total sortir seluruh periode."
            )

# ======================================================================
# 1. RINGKASAN PERIODE INI VS SEBELUMNYA
# ======================================================================
st.subheader(f"📅 {tipe_periode} Ini vs {tipe_periode} Sebelumnya")

if periode_sebelumnya is not None:
    total_sebelumnya = df_f[df_f["periode"] == periode_sebelumnya]["Subtotal"].sum()
    delta = total_periode - total_sebelumnya
    delta_pct = (delta / total_sebelumnya * 100) if total_sebelumnya > 0 else None

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Sortir {tipe_periode} Ini", format_rupiah(total_periode))
    c2.metric(f"Sortir {tipe_periode} Sebelumnya", format_rupiah(total_sebelumnya))
    c3.metric(
        "Perubahan",
        f"{delta_pct:+.1f}%" if delta_pct is not None else "-",
        delta=format_rupiah(delta),
        delta_color="inverse",  # turun = hijau (bagus), naik = merah
    )

    if delta_pct is not None:
        if delta_pct <= -10:
            st.success(f"🎉 Sortir turun {abs(delta_pct):.1f}% dari {tipe_periode.lower()} sebelumnya — usaha reduce-nya kelihatan hasilnya.")
        elif delta_pct >= 10:
            st.error(f"⚠️ Sortir naik {delta_pct:.1f}% dari {tipe_periode.lower()} sebelumnya — perlu dicek apa penyebabnya.")
        else:
            st.info(f"📊 Sortir relatif stabil dibanding {tipe_periode.lower()} sebelumnya.")
else:
    st.metric(f"Sortir {tipe_periode} Ini", format_rupiah(total_periode))
    st.caption(f"Belum ada data {tipe_periode.lower()} sebelumnya untuk dibandingkan.")

# ======================================================================
# 2. PER CABANG (periode terpilih)
# ======================================================================
if cabang_selected == "Semua Cabang" and len(cabang_list) > 1:
    st.subheader(f"🏪 Per Cabang ({tipe_periode} Ini)")
    per_cabang = df_periode.groupby("Cabang")["Subtotal"].sum().sort_values(ascending=False)
    st.bar_chart(per_cabang)
    st.dataframe(
        per_cabang.reset_index().rename(columns={"Subtotal": "Total Sortir"}),
        hide_index=True,
        width="stretch",
        column_config={"Total Sortir": st.column_config.NumberColumn(format="Rp %,d")},
    )

# ======================================================================
# 3. RANKING PRODUK PALING BOROS (periode terpilih)
# ======================================================================
st.subheader(f"🔥 Ranking Produk Paling Boros ({tipe_periode} Ini)")

# Satuan ditebak dari SELURUH riwayat produk itu (bukan cuma periode
# terpilih) biar polanya lebih kelihatan/akurat.
satuan_map = df_f.groupby("Produk")["Qty"].apply(classify_satuan)

ranking = (
    df_periode.groupby("Produk")
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
    st.caption(f"Belum ada data sortir {tipe_periode.lower()} ini.")
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
        + "\n\n👉 **Paling sering muncul** (cek proses order/simpan): "
        + ", ".join(sering["Produk"].tolist())
    )

# ======================================================================
# 3.5 SORTIR VS PENJUALAN (butuh upload data transaksi)
# ======================================================================
if sales_df is not None and not sortir_ov.empty:
    st.subheader("🧮 Sortir vs Penjualan")

    jual = (
        sales_ov.groupby("nama_norm")
        .agg(qty_jual=("Jumlah", "sum"), omset=("Total", "sum"), untung_jual=("laba", "sum"))
        .reset_index()
    )
    srt = (
        sortir_ov.groupby(["Produk", "nama_norm"])
        .agg(qty_sortir=("Qty", "sum"), rugi_sortir=("Subtotal", "sum"))
        .reset_index()
    )
    m = srt.merge(jual, on="nama_norm", how="left")
    m["cocok"] = m["qty_jual"].notna()
    m["qty_jual"] = m["qty_jual"].fillna(0)
    m["omset"] = m["omset"].fillna(0)
    m["untung_jual"] = m["untung_jual"].fillna(0)
    m["rasio"] = m.apply(lambda r: (r["qty_sortir"] / r["qty_jual"]) if r["qty_jual"] > 0 else None, axis=1)
    # Net cuma bermakna untuk produk yang ketemu di data penjualan; kalau tidak
    # cocok, untung_jual=0 itu artifak (bukan beneran nol untung) -> biarkan kosong.
    m["net"] = (m["untung_jual"] - m["rugi_sortir"]).where(m["cocok"])
    m["Satuan"] = m["Produk"].map(satuan_map)

    # headline
    total_omset = jual["omset"].sum()
    total_untung = jual["untung_jual"].sum()
    total_rugi = sortir_ov["Subtotal"].sum()
    pct_untung_tergerus = (total_rugi / total_untung * 100) if total_untung > 0 else None
    h1, h2, h3 = st.columns(3)
    h1.metric("Omset (irisan)", format_rupiah(total_omset))
    h2.metric("Rugi Sortir (irisan)", format_rupiah(total_rugi))
    h3.metric(
        "Untung Tergerus Sortir",
        f"{pct_untung_tergerus:.1f}%" if pct_untung_tergerus is not None else "-",
        delta=f"-{format_rupiah(total_rugi)}",
    )

    def _fmt_qty(q, sat):
        return f"{q:.2f} kg" if sat == "Kg" else f"{q:.0f} ikat/pcs"

    tampil = m.sort_values(["cocok", "rasio"], ascending=[False, False]).copy()
    tampil["Terjual"] = tampil.apply(
        lambda r: _fmt_qty(r["qty_jual"], r["Satuan"]) if r["cocok"] else "—", axis=1
    )
    tampil["Sortir"] = tampil.apply(lambda r: _fmt_qty(r["qty_sortir"], r["Satuan"]), axis=1)
    tampil["Rasio Sortir"] = tampil["rasio"].apply(
        lambda x: f"{x * 100:.0f}%" if pd.notna(x) else "—"
    )

    st.dataframe(
        tampil[["Produk", "Terjual", "Sortir", "Rasio Sortir", "rugi_sortir", "untung_jual", "net"]]
        .rename(columns={"rugi_sortir": "Rugi Sortir", "untung_jual": "Untung Jual", "net": "Net (Untung-Rugi)"})
        .head(30),
        hide_index=True,
        width="stretch",
        column_config={
            "Rugi Sortir": st.column_config.NumberColumn(format="Rp %,d"),
            "Untung Jual": st.column_config.NumberColumn(format="Rp %,d"),
            "Net (Untung-Rugi)": st.column_config.NumberColumn(format="Rp %,d"),
        },
    )
    st.caption(
        "**Rasio Sortir** = qty disortir ÷ qty terjual pada rentang yang sama — makin tinggi makin boros "
        "relatif ke penjualannya (mis. 19% = dari tiap 100 terjual, ~19 kebuang). "
        "**Net** negatif = rugi sortir produk itu melebihi untung jualannya."
    )

    boros = m[(m["rasio"].notna()) & (m["rasio"] >= 0.15)].sort_values("rasio", ascending=False)
    if not boros.empty:
        st.warning(
            "🔻 **Rasio sortir tinggi (≥15%)** — prioritas cek kualitas/penyimpanan/order: "
            + ", ".join(f"{r['Produk']} ({r['rasio'] * 100:.0f}%)" for _, r in boros.head(8).iterrows())
        )
    net_rugi = m[m["net"] < 0].sort_values("net")
    if not net_rugi.empty:
        st.error(
            "🚨 **Sortir > untung jual** (produk ini makan untung di rentang ini): "
            + ", ".join(net_rugi.head(8)["Produk"].tolist())
        )
    tak_cocok = m[~m["cocok"]]["Produk"].tolist()
    if tak_cocok:
        st.caption(
            "ℹ️ Tidak ketemu di data penjualan (kemungkinan beda ejaan nama, atau memang "
            "tidak terjual di rentang ini): " + ", ".join(tak_cocok[:15])
            + (" …" if len(tak_cocok) > 15 else "")
        )

# ======================================================================
# 4. INSIGHT & REKOMENDASI AKSI
# ======================================================================
st.subheader("🎯 Insight & Rekomendasi Aksi")

pivot = df_f.groupby(["Produk", "periode"])["Subtotal"].sum().unstack(fill_value=0)
pivot = pivot.reindex(columns=periode_tersedia, fill_value=0)
n_periode = len(periode_tersedia)

if n_periode < 2:
    st.caption(
        f"Butuh minimal 2 {tipe_periode.lower()} data untuk insight berulang/lonjakan/rekomendasi kurangi order. "
        f"Baru ada 1 {tipe_periode.lower()} data."
    )
else:
    if n_periode < 4:
        st.caption(
            f"ℹ️ Baru ada {n_periode} {tipe_periode.lower()} data, jadi status \"Berulang\" & saran di bawah ini "
            "masih **awal/kasar** -- gampang sekali produk kelihatan \"berulang\" padahal cuma kebetulan. "
            f"Makin akurat & bisa dipercaya setelah 4+ {tipe_periode.lower()} data terkumpul. "
            "Untuk sekarang, pakai sebagai starting point, bukan keputusan final."
        )

    # rasio & baseline dihitung relatif terhadap periode_terpilih (bukan
    # selalu periode terbaru), biar tetap benar walau lihat histori lama.
    periode_up_to_now = [p for p in periode_tersedia if p <= periode_terpilih]
    pivot_relevan = pivot[periode_up_to_now]
    n_relevan = len(periode_up_to_now)

    muncul_ratio = (pivot_relevan > 0).sum(axis=1) / n_relevan
    nilai_periode = pivot[periode_terpilih]
    periode_sebelum_list = [p for p in periode_up_to_now if p != periode_terpilih]
    baseline = pivot[periode_sebelum_list].mean(axis=1) if periode_sebelum_list else pd.Series(0, index=pivot.index)

    aktif = nilai_periode[nilai_periode > 0].index
    value_rank = nilai_periode.loc[aktif].rank(pct=True)

    insight_rows = []
    for produk in aktif:
        nilai = nilai_periode[produk]
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
                "Muncul": f"{int(round(rasio * n_relevan))}/{n_relevan} {tipe_periode.lower()}",
                f"Nilai {tipe_periode} Ini": nilai,
                "vs Rata² Sebelumnya": f"{(nilai / base * 100 - 100):+.0f}%" if base > 0 else "baru",
                "Lonjakan": "🔺" if is_spike else "",
                "Saran": f"Kurangi order {reduce_pct}%" if reduce_pct > 0 else "Monitor saja",
            }
        )

    insight_df = pd.DataFrame(insight_rows).sort_values(f"Nilai {tipe_periode} Ini", ascending=False)

    spike_list = insight_df[insight_df["Lonjakan"] == "🔺"]["Produk"].tolist()
    if spike_list:
        st.error(
            f"🔺 **Lonjakan tiba-tiba** (naik ≥50% dari rata-rata {tipe_periode.lower()} sebelumnya, cek supplier/kualitas): "
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
        column_config={f"Nilai {tipe_periode} Ini": st.column_config.NumberColumn(format="Rp %,d")},
    )
    st.caption(
        "Rasio 'Muncul' dihitung dari seluruh periode sampai dengan periode yang dipilih. "
        "Skor rekomendasi = 50% peringkat nilai rugi + 50% seberapa sering berulang -- "
        "kian tinggi & kian sering, kian besar saran pengurangannya."
    )

# ======================================================================
# 5. ESTIMASI DAMPAK KE MARGIN/PROFIT
# ======================================================================
st.subheader("💰 Estimasi Dampak ke Margin/Profit")

if sales_df is not None and not sales_ov.empty:
    untung_kotor_nyata = sales_ov["laba"].sum()
    rugi_sortir_nyata = sortir_ov["Subtotal"].sum()
    untung_bersih_nyata = untung_kotor_nyata - rugi_sortir_nyata
    pct_nyata = (rugi_sortir_nyata / untung_kotor_nyata * 100) if untung_kotor_nyata > 0 else None

    st.markdown("**📌 Berdasarkan data penjualan yang diupload (paling akurat):**")
    n1, n2, n3 = st.columns(3)
    n1.metric(f"Untung Kotor ({ov_start} – {ov_end})", format_rupiah(untung_kotor_nyata))
    n2.metric("Rugi Sortir (rentang sama)", format_rupiah(rugi_sortir_nyata))
    n3.metric(
        "Untung Tergerus Sortir",
        f"{pct_nyata:.1f}%" if pct_nyata is not None else "-",
        delta=f"-{format_rupiah(rugi_sortir_nyata)}",
    )
    if pct_nyata is not None:
        st.success(
            f"Dari untung kotor riil ~{format_rupiah(untung_kotor_nyata)}, "
            f"**{format_rupiah(rugi_sortir_nyata)} ({pct_nyata:.1f}%) hilang karena sortir** — "
            f"untung bersih ~{format_rupiah(untung_bersih_nyata)}. "
            "(Untung kotor = (harga jual − harga beli) × qty terjual, langsung dari transaksi.)"
        )
    st.divider()
    st.caption("Angka di bawah ini estimasi kasar (dipakai kalau tidak upload) — abaikan kalau sudah pakai angka nyata di atas.")

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
    lap_df["periode"] = lap_df["Tanggal"].dt.to_period(freq)
    lap_df_f = lap_df if cabang_selected == "Semua Cabang" else lap_df[lap_df["Cabang"] == cabang_selected]
    # dedupe per sesi biar Cash/Qris/dst tidak ke-double-count (berulang di tiap baris item)
    sesi_unik = lap_df_f.drop_duplicates(subset="Session ID")
    sesi_periode = sesi_unik[sesi_unik["periode"] == periode_terpilih]
    omset_proxy = (sesi_periode["Cash"] + sesi_periode["Qris"] + sesi_periode["Debit"] + sesi_periode["Tf"]).sum()

    if omset_proxy > 0:
        margin_kotor = omset_proxy * margin_pct / 100
        margin_bersih = margin_kotor - total_periode
        pct_tergerus = (total_periode / margin_kotor * 100) if margin_kotor > 0 else None

        c1, c2, c3 = st.columns(3)
        c1.metric(f"Omset {tipe_periode} Ini (estimasi)", format_rupiah(omset_proxy))
        c2.metric("Margin Kotor (estimasi)", format_rupiah(margin_kotor))
        c3.metric(
            "Margin Tergerus Sortir",
            f"{pct_tergerus:.1f}%" if pct_tergerus is not None else "-",
            delta=f"-{format_rupiah(total_periode)}",
        )
        st.caption(
            "Omset di sini estimasi kasar dari Cash+Qris+Debit+Tf yang tercatat di Laporan Harian, "
            "bisa kurang akurat kalau ada sesi yang belum lengkap diisi."
        )
        st.success(
            f"Dari margin kotor ~{format_rupiah(margin_kotor)} {tipe_periode.lower()} ini, "
            f"**{format_rupiah(total_periode)} ({pct_tergerus:.1f}%) hilang karena sortir** — "
            f"margin bersih sebenarnya ~{format_rupiah(margin_bersih)}."
        )
    else:
        st.caption(f"Belum cukup data Laporan Harian {tipe_periode.lower()} ini untuk estimasi omset.")
else:
    st.caption("Belum ada data Laporan Harian sama sekali untuk estimasi omset.")

# ======================================================================
# 6. TREN HARIAN (semua data yang ada)
# ======================================================================
st.subheader("📈 Tren Sortir Harian")
harian = df_f.groupby(df_f["Tanggal"].dt.date)["Subtotal"].sum()
st.line_chart(harian)
