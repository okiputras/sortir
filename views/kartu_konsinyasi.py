"""
Kartu Konsinyasi -- pengganti kartu kertas konsinyasi (Tipe A & B).

Dipakai kasir saat supplier titipan datang: hitung sisa barangnya di rak
SEBELUM barang baru ditaruh, catat barang baru yang dibawa, lalu halaman ini
menghitung yang terjual dan yang harus dibayar. Rumus dan alasannya ada di
konsinyasi.py. Satu kunjungan = satu Session ID, satu baris per produk.

Terbuka untuk semua karyawan seperti Input Sortir. Hanya tab "Kelola"
(supplier, produk, harga titip) yang memakai login owner (ops_authenticated),
karena harga titip menentukan uang yang dibayar ke supplier.

Hapus dibatasi ke kunjungan TERAKHIR supplier itu: stok lama tiap kunjungan
diambil dari kunjungan sebelumnya, jadi menghapus kunjungan di tengah membuat
hitungan sesudahnya salah. Karyawan hanya bisa menghapus kunjungan hari ini;
yang lebih lama perlu login owner.
"""

import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import konsinyasi as K
from gsheet_client import (
    append_konsinyasi,
    delete_konsinyasi,
    load_all_konsinyasi,
    simpan_konsinyasi_master,
    tambah_konsinyasi_master,
    update_konsinyasi,
)

JAKARTA = ZoneInfo("Asia/Jakarta")
AUTH_USERNAME = os.environ.get("OPS_USERNAME", "oki")
AUTH_PASSWORD = os.environ.get("OPS_PASSWORD", "oki")
RUPIAH = st.column_config.NumberColumn(format="Rp %,d")

st.title("🤝 Kartu Konsinyasi")


