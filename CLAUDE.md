# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit app for Airin Fresh Mart, a 2-branch grocery/vegetable store (**SULFAT** and **PIRANHA** — treat these as independent businesses with separate Olshopin storefronts, separate stock, separate everything unless a feature explicitly says otherwise). Core purpose: track daily "sortir" (spoiled/discarded produce — the store's main waste metric), reconcile cash per shift, track operational expenses, and forecast restock/prep quantities from sales history.

## Commands

- Install deps: `pip install -r requirements.txt`
- Run the app: `streamlit run app.py` (needs Google Sheets credentials — see below)
- One-time new-spreadsheet bootstrap: `python3 setup_gsheet.py` (creates the base tabs; see caveat under Data model)
- Re-sync `PenjualanBulanan` from raw Kasir Pintar exports: `python3 backfill_penjualan.py` (add `--dry-run` to preview, `--cabang SULFAT|PIRANHA` to limit to one branch)
- Deploy target is Railway (see `Procfile`); no separate build step.
- Tests: only the consignment math has them. Run `python3 tests/test_konsinyasi.py`, or `pytest tests/` if pytest is installed; neither needs Google Sheets. No linter or type checker is configured.

## Credentials

`gsheet_client.py` resolves Google Sheets access in this priority order:
1. Streamlit secrets (`.streamlit/secrets.toml`, keys `gcp_service_account` + `spreadsheet_id`) — Streamlit Cloud.
2. Env vars `GCP_SERVICE_ACCOUNT_JSON` (the full service-account JSON as a string) + `SPREADSHEET_ID` — Railway.
3. Local files `service_account.json` + `spreadsheet_id.txt` — local dev.

All three are gitignored. For local dev, drop the two files in the repo root.

## Architecture

### Entry point & pages

`app.py` registers every page via `st.navigation()` pointing at `views/*.py`. Each view is a self-contained script (Streamlit's multipage model — Streamlit re-executes only the selected page top to bottom on each interaction, there's no shared router/class hierarchy). Read the docstring at the top of a view before changing it; most encode a non-obvious business rule (e.g. the cash-reconciliation formula in `laporan_transaksi_harian.py`, the login gate in `pengeluaran_operasional.py`).

**Page layout is set once per run, in `app.py`.** `HALAMAN_LEBAR` lists the pages that get `wide`; every other page is `centered`. Never call `st.set_page_config(layout=...)` inside a page. With two layout calls in one run, Streamlit's frontend sometimes drops one, and the page flips between wide and centered on clicks. This happened on Kartu Konsinyasi on 2026-11-13.

**Widget state does not survive a page switch.**
- Streamlit drops the state of every widget that isn't rendered in a run. So when someone leaves a page and comes back, its selectboxes fall back to the first option: alphabetically, that is cabang `PIRANHA` and nama `Adi`.
- Values kept in plain `session_state` keys survive, such as the amounts in Laporan Transaksi Harian.
- Together, this saved two SULFAT reports as "Adi · PIRANHA" on 2026-11-09 without anyone noticing.

Every page that writes a Cabang, Nama or Tanggal therefore follows two rules:
- It uses `ingat_pilihan.selectbox` and `ingat_pilihan.date_input`, which put the last value back.
- Cabang and Nama start with no selection (`index=None`), and Simpan stays disabled until both are chosen. Nothing gets saved under a default the user never picked.

### Data layer: one Google Sheet, several access patterns

`gsheet_client.py` owns the spreadsheet connection (`get_spreadsheet()`, cached via `st.cache_resource`) and generic CRUD for the four high-volume "transactional" tabs: `Sortir`, `Laporan Harian`, `Pengeluaran Operasional`, `Konsinyasi`.

- Each of those four **auto-splits by month**: writes always target `<Base>_MM_YYYY` (created on first write of a new month), while reads merge the legacy un-suffixed sheet (if one still exists from before this split existed) with every monthly sheet, chronologically (`_data_sheets`). This keeps any single sheet from growing unbounded.
- Deletes are physical (`deleteDimension`), not soft — protected by a single-cell lock in the `_Lock` tab (`_acquire_lock`/`_release_lock`) because deleting shifts row indices, and two concurrent deletes racing would otherwise corrupt each other. Rows are matched and removed by `Session ID`.
- Bulk reads batch across every monthly sheet in one `values.batchGet` call (`_batch_get_records`) rather than one request per sheet, so the request count stays flat as monthly sheets accumulate.
- `Produk`, `Cabang`, `Karyawan`, `ProdukMapping`, `PenjualanBulanan`, `Konsinyasi Supplier`, `Konsinyasi Produk`, `_Lock` are **not** month-split and are read/written directly by whichever module owns them.
- **Read quota.** Every app session *and* every local script share one service account, and Google caps it at ~60 read requests per minute. Going over that crashed pages with a 429 in production on 2026-11-08.
  - `_RetryHTTPClient` waits and retries 429s (and 5xx on GETs) for about a minute instead of crashing. `LOCK_TIMEOUT_SECONDS` must stay above that retry budget.
  - The worksheet list is cached (`_worksheets`, cleared when the app creates a tab).
  - Produk/Cabang/Karyawan come from one batched read (`_load_master`, 60 s TTL; call `clear_master_cache()` after writing to them).
  - `sales_history.load_all` is cached for 10 minutes.
  - Keep new read paths batched and cached: an uncached read in a page body runs on every click.

