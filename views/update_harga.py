"""
Update Harga (Olshopin) -- tarik harga jual terbaru dari katalog Olshopin,
hitung harga beli (kg -4.000 / satuan -500), tampilkan preview, lalu tulis ke
tab Produk (kolom harga_jual_edit & harga_beli_edit).

Produk yang belum cocok otomatis dibiarkan; pemetaan manual dibaca dari tab
ProdukMapping (nama_barang_edit | nama_olshopin).

Dikunci login owner (session "ops_authenticated"), sama seperti Laporan Sortir.
"""
import os

import pandas as pd
import streamlit as st

from gsheet_client import get_spreadsheet, load_cabang
import olshopin_sync as S
import sales_history as SH
from sales_upload import normalize_name, parse_transaksi

st.title("💰 Update Harga (Olshopin)")

# --- LOGIN GATE (session sama dgn Pengeluaran/Laporan Sortir) ---
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False
if not st.session_state.ops_authenticated:
    st.info("Halaman ini khusus owner. Silakan login dulu.")
    auth_username = os.environ.get("OPS_USERNAME", "oki")
    auth_password = os.environ.get("OPS_PASSWORD", "oki")
    with st.form("update_harga_login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login", type="primary"):
            if username == auth_username and password == auth_password:
                st.session_state.ops_authenticated = True
                st.rerun()
            else:
                st.error("Username / password salah.")
    st.stop()

st.caption(
    "Ambil harga jual terbaru dari katalog Olshopin berdasarkan nama produk, "
    "hitung harga beli otomatis (**kg −4.000**, **satuan −500**), lalu tulis "
    "ke tab **Produk**."
)


@st.cache_data(ttl=21600, show_spinner=False)
def _catalog():
    return S.fetch_catalog()


c1, c2 = st.columns([1, 1])
if c1.button("🔄 Tarik katalog Olshopin", type="primary"):
    with st.spinner("Menarik katalog Olshopin (1 request, ~1–2 dtk)…"):
        st.session_state.olshop_catalog = _catalog()
if c2.button("🧹 Bersihkan cache"):
    _catalog.clear()
    st.session_state.pop("olshop_catalog", None)
    st.info("Cache katalog dibersihkan. Klik 'Tarik katalog' untuk ambil ulang.")

catalog = st.session_state.get("olshop_catalog")
if not catalog:
    st.info("Klik **Tarik katalog Olshopin** untuk mulai.")
    st.stop()

st.success(f"Katalog termuat: {len(catalog):,} produk.".replace(",", "."))

sh = get_spreadsheet()
ws = sh.worksheet("Produk")
rows = ws.get_all_values()[1:]
plan = S.plan_updates(rows, catalog)
matched = [p for p in plan if p["matched"]]
unmatched = [p for p in plan if not p["matched"]]
overridden = sum(1 for p in plan if p.get("override"))

m1, m2, m3 = st.columns(3)
m1.metric("Total produk", len(plan))
m2.metric("Cocok (akan diupdate)", len(matched))
m3.metric("Belum cocok", len(unmatched))
st.caption(
    "Atur langsung di tab **Produk**: kolom **tipe** (kg/satuan) & **nama_olshopin** "
    f"(nama katalog untuk ambil harga). {overridden} produk memakai override nama_olshopin."
)

st.subheader("Preview perubahan (produk cocok)")
df = pd.DataFrame([{
    "Nama": p["nama"], "Tipe": p["tipe"],
    "Jual lama": p["jual_lama"], "Jual baru": p["jual_baru"], "Δ jual": p["jual_baru"] - p["jual_lama"],
    "Beli lama": p["beli_lama"], "Beli baru": p["beli_baru"], "Δ beli": p["beli_baru"] - p["beli_lama"],
    "Olshopin": p["olshopin"],
} for p in matched])
st.dataframe(df, use_container_width=True, hide_index=True, height=420)

with st.expander(f"Belum cocok ({len(unmatched)}) — dibiarkan apa adanya"):
    st.dataframe(
        pd.DataFrame([{"Nama": p["nama"], "Tipe": p["tipe"],
                       "nama_olshopin (diisi tapi tak ada di katalog?)": p["olshopin"] or ""}
                      for p in unmatched]),
        use_container_width=True, hide_index=True,
    )
    st.caption("Untuk mencocokkan: buka tab **Produk**, isi kolom **nama_olshopin** "
               "dengan nama persis di katalog Olshopin (lalu Tarik katalog & cek lagi).")

st.divider()
st.warning("Menerapkan akan **menimpa** harga_jual_edit & harga_beli_edit untuk "
           f"{len(matched)} produk yang cocok. Yang belum cocok tidak diubah.")
if st.button(f"💾 Terapkan ke Sheet ({len(matched)} produk)", type="primary"):
    with st.spinner("Menulis ke sheet…"):
        n = S.apply_updates(ws, plan)
    st.success(f"✅ Selesai — {n} produk diperbarui di tab Produk.")
    st.balloons()

st.divider()
st.header("📦 Proyeksi Stok Habis")
st.caption(
    "Bandingkan **stok real-time Olshopin** dengan rata-rata penjualan harian "
    "(dari data penjualan yang sudah diupload di bagian bawah halaman ini) untuk "
    "tahu produk mana yang harus segera di-restock."
)

cabang_records = load_cabang()
cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})

if not cabang_list:
    st.warning("Data master **Cabang** masih kosong. Isi dulu tab Cabang di Google Sheet.")
