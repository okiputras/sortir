"""
Update Harga (Olshopin) -- tarik harga jual terbaru dari katalog Olshopin,
hitung harga beli (kg -4.000 / satuan -500), tampilkan preview, lalu tulis ke
tab Produk (kolom harga_jual_edit & harga_beli_edit).

Juga berisi Proyeksi Stok Habis (stok real-time Olshopin vs rata-rata
penjualan harian) & Upload Data Penjualan (sumber data histori penjualan --
dipakai di sini DAN di halaman terpisah "Jadwal Sayur Pagi/Siang").
Proyeksi Stok jalan dari SELURUH katalog Olshopin, tidak terikat ke tab
Produk -- tab Produk cuma dipakai sinkronisasi harga (section paling atas).

Produk yang belum cocok (sinkronisasi harga) otomatis dibiarkan; pemetaan
manual dibaca dari tab ProdukMapping (nama_barang_edit | nama_olshopin).

Dikunci login owner (session "ops_authenticated"), sama seperti Laporan Sortir.
"""
import os

import pandas as pd
import streamlit as st

from gsheet_client import get_spreadsheet, load_cabang
import olshopin_sync as S
import sales_history as SH
from sales_upload import parse_transaksi

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
    "Ambil harga jual terbaru dari katalog Olshopin **toko SULFAT** berdasarkan "
    "nama produk, hitung harga beli otomatis (**kg −4.000**, **satuan −500**), "
    "lalu tulis ke tab **Produk**. (Proyeksi Stok di bawah bisa pilih cabang lain.)"
)


@st.cache_data(ttl=21600, show_spinner=False)
def _catalog():
    return S.fetch_catalog()


@st.cache_data(ttl=21600, show_spinner=False)
def _catalog_for(tid):
    return S.fetch_catalog(tid)


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
    st.info("Klik **Tarik katalog Olshopin** untuk mulai perbandingan harga & lihat stok real-time.")
else:
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
    "Semua produk di **katalog Olshopin cabang terpilih** (bukan cuma yang ada "
    "di tab Produk -- termasuk indomie, saori, dan barang sembako/kemasan lain) "
    "dibandingkan stok real-time-nya dengan rata-rata penjualan **bertren** "
    "(bukan rata-rata datar -- cabang yang penjualannya lagi naik/turun tidak "
    "ketarik ke rata-rata lama), supaya kelihatan produk apa saja yang harus "
    "segera di-restock. **Tiap cabang punya toko Olshopin & stok sendiri-sendiri**."
)

cabang_records = load_cabang()
cabang_list = sorted({r["Nama Cabang"] for r in cabang_records if r.get("Nama Cabang")})

if not cabang_list:
    st.warning("Data master **Cabang** masih kosong. Isi dulu tab Cabang di Google Sheet.")
