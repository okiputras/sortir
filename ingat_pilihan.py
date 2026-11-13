"""
Isian form (Cabang, Nama, Tanggal) yang tetap sama setelah pengguna membuka
halaman lain lalu kembali.

Streamlit menghapus state widget yang tidak tampil dalam satu run, termasuk
saat pindah halaman. Waktu kembali, selectbox jatuh ke opsi pertama (urut
abjad: cabang PIRANHA, nama Adi) dan tanggal ke nilai awalnya, padahal angka
yang sudah diketik masih ada (disimpan di kunci biasa, lihat rupiah_input di
Laporan Transaksi Harian). Laporan pun tersimpan atas nama, cabang, dan
tanggal yang salah tanpa disadari: 9 Nov 2026 dua laporan SULFAT tercatat
"Adi · PIRANHA".

Di sini nilai terakhir tiap widget disalin ke kunci cadangan biasa (yang
tidak ikut dihapus) lalu dipasang lagi sebelum widget dibuat ulang.
"""

import streamlit as st


def _cadangan(key: str) -> str:
    return f"_ingat_{key}"


def selectbox(label: str, options: list, key: str, **kwargs):
    """st.selectbox yang pilihannya bertahan setelah pindah halaman. Pilihan
    yang sudah tidak ada di `options` (mis. karyawan dihapus) tidak dipasang
    lagi."""
    cadangan = _cadangan(key)
    if key not in st.session_state and st.session_state.get(cadangan) in options:
        st.session_state[key] = st.session_state[cadangan]
    nilai = st.selectbox(label, options, key=key, **kwargs)
    st.session_state[cadangan] = nilai
    return nilai


def date_input(label: str, key: str, nilai_awal, **kwargs):
    """st.date_input yang tanggalnya bertahan setelah pindah halaman.
    `nilai_awal` hanya dipakai saat `key` dibuat pertama kali (mis. sesudah
    form direset atau masuk mode edit, yang membuat key baru)."""
    cadangan = _cadangan(key)
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(cadangan, nilai_awal)
    nilai = st.date_input(label, key=key, **kwargs)
    st.session_state[cadangan] = nilai
    return nilai
