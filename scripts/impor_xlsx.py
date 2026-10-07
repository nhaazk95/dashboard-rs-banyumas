import os, sys
import pandas as pd
from datetime import datetime

os.environ.setdefault("APIFY_TOKEN", "dummy")   # tidak dipakai di skrip ini
from scrape_update import (OUTPUT_FILE, load_existing, review_id,
                           wake_up_svm_api, classify_sentiment)
import json, time

XLSX = "Hasil_Prediksi_RS_2026.xlsx"

KANDIDAT = {
    "Nama RS":      ["nama rs", "nama_rs", "title", "rumah sakit"],
    "Username":     ["username", "name", "reviewer", "nama pengguna"],
    "Rating":       ["rating", "stars", "bintang"],
    "Waktu Ulasan": ["waktu ulasan", "publishedatdate", "tanggal", "waktu", "date"],
    "Lokasi Tempat":["lokasi tempat", "lokasi", "address", "alamat"],
    "Latitude":     ["latitude", "lat"],
    "Longitude":    ["longitude", "lng", "lon", "long"],
    "Isi Ulasan":   ["isi ulasan", "text", "ulasan", "review"],
}

df = pd.read_excel(XLSX)
print("Kolom di xlsx:", df.columns.tolist())
low = {str(c).strip().lower(): c for c in df.columns}

peta = {}
for tujuan, opsi in KANDIDAT.items():
    ketemu = next((low[o] for o in opsi if o in low), None)
    if ketemu is None and tujuan in ("Nama RS", "Waktu Ulasan", "Isi Ulasan"):
        sys.exit(f"Kolom wajib '{tujuan}' tidak ditemukan. Kirim daftar kolom di atas.")
    peta[tujuan] = ketemu

norm = lambda s: " ".join(str(s).lower().split())
existing = load_existing()
ids = {r["id"] for r in existing}
kunci = {(norm(r["Nama RS"]), norm(r["Isi Ulasan"]), str(r["Waktu Ulasan"])[:10]) for r in existing}

baru, lewat = [], 0
for _, x in df.iterrows():
    isi = x[peta["Isi Ulasan"]]
    if pd.isna(isi) or not str(isi).strip():
        continue
    t = pd.to_datetime(x[peta["Waktu Ulasan"]], utc=True, errors="coerce")
    if pd.isna(t):
        continue
    row = {k: (None if c is None or pd.isna(x[c]) else x[c]) for k, c in peta.items()}
    row["Waktu Ulasan"] = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    row["Isi Ulasan"] = str(isi)
    row["id"] = review_id(row)
    k = (norm(row["Nama RS"]), norm(row["Isi Ulasan"]), row["Waktu Ulasan"][:10])
    if row["id"] in ids or k in kunci:
        lewat += 1
        continue
    ids.add(row["id"]); kunci.add(k)
    baru.append(row)

print(f"Dari xlsx: {len(df)} baris | sudah ada: {lewat} | baru: {len(baru)}")
if baru:
    tgl = sorted(r["Waktu Ulasan"][:10] for r in baru)
    print(f"Rentang tanggal data baru: {tgl[0]} s/d {tgl[-1]}")
    nama_json = {r["Nama RS"] for r in existing}
    asing = sorted({r["Nama RS"] for r in baru} - nama_json)
    if asing:
        print("PERINGATAN, nama RS di xlsx tidak ada di reviews.json:", asing)

wake_up_svm_api()
selesai, gagal = [], 0
for i, row in enumerate(baru, 1):
    print(f"  [{i}/{len(baru)}] {str(row['Nama RS'])[:30]}")
    res = classify_sentiment(row["Isi Ulasan"])
    if not res or "sentimen" not in res:
        gagal += 1
        continue
    row["Sentimen_Prediksi"] = res["sentimen"]
    row["Confidence"] = res.get("confidence")
    row["Teks_Bersih"] = res.get("clean_text")
    row["Processed_At"] = datetime.utcnow().isoformat()
    selesai.append(row)
    time.sleep(0.5)

gabung = existing + selesai
OUTPUT_FILE.write_text(json.dumps(gabung, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Selesai. Ditambahkan {len(selesai)} (gagal klasifikasi {gagal}). Total sekarang: {len(gabung)}")