def rupiah(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def aktif(row: dict) -> bool:
    return str(row.get("Aktif", "Ya")).strip().lower() not in ("tidak", "false", "0", "no")


def sekarang() -> datetime:
    return datetime.now(JAKARTA)


# --- init session state ---
if "kons_versi" not in st.session_state:
    st.session_state.kons_versi = 0
if "ops_authenticated" not in st.session_state:
    st.session_state.ops_authenticated = False
versi = st.session_state.kons_versi

# --- load data ---
try:
    with st.spinner("Memuat data..."):
        data = load_all_konsinyasi()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

cabang_list = sorted({r["Nama Cabang"] for r in data["cabang"] if r.get("Nama Cabang")})
karyawan_list = sorted({r["Nama Karyawan"] for r in data["karyawan"] if r.get("Nama Karyawan")})
supplier_rows = [r for r in data["master"]["supplier"] if r.get("ID")]
produk_rows = [r for r in data["master"]["produk"] if r.get("ID")]
kunjungan = data["kunjungan"]

if not cabang_list:
    st.warning("Data master Cabang masih kosong. Isi dulu langsung di Google Sheet-nya.")
    st.stop()

supplier_by_id = {str(r["ID"]): r for r in supplier_rows}


def nama_supplier(sid) -> str:
    return str(supplier_by_id.get(str(sid), {}).get("Nama Supplier") or sid)


if "kons_pesan" in st.session_state:
    st.success(st.session_state.pop("kons_pesan"))

cabang = st.selectbox("Cabang", cabang_list, key="kons_cabang")
produk_cabang = [p for p in produk_rows if p.get("Cabang") == cabang]
stok = K.stok_terakhir(kunjungan, cabang)
kunjungan_cabang = [r for r in kunjungan if r.get("Cabang") == cabang]

tab_catat, tab_kartu, tab_rekap, tab_kelola = st.tabs(
    ["Catat kunjungan", "Kartu per supplier", "Rekap bulanan", "Kelola supplier & produk"]
)

# =========================================================== Catat kunjungan
with tab_catat:
    produk_aktif = [
        p for p in produk_cabang if aktif(p) and aktif(supplier_by_id.get(str(p.get("Supplier ID")), {}))
    ]
    supplier_aktif = sorted({str(p["Supplier ID"]) for p in produk_aktif}, key=nama_supplier)
    if not supplier_aktif:
        st.info(
            "Belum ada supplier titipan aktif untuk cabang ini. Owner bisa menambahkan "
            "supplier, produk, dan harga titipnya di tab **Kelola supplier & produk**."
        )
    else:
        c1, c2 = st.columns(2)
        tanggal = c1.date_input("Tanggal", value=sekarang().date(), key=f"kons_tgl_{versi}")
        petugas = c2.selectbox(
            "Petugas (kasir)", karyawan_list, index=None, placeholder="Pilih nama", key=f"kons_petugas_{versi}"
        )
        sid = st.selectbox(
            "Supplier yang datang", supplier_aktif, index=None, format_func=nama_supplier,
            placeholder="Pilih supplier", key=f"kons_supplier_{versi}",
        )
        if sid:
            sup = supplier_by_id.get(sid, {})
            keterangan = [x for x in (sup.get("No HP"), sup.get("Sistem Bayar")) if x]
            if keterangan:
                st.caption(" · ".join(str(x) for x in keterangan))
            milik = K.urut([r for r in kunjungan_cabang if str(r.get("Supplier ID")) == sid])
            if milik:
                sesi = milik[-1]["Session ID"]
                rows_t = [r for r in milik if r["Session ID"] == sesi]
                st.caption(
                    f"Kunjungan terakhir {rows_t[0]['Tanggal']} oleh {rows_t[0].get('Petugas') or '-'}: "
                    f"bayar {rupiah(sum(K.angka(r.get('Bayar')) or 0 for r in rows_t))} "
                    f"({str(rows_t[0].get('Status Bayar') or '-').lower()})."
                )
                if K.kunci_waktu(tanggal.isoformat(), "")[:3] < K.kunci_waktu(rows_t[0]["Tanggal"], "")[:3]:
                    st.warning("Tanggal ini lebih awal dari kunjungan terakhir. Stok lama tetap diambil dari kunjungan terakhir.")

            items = sorted([p for p in produk_aktif if str(p["Supplier ID"]) == sid], key=lambda p: str(p["Nama Produk"]))
            st.caption(
                "Hitung **sisa** barang di rak **sebelum** barang baru ditaruh. **Masuk** = barang baru "
                "yang dibawa hari ini. Produk yang tidak dihitung kali ini biarkan kosong."
            )
            # NaN (bukan None) untuk sel kosong: kolom harus bertipe angka supaya
            # data_editor menampilkan isian angka -- kolom yang isinya None semua
            # akan jadi kolom teks (object) di pandas.
            kosong = float("nan")
            awal = pd.DataFrame(
                [
                    {
                        "Produk": str(p["Nama Produk"]),
                        "Harga Titip": K.angka(p.get("Harga Titip")) or 0.0,
                        "Stok Lama": stok.get(str(p["ID"]), kosong),
                        "Sisa": kosong,
                        "Masuk": kosong,
                    }
                    for p in items
                ]
            )
            edited = st.data_editor(
                awal,
                hide_index=True,
                width="stretch",
                num_rows="fixed",
                key=f"kons_editor_{sid}_{versi}",
                column_config={
                    "Produk": st.column_config.TextColumn(disabled=True),
                    "Harga Titip": st.column_config.NumberColumn(format="Rp %,d", disabled=True),
                    "Stok Lama": st.column_config.NumberColumn(
                        disabled=True, help="Stok akhir kunjungan sebelumnya. Kosong = kunjungan pertama."
                    ),
                    "Sisa": st.column_config.NumberColumn(min_value=0, step=1, help="Dihitung di rak sebelum barang baru ditaruh."),
                    "Masuk": st.column_config.NumberColumn(min_value=0, step=1, help="Barang baru yang dibawa hari ini."),
                },
            )
            baris = [
                {
                    "produk_id": str(p["ID"]),
                    "produk": str(p["Nama Produk"]),
                    "harga": K.angka(p.get("Harga Titip")) or 0.0,
                    "stok_lama": stok.get(str(p["ID"])),
                    "sisa": K.angka(row["Sisa"]),
                    "masuk": K.angka(row["Masuk"]),
                }
                for p, (_, row) in zip(items, edited.iterrows())
            ]
            salah = K.periksa(baris)
            for pesan in salah:
                st.error(pesan)
            isi = [] if salah else K.baris_diisi(baris)
            if isi:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Produk": b["produk"],
                                "Stok lama": b["stok_lama"],
                                "Sisa": b["sisa"],
                                "Terjual": b["terjual"],
                                "Masuk": b["masuk"],
                                "Stok akhir": b["stok_akhir"],
                                "Bayar": b["bayar"],
                            }
                            for b in isi
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={"Bayar": RUPIAH},
                )
                total = sum(b["bayar"] for b in isi)
                st.markdown(f"**Dibayar ke supplier: {rupiah(total)}**")
                if any(b["stok_lama"] is None for b in isi):
                    st.caption("Produk tanpa stok lama dihitung sebagai kunjungan pertama: sisanya dianggap stok awal, belum ada yang dibayar.")

                tunda = any(k in str(sup.get("Sistem Bayar", "")).lower() for k in ("minggu", "bulan", "tempo", "nanti"))
                status = st.radio(
                    "Pembayaran", K.STATUS_BAYAR, index=2 if tunda else 0, horizontal=True, key=f"kons_status_{versi}"
                )
                setuju = st.checkbox("Supplier sudah melihat jumlah ini dan setuju", key=f"kons_setuju_{versi}")
                catatan = st.text_input("Catatan (opsional)", key=f"kons_catatan_{versi}")
                kurang = [t for t, ok in (("pilih nama petugas", petugas), ("centang persetujuan supplier", setuju)) if not ok]
                if kurang:
                    st.caption("Sebelum simpan: " + " dan ".join(kurang) + ".")
                if st.button("Simpan kunjungan", type="primary", disabled=bool(kurang), width="stretch"):
                    waktu = sekarang().strftime("%Y-%m-%d %H:%M:%S")
                    sesi_baru = str(uuid.uuid4())
                    rows = [
                        {
                            "Session ID": sesi_baru,
                            "Tanggal": tanggal.isoformat(),
                            "Cabang": cabang,
                            "Supplier ID": sid,
                            "Supplier": nama_supplier(sid),
                            "Produk ID": b["produk_id"],
                            "Produk": b["produk"],
                            "Harga Titip": b["harga"],
                            "Stok Lama": "" if b["stok_lama"] is None else b["stok_lama"],
                            "Sisa": b["sisa"],
                            "Terjual": b["terjual"],
                            "Masuk": b["masuk"],
                            "Stok Akhir": b["stok_akhir"],
                            "Bayar": b["bayar"],
                            "Petugas": petugas,
                            "Disetujui Supplier": "Ya",
                            "Status Bayar": status,
                            "Catatan": catatan.strip(),
                            "Timestamp": waktu,
                        }
                        for b in isi
                    ]
                    with st.spinner("Menyimpan..."):
                        append_konsinyasi(rows)
                    st.session_state.kons_pesan = (
                        f"Kunjungan {nama_supplier(sid)} tersimpan: {rupiah(total)} ({status.lower()})."
                    )
                    st.session_state.kons_versi += 1
                    st.rerun()