else:
    c3, c4 = st.columns([1, 1])
    cabang_pilih = c3.selectbox("Cabang", cabang_list, key="proyeksi_cabang")
    hari_target = c4.number_input(
        "Order kalau stok bakal habis dalam berapa hari?",
        min_value=1, max_value=90, value=5, step=1, key="proyeksi_hari",
    )

    tid = S.CABANG_TID.get(cabang_pilih)
    if not tid:
        st.warning(
            f"Belum ada toko Olshopin terdaftar untuk cabang **{cabang_pilih}** "
            "(tambahkan di `olshopin_sync.CABANG_TID`)."
        )
    else:
        bulan_ada = sorted(SH.bulan_terupload(cabang_pilih), reverse=True)
        if not bulan_ada:
            st.info(
                f"Belum ada data penjualan untuk **{cabang_pilih}**. Upload dulu di bagian "
                "**Upload Data Penjualan** di bawah supaya proyeksi bisa dihitung."
            )
        else:
            with st.expander("⚙️ Pengaturan perhitungan (rentang data, kecualikan bulan, buffer)"):
                c5, c6 = st.columns([1, 1])
                n_bulan = c5.number_input(
                    "Pakai berapa bulan data terakhir?",
                    min_value=1, max_value=len(bulan_ada), value=min(6, len(bulan_ada)),
                    step=1, key="proyeksi_bulan",
                )
                buffer_pct = c6.number_input(
                    "Buffer keamanan (%)", min_value=0, max_value=100, value=10, step=5,
                    key="proyeksi_buffer",
                    help="Ditambahkan ke rata-rata bertren sebelum dipakai hitung proyeksi, "
                         "biar tidak pas-pasan.",
                )
                bulan_dikecualikan = st.multiselect(
                    "Kecualikan bulan tertentu dari perhitungan (mis. bulan puasa)",
                    options=bulan_ada, default=[], key="proyeksi_exclude",
                )

            with st.spinner(f"Menarik katalog Olshopin {cabang_pilih}…"):
                catalog_cabang = _catalog_for(tid)
            st.caption(f"Katalog Olshopin {cabang_pilih}: {len(catalog_cabang):,} produk.".replace(",", "."))

            trend_map = SH.trend_avg_qty(  # {nama_norm: (nama_asli, flat, tren, slope)}
                cabang_pilih, months=n_bulan, exclude_bulan=bulan_dikecualikan,
            )
            baris, tanpa_histori = [], []
            for nama_ol, (harga_jual, stok) in catalog_cabang.items():
                n = S.norm(nama_ol)
                v = trend_map.get(n) or trend_map.get(S._strip_kg(n))  # sama spt pencocokan harga di atas
                _, flat, tren, slope = v if v else (None, 0.0, 0.0, 0.0)
                avg_dipakai = tren * (1 + buffer_pct / 100)
                hh = SH.hari_habis(stok, avg_dipakai)
                arah = "↑" if slope > 0.01 else ("↓" if slope < -0.01 else "→")
                item = {
                    "Nama": nama_ol,
                    "Stok Olshopin": stok,
                    "Tren": arah,
                    "Rata² Dipakai (+buffer)": round(avg_dipakai, 2),
                    "Rata² Historis (flat)": round(flat, 2),
                    "Proyeksi Habis (hari)": round(hh, 1) if hh is not None else None,
                }
                (baris if hh is not None else tanpa_histori).append(item)

            bulan_dipakai_teks = [b for b in bulan_ada if b not in bulan_dikecualikan][:n_bulan]
            st.caption(
                f"Data penjualan **{cabang_pilih}** dipakai dari: {', '.join(bulan_dipakai_teks)} "
                f"({len(bulan_dipakai_teks)} bulan"
                + (f", {len(bulan_dikecualikan)} bulan dikecualikan" if bulan_dikecualikan else "")
                + f"). Rata-rata dipakai sudah + buffer {buffer_pct}%."
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
    "penjualan harian di atas, dan juga di menu **Jadwal Sayur Pagi/Siang**. Tidak "
    "perlu tarik katalog Olshopin dulu. Bisa pilih banyak file sekaligus (mis. semua "
    "file mingguan 6 bulan terakhir). Upload ulang untuk bulan yang sama akan "
    "**menimpa** data bulan itu (aman dipakai untuk koreksi), jadi file dari bulan "
    "yang sama sebaiknya diupload sekaligus dalam satu proses."
)

if not cabang_list:
    st.warning("Data master **Cabang** masih kosong. Isi dulu tab Cabang di Google Sheet.")
