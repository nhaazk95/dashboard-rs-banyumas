import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("APIFY_TOKEN", "dummy")
sys.path.insert(0, "scripts")
import scrape_update as s

PATH = s.OUTPUT_FILE   # docs/data/reviews.json (jalankan dari root repo)


def baca():
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else []


def tulis(rows):
    PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def tanpa_dummy(rows):
    return [r for r in rows if not r.get("Dummy")]


# --- Hapus semua baris dummy ---
if "--hapus" in sys.argv:
    rows = baca()
    bersih = tanpa_dummy(rows)
    tulis(bersih)
    print(f"Dihapus {len(rows) - len(bersih)} baris dummy. Total sekarang: {len(bersih)}")
    sys.exit()


def iso(hari_lalu):
    t = datetime.utcnow() - timedelta(days=hari_lalu)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


LOK = {   # koordinat palsu di sekitar Purwokerto supaya marker muncul di peta
    "RS Dummy A": (-7.4300, 109.2300),
    "RS Dummy B": (-7.4100, 109.2600),
    "RS Dummy C": (-7.4450, 109.2100),
}

DATA = [
    ("RS Dummy A", 1, 1,  "Pelayanan lambat banget, nunggu obat 3 jam, petugas judes", "Negatif"),
    ("RS Dummy A", 2, 2,  "Dokternya kasar dan tidak mau menjelaskan, kecewa sekali", "Negatif"),
    ("RS Dummy B", 1, 5,  "IGD antre lama, pasien dibiarkan menunggu tanpa kejelasan", "Negatif"),
    ("RS Dummy C", 1, 60, "Ulasan negatif lama, tidak boleh ikut dikirim email", "Negatif"),
    ("RS Dummy A", 5, 1,  "Pelayanan ramah, dokter dan perawat baik sekali", "Positif"),
    ("RS Dummy B", 3, 3,  "Sudah cukup", "Netral"),
]

dummy = []
for i, (rs, rating, hari, teks, label) in enumerate(DATA, 1):
    lat, lng = LOK[rs]
    dummy.append({
        "Nama RS": rs, "Username": f"Pengguna Uji {i}", "Rating": rating,
        "Waktu Ulasan": iso(hari), "Lokasi Tempat": "Purwokerto (dummy)",
        "Latitude": lat, "Longitude": lng, "Isi Ulasan": teks,
        "id": f"dummy-{i}", "Dummy": True,
        "Sentimen_Prediksi": label, "Confidence": None, "Teks_Bersih": None,
        "Processed_At": datetime.utcnow().isoformat(), "_harapan": label,
        "Notified": False,
    })

# Label dari model SVM asli (opsional)
if "--api" in sys.argv:
    s.wake_up_svm_api()
    for r in dummy:
        res = s.classify_sentiment(r["Isi Ulasan"])
        if res.get("sentimen"):
            r["Sentimen_Prediksi"] = res["sentimen"]
            r["Confidence"] = res.get("confidence")
            r["Teks_Bersih"] = res.get("clean_text")

print("Hasil label:")
for r in dummy:
    print(f"  harapan={r['_harapan']:8} | prediksi={r['Sentimen_Prediksi']:8} | {r['Isi Ulasan'][:50]}")
for r in dummy:
    r.pop("_harapan")

# Masukkan ke reviews.json (dummy lama diganti, data asli tidak disentuh)
asli = tanpa_dummy(baca())
tulis(asli + dummy)
print(f"\nreviews.json: {len(asli)} data asli + {len(dummy)} dummy = {len(asli) + len(dummy)}")

print("\nSelesai. Dummy ada di reviews.json dengan Notified=False.")
print("Commit + push, lalu jalankan workflow (Actions, Run workflow) untuk memicu email.")