# =========================================================== Kartu per supplier
with tab_kartu:
    supplier_kartu = sorted(
        {str(p["Supplier ID"]) for p in produk_cabang} | {str(r["Supplier ID"]) for r in kunjungan_cabang if r.get("Supplier ID")},
        key=nama_supplier,
    )
    if not supplier_kartu:
        st.info("Belum ada kartu konsinyasi untuk cabang ini.")
    else:
        sid_k = st.selectbox("Supplier", supplier_kartu, format_func=nama_supplier, key="kons_kartu_supplier")
        milik = K.urut([r for r in kunjungan_cabang if str(r.get("Supplier ID")) == sid_k])
        pilihan = ["Semua produk"] + sorted({str(r["Produk"]) for r in milik})
        produk_k = st.selectbox("Produk", pilihan, key=f"kons_kartu_produk_{sid_k}")
        tampil = milik if produk_k == "Semua produk" else [r for r in milik if str(r["Produk"]) == produk_k]
        if not tampil:
            st.caption("Belum ada kunjungan tercatat untuk supplier ini.")
        else:
            kolom = ["Tanggal", "Produk", "Stok Lama", "Sisa", "Terjual", "Masuk", "Stok Akhir", "Bayar", "Petugas", "Status Bayar"]
            kartu = pd.DataFrame(tampil)[kolom]
            # Stok Lama kunjungan pertama tersimpan kosong (""), angka lainnya
            # angka: samakan jadi angka supaya tabelnya tidak campur teks/angka.
            for c in ("Stok Lama", "Sisa", "Terjual", "Masuk", "Stok Akhir", "Bayar"):
                kartu[c] = pd.to_numeric(kartu[c], errors="coerce")
            st.dataframe(kartu, hide_index=True, width="stretch", column_config={"Bayar": RUPIAH})
            total_bayar = sum(K.angka(r.get("Bayar")) or 0 for r in tampil)
            belum = sum(K.angka(r.get("Bayar")) or 0 for r in tampil if str(r.get("Status Bayar", "")).startswith("Belum"))
            st.markdown(
                f"Terjual **{sum(K.angka(r.get('Terjual')) or 0 for r in tampil):g}** · "
                f"bayar **{rupiah(total_bayar)}** · belum dibayar **{rupiah(belum)}**"
            )

            sesi_belum = []
            for r in reversed(milik):
                if str(r.get("Status Bayar", "")).startswith("Belum") and r["Session ID"] not in sesi_belum:
                    sesi_belum.append(r["Session ID"])
            if sesi_belum:
                st.subheader("Belum dibayar")
                for sesi in sesi_belum[:10]:
                    rows_s = [r for r in milik if r["Session ID"] == sesi]
                    with st.expander(f"{rows_s[0]['Tanggal']} · {rupiah(sum(K.angka(r.get('Bayar')) or 0 for r in rows_s))}"):
                        cara = st.radio("Dibayar dengan", K.STATUS_BAYAR[:2], horizontal=True, key=f"kons_cara_{sesi}")
                        if st.button("Tandai sudah dibayar", key=f"kons_lunas_{sesi}"):
                            with st.spinner("Menyimpan..."):
                                update_konsinyasi(sesi, [{**r, "Status Bayar": cara} for r in rows_s])
                            st.session_state.kons_pesan = f"Kunjungan {rows_s[0]['Tanggal']} ditandai {cara.lower()}."
                            st.rerun()

            terakhir = K.sesi_terakhir(kunjungan, cabang, sid_k)
            rows_t = [r for r in milik if r["Session ID"] == terakhir]
            if rows_t:
                hari_ini = K.kunci_waktu(sekarang().date().isoformat(), "")[:3] == K.kunci_waktu(rows_t[0]["Tanggal"], "")[:3]
                boleh = st.session_state.ops_authenticated or hari_ini
                with st.expander("Hapus kunjungan terakhir (salah input)"):
                    st.write(
                        f"{rows_t[0]['Tanggal']} oleh {rows_t[0].get('Petugas') or '-'}: {len(rows_t)} produk, "
                        f"bayar {rupiah(sum(K.angka(r.get('Bayar')) or 0 for r in rows_t))}."
                    )
                    st.caption("Hanya kunjungan terakhir yang bisa dihapus, supaya stok lama kunjungan berikutnya tetap benar.")
                    if not boleh:
                        st.caption("Kunjungan sebelum hari ini hanya bisa dihapus owner (login di tab Kelola).")
                    yakin = st.checkbox("Ya, hapus kunjungan ini", key=f"kons_yakin_{terakhir}", disabled=not boleh)
                    if st.button("Hapus kunjungan", key=f"kons_hapus_{terakhir}", disabled=not (boleh and yakin)):
                        with st.spinner("Menghapus..."):
                            delete_konsinyasi(terakhir)
                        st.session_state.kons_pesan = "Kunjungan terakhir dihapus."
                        st.rerun()