### Master data tabs

- **Produk** — a *curated* subset of products the store actively manages for sortir/pricing, **not** the full Olshopin catalog (see `olshopin_sync.py`). Live columns: `nama_barang_edit`, `harga_jual_edit`, `harga_beli_edit`, `tipe` (`kg`/`satuan`, blank = auto-detect from name), `nama_olshopin` (manual override for catalog matching). `setup_gsheet.py`'s `HEADERS["Produk"]` reflects an older 3-column schema and is stale — don't use it as a reference for the current shape.
- **Cabang** — the branch list (`SULFAT`, `PIRANHA`); every branch selector in the app reads from here.
- **ProdukMapping** — manual `nama_barang_edit` → `nama_olshopin` overrides for products whose names don't fuzzy-match the live catalog automatically.
- **PenjualanBulanan** — aggregated monthly sales history; owned entirely by `sales_history.py` (below).
- **Konsinyasi Supplier** / **Konsinyasi Produk** — consignment suppliers and their products, per branch, with `Harga Titip`. These are created by the app on first save and maintained from the Kartu Konsinyasi page (below), not by hand.

### Olshopin integration (`olshopin_sync.py`)

Each branch has its own independent Olshopin storefront (`CABANG_TID`) — never merge their catalogs or assume a product/price is shared. `fetch_catalog(tid)` scrapes the `window.__SHOP_HOME__` JSON embedded in the storefront's HTML (there is no official API). **`harga_beli` is never read from anywhere** — it is always derived as `harga_jual` minus a fixed markdown (`POTONG_KG` = 4000, `POTONG_SATUAN` = 500), floored at 0. This is an *estimate*, not a real cost; see the note on `sales_upload.py` below for where the real cost actually lives. Name matching to the live catalog falls back in this order: manual `ProdukMapping` entry → normalized exact match → normalized match with the `kg` suffix stripped (`_strip_kg`).

### kg vs. satuan detection

A product counts as "kg" if the `tipe` column says so explicitly, otherwise if its name matches `\bkg\b` (`olshopin_sync.is_kg` / `resolve_kg`). This one rule is reused for price-sync, sortir classification, and both forecasting features below — if a new feature needs the same distinction, reuse it rather than reimplementing name-sniffing.

### Sales history & forecasting (`sales_history.py`)

`PenjualanBulanan` stores one row per `(Cabang, Bulan, Produk, Periode)` with total `Qty` and the day-count that month's source data covers. `Periode` is `Total` / `Pagi` (before noon) / `Siang` (noon+); it was added after the original schema and is deliberately the **last** column so pre-existing rows (which predate it) still parse correctly as `Total` (see the comment above `HEADER`). Uploading a `(cabang, bulan, periode)` combination again **replaces** it (`replace_month`), it never appends — re-uploading a corrected export is always safe.

The sheet is auto-seeded from `sales_history_seed.json` (pre-aggregated from `data-sulfat/`/`data-piranha/`) the *first time it's ever created* — this seeding does not re-run once the sheet exists, so an updated seed file never propagates to an already-existing sheet automatically. This has caused real drift in production (a branch silently missing months of history) — `backfill_penjualan.py` exists specifically to force a re-sync from the raw exports when that happens; reach for it (or extend it) rather than re-seeding by hand.

`trend_avg_qty()` is the forecasting primitive both Jadwal Sayur and Proyeksi Stok Habis build on: it returns a flat average (qty/day) alongside a trend-adjusted value (simple linear regression over monthly qty/day, evaluated at the *last observed* month — not extrapolated forward, deliberately conservative) so a branch with real momentum isn't dragged toward a stale flat average. Falls back to the flat average below `min_bulan_tren` (default 3) months of history for a product.

### Buffer & rounding conventions (shared by Jadwal Sayur and Proyeksi Stok Habis)

Both features take `trend_avg_qty`'s trend value, add a safety buffer %, then round: kg-based quantities stay decimal (a fractional kg is real), satuan quantities round **up** (`math.ceil`) since "3.6 pcs" isn't actionable and over-preparing beats running out. Buffer % is hardcoded per `(cabang, tipe)` in each view's `DEFAULT_BUFFER` dict (`views/jadwal_sayur.py`, `views/update_harga.py`) — currently SULFAT 40%/20% and PIRANHA 50%/20% (kg/satuan). These came from a walk-forward backtest against real transaction data (hold out recent months, compare predicted vs. actual, find the buffer where accuracy stops improving cheaply), not from guessing — re-derive them the same way if they ever need revisiting rather than eyeballing new values.