else:
    up_cabang = st.selectbox("Cabang untuk file yang diupload", cabang_list, key="upload_cabang")
    ups = st.file_uploader(
        "File .xls Kasir Pintar (sheet TransaksiBarang)", type=["xls"],
        accept_multiple_files=True, key="upload_penjualan_files",
    )

    if ups:
        total_mb = sum(u.size for u in ups) / (1024 * 1024)
        st.caption(f"{len(ups)} file dipilih, total {total_mb:.1f} MB.")
        # Server Railway cuma 512 MB RAM. Batas per-file (20 MB) sudah ada di
        # parse_transaksi's caller sejak fitur Laporan Sortir, tapi upload
        # multi-file baru ini juga perlu batas TOTAL -- Streamlit menampung
        # semua file yang dipilih di memori sekaligus sebelum kita sempat
        # memprosesnya, jadi biarpun diproses satu-satu, "modal awal"-nya
        # tetap sebesar total yang dipilih.
        if total_mb > 60:
            st.error(
                f"Total {total_mb:.0f} MB terlalu besar untuk sekali proses di server ini "
                "(server cuma 512 MB RAM). Upload bertahap, mis. per bulan (~5 file "
                "mingguan) sekali proses."
            )
        elif st.button(f"📥 Proses & simpan {len(ups)} file → {up_cabang}", type="primary"):
            # Agregat per bulan sambil jalan, lalu LEPAS DataFrame tiap file
            # begitu kontribusinya sudah diambil -- supaya yang menumpuk di
            # memori cuma satu file mentah + agregat (kecil), bukan seluruh
            # file yang diupload sekaligus.
            # bulan -> {"tanggal": {date,...}, "Total"/"Pagi"/"Siang": {nama: qty}}
            # Pagi = sblm jam 12 (batch keluar jam 4 pagi), Siang = jam 12+
            # (batch tambahan keluar jam 12) -- dipakai halaman Jadwal Sayur.
            agg = {}
            gagal = []
            catatan = []
            seen_baris = set()  # (Timestamp, Nama, Jumlah, Total) yg sudah kehitung
            total_baris = 0
            with st.spinner(f"Memproses {len(ups)} file…"):
                for u in ups:
                    size_mb = u.size / (1024 * 1024)
                    if size_mb > 20:
                        gagal.append(f"{u.name}: {size_mb:.0f} MB > batas 20 MB, dilewati.")
                        continue
                    try:
                        df = parse_transaksi(u.getvalue())
                    except ValueError as e:
                        gagal.append(f"{u.name}: {e}")
                        continue

                    # Export Kasir Pintar kadang tumpang tindih persis satu sama
                    # lain (sudah kejadian: 2 file identik, & 1 file yg isinya
                    # subset penuh dari file lain) -- buang baris yg PERSIS sama
                    # (Timestamp+Nama+Jumlah+Total) dgn yg sudah kehitung dari
                    # file lain di batch upload yang sama, biar tidak dobel.
                    kunci = list(zip(df["Timestamp"], df["Nama"], df["Jumlah"], df["Total"]))
                    baru_mask = [k not in seen_baris for k in kunci]
                    n_dup = len(df) - sum(baru_mask)
                    if n_dup:
                        catatan.append(f"{u.name}: {n_dup} baris dilewati (duplikat dari file lain di batch ini).")
                    df = df[baru_mask]
                    seen_baris.update(k for k, is_baru in zip(kunci, baru_mask) if is_baru)

                    total_baris += len(df)
                    for bulan, grp in df.groupby(df["Timestamp"].dt.strftime("%Y-%m")):
                        slot = agg.setdefault(bulan, {"tanggal": set(), "Total": {}, "Pagi": {}, "Siang": {}})
                        slot["tanggal"].update(grp["Timestamp"].dt.date)
                        potongan = {
                            "Total": grp,
                            "Pagi": grp[grp["Timestamp"].dt.hour < 12],
                            "Siang": grp[grp["Timestamp"].dt.hour >= 12],
                        }
                        for periode, bagian in potongan.items():
                            for nama, qty in bagian.groupby("Nama")["Jumlah"].sum().items():
                                slot[periode][nama] = slot[periode].get(nama, 0) + qty
                    del df, grp, potongan  # lepas memori file ini sebelum lanjut ke file berikutnya

            for g in gagal:
                st.warning(g)
            for c in catatan:
                st.info(c)

            if agg:
                with st.spinner("Menyimpan ke histori penjualan…"):
                    ringkasan = []
                    for bulan, slot in agg.items():
                        hari = len(slot["tanggal"])
                        for periode in ("Total", "Pagi", "Siang"):
                            SH.replace_month(up_cabang, bulan, slot[periode], hari, periode=periode)
                        ringkasan.append((bulan, hari, len(slot["Total"])))
                st.success(
                    f"✅ Tersimpan {total_baris:,} baris transaksi untuk {up_cabang}:".replace(",", ".")
                )
                for bulan, hari, n_produk in sorted(ringkasan):
                    st.caption(f"- **{bulan}**: {hari} hari tercakup, {n_produk} produk.")
                st.rerun()