# =========================================================== Rekap bulanan
with tab_rekap:
    bulan_ada = {sekarang().strftime("%Y-%m")}
    for r in kunjungan_cabang:
        k = K.kunci_waktu(r.get("Tanggal"), r.get("Timestamp"))
        bulan_ada.add(f"{k[0]:04d}-{k[1]:02d}")
    bulan = st.selectbox("Bulan", sorted(bulan_ada, reverse=True), key="kons_rekap_bulan")
    rekap = K.rekap(kunjungan, cabang, bulan)
    if not rekap:
        st.caption("Belum ada kunjungan konsinyasi di bulan ini.")
    else:
        st.dataframe(
            pd.DataFrame(rekap)[["Supplier", "Kunjungan", "Terjual", "Bayar", "Sudah dibayar", "Belum dibayar"]],
            hide_index=True,
            width="stretch",
            column_config={"Bayar": RUPIAH, "Sudah dibayar": RUPIAH, "Belum dibayar": RUPIAH},
        )
        st.markdown(
            f"Total **{rupiah(sum(s['Bayar'] for s in rekap))}** · "
            f"belum dibayar **{rupiah(sum(s['Belum dibayar'] for s in rekap))}**"
        )

# =========================================================== Kelola (owner)
with tab_kelola:
    if not st.session_state.ops_authenticated:
        st.info("Bagian ini khusus owner: menambah supplier, produk titipan, dan harga titip.")
        with st.form("kons_login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary"):
                if username == AUTH_USERNAME and password == AUTH_PASSWORD:
                    st.session_state.ops_authenticated = True
                    st.rerun()
                else:
                    st.error("Username atau password salah.")
    else:
        st.subheader("Supplier")
        with st.form("kons_tambah_supplier", clear_on_submit=True):
            nama_baru = st.text_input("Nama supplier")
            hp_baru = st.text_input("No. HP")
            sistem_baru = st.text_input("Sistem bayar", placeholder="mis. tunai tiap datang / transfer mingguan")
            if st.form_submit_button("Tambah supplier"):
                nama_baru = nama_baru.strip()
                if not nama_baru:
                    st.error("Nama supplier wajib diisi.")
                elif nama_baru.lower() in {str(r.get("Nama Supplier", "")).strip().lower() for r in supplier_rows}:
                    st.error(f"Supplier {nama_baru} sudah ada.")
                else:
                    with st.spinner("Menyimpan..."):
                        tambah_konsinyasi_master(
                            "supplier",
                            {
                                "ID": f"S{uuid.uuid4().hex[:6]}",
                                "Nama Supplier": nama_baru,
                                "No HP": hp_baru.strip(),
                                "Sistem Bayar": sistem_baru.strip(),
                                "Aktif": "Ya",
                                "Dibuat": sekarang().strftime("%Y-%m-%d %H:%M:%S"),
                            },
                        )
                    st.session_state.kons_pesan = f"Supplier {nama_baru} ditambahkan."
                    st.rerun()

        if supplier_rows:
            ed_supplier = st.data_editor(
                pd.DataFrame(
                    [
                        {
                            "Nama Supplier": str(r.get("Nama Supplier", "")),
                            "No HP": str(r.get("No HP", "")),
                            "Sistem Bayar": str(r.get("Sistem Bayar", "")),
                            "Aktif": aktif(r),
                        }
                        for r in supplier_rows
                    ]
                ),
                hide_index=True,
                width="stretch",
                num_rows="fixed",
                key=f"kons_ed_supplier_{versi}",
                column_config={"Aktif": st.column_config.CheckboxColumn(help="Matikan kalau supplier berhenti menitip. Riwayatnya tetap ada.")},
            )
            if st.button("Simpan perubahan supplier"):
                ubah = {
                    str(r["ID"]): {
                        "Nama Supplier": str(e["Nama Supplier"]).strip() or r.get("Nama Supplier", ""),
                        "No HP": str(e["No HP"]).strip(),
                        "Sistem Bayar": str(e["Sistem Bayar"]).strip(),
                        "Aktif": "Ya" if e["Aktif"] else "Tidak",
                    }
                    for r, (_, e) in zip(supplier_rows, ed_supplier.iterrows())
                }
                # Tulis SEMUA baris tab (termasuk yang tanpa ID) dalam urutan aslinya:
                # simpan_konsinyasi_master menimpa dari A1, jadi baris yang terlewat
                # akan tergeser dan tersisa dobel di bawah.
                semua = [{**r, **ubah.get(str(r.get("ID")), {})} for r in data["master"]["supplier"]]
                with st.spinner("Menyimpan..."):
                    simpan_konsinyasi_master("supplier", semua)
                st.session_state.kons_pesan = "Perubahan supplier tersimpan."
                st.session_state.kons_versi += 1
                st.rerun()

        st.subheader(f"Produk titipan {cabang}")
        supplier_dipakai = [str(r["ID"]) for r in supplier_rows if aktif(r)]
        if not supplier_dipakai:
            st.caption("Tambahkan supplier dulu.")
        else:
            with st.form("kons_tambah_produk", clear_on_submit=True):
                sup_p = st.selectbox("Supplier", supplier_dipakai, format_func=nama_supplier)
                nama_p = st.text_input("Nama produk")
                c1, c2 = st.columns(2)
                harga_titip = c1.number_input("Harga titip (Rp)", min_value=0, step=500)
                harga_jual = c2.number_input("Harga jual di Airin (Rp, opsional)", min_value=0, step=500)
                if st.form_submit_button("Tambah produk"):
                    nama_p = nama_p.strip()
                    sudah = {
                        (str(p.get("Supplier ID")), str(p.get("Nama Produk", "")).strip().lower()) for p in produk_cabang
                    }
                    if not nama_p or not harga_titip:
                        st.error("Nama produk dan harga titip wajib diisi.")
                    elif (sup_p, nama_p.lower()) in sudah:
                        st.error(f"{nama_p} dari {nama_supplier(sup_p)} sudah ada di {cabang}.")
                    else:
                        with st.spinner("Menyimpan..."):
                            tambah_konsinyasi_master(
                                "produk",
                                {
                                    "ID": f"P{uuid.uuid4().hex[:6]}",
                                    "Supplier ID": sup_p,
                                    "Cabang": cabang,
                                    "Nama Produk": nama_p,
                                    "Harga Titip": harga_titip,
                                    "Harga Jual": harga_jual or "",
                                    "Aktif": "Ya",
                                    "Dibuat": sekarang().strftime("%Y-%m-%d %H:%M:%S"),
                                },
                            )
                        st.session_state.kons_pesan = f"Produk {nama_p} ({cabang}) ditambahkan."
                        st.rerun()

        if produk_cabang:
            ed_produk = st.data_editor(
                pd.DataFrame(
                    [
                        {
                            "Supplier": nama_supplier(p.get("Supplier ID")),
                            "Nama Produk": str(p.get("Nama Produk", "")),
                            "Harga Titip": K.angka(p.get("Harga Titip")) or 0.0,
                            "Harga Jual": K.angka(p.get("Harga Jual")),
                            "Aktif": aktif(p),
                        }
                        for p in produk_cabang
                    ]
                ),
                hide_index=True,
                width="stretch",
                num_rows="fixed",
                key=f"kons_ed_produk_{cabang}_{versi}",
                column_config={
                    "Supplier": st.column_config.TextColumn(disabled=True),
                    "Harga Titip": st.column_config.NumberColumn(format="Rp %,d", min_value=0, help="Harga baru berlaku untuk kunjungan berikutnya."),
                    "Harga Jual": st.column_config.NumberColumn(format="Rp %,d", min_value=0),
                    "Aktif": st.column_config.CheckboxColumn(help="Matikan kalau produk tidak dititipkan lagi."),
                },
            )
            if st.button("Simpan perubahan produk"):
                ubah = {
                    str(p["ID"]): {
                        "Nama Produk": str(e["Nama Produk"]).strip() or p.get("Nama Produk", ""),
                        "Harga Titip": K.angka(e["Harga Titip"]) or 0,
                        "Harga Jual": "" if K.angka(e["Harga Jual"]) is None else K.angka(e["Harga Jual"]),
                        "Aktif": "Ya" if e["Aktif"] else "Tidak",
                    }
                    for p, (_, e) in zip(produk_cabang, ed_produk.iterrows())
                }
                semua = [{**p, **ubah.get(str(p.get("ID")), {})} for p in data["master"]["produk"]]
                with st.spinner("Menyimpan..."):
                    simpan_konsinyasi_master("produk", semua)
                st.session_state.kons_pesan = "Perubahan produk tersimpan."
                st.session_state.kons_versi += 1
                st.rerun()

        if st.button("Logout owner"):
            st.session_state.ops_authenticated = False
            st.rerun()