### Kasir Pintar transaction data (`sales_upload.py`)

`parse_transaksi()` reads the `TransaksiBarang` sheet from a Kasir Pintar `.xls` export — an old BIFF/OLE2 format that must be opened with `xlrd(ignore_workbook_corruption=True)`; `pandas.read_excel` fails on these files. The returned `HargaBeli`/`HargaJual` are the **real** prices recorded at sale time — this is the only source of true cost/margin in the whole app (as opposed to `olshopin_sync`'s fixed-markdown estimate above). `views/laporan_sortir.py` compares this against sortir records for real waste-vs-margin analysis; `views/update_harga.py`'s upload flow aggregates it into `PenjualanBulanan`.

### Kartu Konsinyasi (`views/kartu_konsinyasi.py`, `konsinyasi.py`)

The page replaces the paper consignment cards for goods suppliers leave on consignment (titipan). The math lives in `konsinyasi.py` (pure functions, no Streamlit/Sheets). The page file is deliberately *not* named `konsinyasi.py`, so that `import konsinyasi` can never resolve to the page.

**How a visit is recorded.** Staff count what is left on the shelf **before** the new goods go up (`Sisa`), then record the new goods (`Masuk`). The page computes:
- `Terjual = Stok lama − Sisa`
- `Bayar = Terjual × Harga titip`
- `Stok akhir = Sisa + Masuk`

`Stok lama` is the previous visit's `Stok akhir` (`stok_terakhir`). This matches the paper formula `Terjual = (Stok lama + Masuk) − Sisa` when the paper's `Sisa` was counted *after* restocking, i.e. it equals `Stok akhir` here. A product's first visit has no `Stok lama`: it sells 0 and its count becomes the opening stock.

**Unpaid bills pile up.** Some suppliers prefer to collect only after several visits. "Sisa Tagihan" is the running total owed to a supplier: it is a payable for Airin (a receivable, *piutang*, for the supplier). It is always computed from the visit rows, never stored. The functions are `sisa_tagihan_berjalan`, `belum_dibayar` and `tagihan_per_supplier`. Zero-amount visits, such as a product's first visit, never count as a bill.

**Rules that are easy to break:**
- **Delete only the latest visit.** Each row stores its own `Stok Lama` snapshot, so deleting a middle visit breaks every later one. Staff can delete only today's visit; older ones need owner login.
- **Paying edits cells in place.** `bayar_konsinyasi` sets `Status Bayar` and `Tanggal Bayar` on the rows of the chosen visits; it does not delete and re-append them. Several accumulated visits can therefore be settled at once, with row order and `Timestamp` unchanged. It still holds the `_Lock`, because a concurrent delete shifts row numbers.
- **New log columns go at the end only.** `Tanggal Bayar` was added after launch as the last column. Monthly tabs created earlier have 19 columns, and `_pastikan_header_konsinyasi` extends their header in place the first time the app saves or pays into them. Add any future column the same way: at the end, never in the middle.
- **Master edits overwrite from A1** (`simpan_konsinyasi_master`), with no `clear()`. Master rows are never deleted; switch `Aktif` to `Tidak` instead. The page writes back *every* row in its original order, including rows without an ID, because skipping a row would shift the rest and leave duplicates.
- **IDs carry a letter prefix.** Supplier IDs start with `S`, product IDs with `P`, because `numericise_all` turns IDs like `1e5…` into floats.
- **Supplier rows stay text.** They are written with `RAW` and read back without numericise, so a phone number like `0812…` keeps its leading zero.

### Auth

Two independent session-based gates (`st.session_state`, no real user accounts):
- `ops_authenticated` (env vars `OPS_USERNAME`/`OPS_PASSWORD`, default `oki`/`oki`) gates **Update Harga**, **Pengeluaran Operasional**, **Laporan Sortir**, **Laporan Operasional** — owner-only, financial data.
- **Input Sortir**, **Laporan Transaksi Harian**, **Jadwal Sayur Pagi/Siang** are open to all staff, no login.
- **Kartu Konsinyasi** is open to all staff for recording visits. Owner login is needed for its "Kelola supplier & produk" tab, because `Harga Titip` decides what suppliers get paid, and for deleting a visit older than today.

### One-off scripts (not part of the running app)

- `setup_gsheet.py` — bootstraps a brand-new spreadsheet. Its `Produk` schema is stale (see Data model above); don't treat it as current documentation.
- `backfill_penjualan.py` — re-derives `PenjualanBulanan` from the raw `data-sulfat/`/`data-piranha/` `.xls` folders. Writes via **one** `clear()` + batched `append_rows()` calls, not a loop of `sales_history.replace_month()` — an earlier version looped `replace_month()` per `(cabang, bulan, periode)`, and each call's internal `clear()`+rewrite of the *entire* sheet meant a dropped connection mid-call actually wiped `PenjualanBulanan` in production once. If `PenjualanBulanan` ever needs a full re-sync again, extend this script's batched pattern rather than reintroducing a `replace_month()` loop.