else:
    c3, c4 = st.columns([1, 1])
    cabang_pilih = c3.selectbox(
        "Cabang (acuan data penjualan yang dibandingkan ke stok Olshopin)",
        cabang_list, key="proyeksi_cabang",
    )
    hari_target = c4.number_input(
        "Order kalau stok bakal habis dalam berapa hari?",
        min_value=1, max_value=90, value=5, step=1, key="proyeksi_hari",
    )

    bulan_ada = sorted(SH.bulan_terupload(cabang_pilih), reverse=True)
    if not bulan_ada:
        st.info(
            f"Belum ada data penjualan untuk **{cabang_pilih}**. Upload dulu di bagian "
            "**Upload Data Penjualan** di bawah supaya proyeksi bisa dihitung."
        )
    else:
        velocity = SH.avg_daily_qty(cabang_pilih, months=6)
        baris, tanpa_histori = [], []
        for p in matched:
            v = velocity.get(normalize_name(p["nama"]))
            avg = v[1] if v else 0.0
            hh = SH.hari_habis(p["stok"], avg)
            item = {
                "Nama": p["nama"],
                "Stok Olshopin": p["stok"],
                "Rata² Terjual/Hari": round(avg, 2),
                "Proyeksi Habis (hari)": round(hh, 1) if hh is not None else None,
            }
            (baris if hh is not None else tanpa_histori).append(item)

        st.caption(
            f"Data penjualan **{cabang_pilih}** tersedia untuk bulan: {', '.join(bulan_ada)} "
            f"({len(bulan_ada)} bulan, dipakai maks. 6 bulan terbaru)."
        )

        urgent = sorted((b for b in baris if b["Proyeksi Habis (hari)"] <= hari_target),
                         key=lambda b: b["Proyeksi Habis (hari)"])
        st.subheader(f"\U0001F534 Segera order — proyeksi habis ≤ {hari_target} hari ({len(urgent)} produk)")
        if urgent:
            st.dataframe(pd.DataFrame(urgent), use_container_width=True, hide_index=True)
        else:
            st.success("Tidak ada produk yang diproyeksikan habis dalam rentang ini.")

        aman = sorted((b for b in baris if b["Proyeksi Habis (hari)"] > hari_target),
                      key=lambda b: b["Proyeksi Habis (hari)"])
        with st.expander(f"Aman — proyeksi habis > {hari_target} hari ({len(aman)} produk)"):
            st.dataframe(pd.DataFrame(aman), use_container_width=True, hide_index=True)

        if tanpa_histori:
            with st.expander(
                f"Belum ada histori penjualan ({len(tanpa_histori)} produk, belum bisa diproyeksikan)"
            ):
                st.dataframe(
                    pd.DataFrame(tanpa_histori).drop(columns=["Proyeksi Habis (hari)"]),
                    use_container_width=True, hide_index=True,
                )

st.divider()
st.subheader("⬆️ Upload Data Penjualan")
st.caption(
    "Upload export **TransaksiBarang** dari Kasir Pintar (.xls) — sumber rata-rata "
    "penjualan harian di atas. Bisa pilih banyak file sekaligus (mis. semua file "
    "mingguan 6 bulan terakhir). Upload ulang untuk bulan yang sama akan **menimpa** "
    "data bulan itu (aman dipakai untuk koreksi), jadi file dari bulan yang sama "
    "sebaiknya diupload sekaligus dalam satu proses."
)

if not cabang_list:
    st.stop()

up_cabang = st.selectbox("Cabang untuk file yang diupload", cabang_list, key="upload_cabang")
ups = st.file_uploader(
    "File .xls Kasir Pintar (sheet TransaksiBarang)", type=["xls"],
    accept_multiple_files=True, key="upload_penjualan_files",
)

if ups:
    total_mb = sum(u.size for u in ups) / (1024 * 1024)
    st.caption(f"{len(ups)} file dipilih, total {total_mb:.1f} MB.")
    if st.button(f"📥 Proses & simpan {len(ups)} file → {up_cabang}", type="primary"):
        frames, gagal = [], []
        with st.spinner(f"Membaca {len(ups)} file…"):
            for u in ups:
                size_mb = u.size / (1024 * 1024)
                if size_mb > 20:
                    gagal.append(f"{u.name}: {size_mb:.0f} MB > batas 20 MB, dilewati.")
                    continue
                try:
                    frames.append(parse_transaksi(u.getvalue()))
                except ValueError as e:
                    gagal.append(f"{u.name}: {e}")

        for g in gagal:
            st.warning(g)

        if frames:
            with st.spinner("Menyimpan ke histori penjualan…"):
                df = pd.concat(frames, ignore_index=True)
                df["Bulan"] = df["Timestamp"].dt.strftime("%Y-%m")
                ringkasan = []
                for bulan, grp in df.groupby("Bulan"):
                    qty_per_produk = grp.groupby("Nama")["Jumlah"].sum().to_dict()
                    hari = int(grp["Timestamp"].dt.date.nunique())
                    SH.replace_month(up_cabang, bulan, qty_per_produk, hari)
                    ringkasan.append((bulan, hari, len(qty_per_produk)))
            st.success(
                f"✅ Tersimpan {len(df):,} baris transaksi untuk {up_cabang}:".replace(",", ".")
            )
            for bulan, hari, n_produk in sorted(ringkasan):
                st.caption(f"- **{bulan}**: {hari} hari tercakup, {n_produk} produk.")
            st.rerun()
