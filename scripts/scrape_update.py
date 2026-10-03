"""
Scrape ulasan terbaru dari 25 RS via Apify, klasifikasi sentimen via API SVM
(Render), lalu gabungkan ke docs/data/reviews.json (cumulative, tidak menimpa
data lama -- ulasan yang sudah pernah diproses tidak di-scrape ulang ke API
SVM supaya hemat kuota/waktu).

Dijalankan otomatis oleh GitHub Actions (lihat .github/workflows/update-data.yml),
bisa juga dijalankan manual lokal untuk tes:
    pip install apify-client requests
    export APIFY_TOKEN=xxxx          (Linux/Mac)
    $env:APIFY_TOKEN="xxxx"          (PowerShell)
    python scripts/scrape_update.py
"""

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from apify_client import ApifyClient

# ============================================================
# KONFIGURASI
# ============================================================
API_TOKEN = os.environ["APIFY_TOKEN"]  # WAJIB diset lewat GitHub Secrets, jangan di-hardcode
SVM_API_URL = "https://sentimen-api.onrender.com/predict"
SVM_WAKEUP_URL = "https://sentimen-api.onrender.com/"

OUTPUT_FILE = Path("docs/data/reviews.json")

MAX_REVIEWS_PER_RS = 20   # per run -- cukup kecil karena jalan berkala, bukan full-scrape tiap kali
REQUEST_TIMEOUT = 90      # detik -- Render free tier bisa cold-start lama

daftar_rs_url = [
    "https://www.google.com/maps/search/?api=1&query=Rumah+Sakit+Umum+Bunda+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=Hermina+Hospital+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSUD+Ajibarang+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=RS+TK+III+Wijayakusuma+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Dadi+Keluarga+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Siaga+Medika+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=RS+PKU+Muhammadiyah+Amanah+Sumpiuh",
    "https://www.google.com/maps/search/?api=1&query=RSIA+Bunda+Arif+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Ananda+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=Rumah+Sakit+Islam+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Sinar+Kasih+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Medika+Lestari+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=RSU+An+Nimah+Wangon+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=RSU+Santa+Elisabeth+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=Rumah+Sakit+Orthopaedi+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSUD+Prof+Dr+Margono+Soekarjo+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSGMP+UNSOED+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSUD+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=Rumah+Sakit+JIH+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RS+Khusus+Mata+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSU+Wiradadi+Husada+Banyumas",
    "https://www.google.com/maps/search/?api=1&query=RSKB+Mitra+Ariva+Ajibarang",
    "https://www.google.com/maps/search/?api=1&query=RSU+Hidayah+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RSIA+Budhi+Asih+Purwokerto",
    "https://www.google.com/maps/search/?api=1&query=RS+Jatiwinangun+Purwokerto",
]


def get_field(obj, key: str):
    """Ambil field dari hasil Apify, kompatibel baik obj berupa dict (versi lama
    apify-client) maupun object dengan atribut snake_case (versi baru)."""
    if isinstance(obj, dict):
        return obj.get(key)
    snake_key = "".join(f"_{c.lower()}" if c.isupper() else c for c in key).lstrip("_")
    if hasattr(obj, snake_key):
        return getattr(obj, snake_key)
    return getattr(obj, key, None)


def review_id(row: dict) -> str:
    """ID unik per ulasan, dipakai untuk deteksi duplikat antar-run."""
    raw = f"{row['Nama RS']}|{row['Username']}|{row['Waktu Ulasan']}|{row['Isi Ulasan']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return []


def wake_up_svm_api():
    """Render free tier sleep kalau idle -- bangunkan dulu sebelum mulai batch."""
    print("Membangunkan API SVM (Render free tier)...")
    for attempt in range(3):
        try:
            requests.get(SVM_WAKEUP_URL, timeout=REQUEST_TIMEOUT)
            print("API SVM sudah bangun.")
            return
        except requests.exceptions.RequestException as e:
            print(f"  percobaan {attempt + 1} gagal: {e}, retry...")
            time.sleep(5)
    print("  Peringatan: API mungkin belum sepenuhnya siap, lanjut saja.")


def classify_sentiment(text: str) -> dict:
    """Panggil API SVM, kembalikan dict kosong kalau gagal (ditandai butuh retry)."""
    try:
        resp = requests.post(SVM_API_URL, json={"text": text}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"  Gagal klasifikasi: {e}")
        return {}


def main():
    existing = load_existing()
    existing_ids = {r["id"] for r in existing}
    print(f"Data lama: {len(existing)} ulasan (ID unik: {len(existing_ids)})")

    client = ApifyClient(API_TOKEN)
    run_input = {
        "startUrls": [{"url": u} for u in daftar_rs_url],
        "language": "id",
        "countryCode": "id",   # FIX: batasi pencarian ke Indonesia -- tanpa ini,
                               # Actor bisa salah menemukan tempat di luar negeri
                               # yang kebetulan namanya mirip (terbukti dari log run
                               # sebelumnya: beberapa RS ketemu di koordinat Amerika)
        "maxReviews": MAX_REVIEWS_PER_RS,
        "reviewsSort": "newest",
        "maxImages": 0,
        "maxQuestions": 0,
    }

    print(f"Menjalankan Apify actor untuk {len(daftar_rs_url)} RS...")
    run = client.actor("compass/crawler-google-places").call(run_input=run_input)
    dataset_id = get_field(run, "defaultDatasetId")
    print(f"Selesai scraping. Dataset: {dataset_id}")

    # --- Flatten hasil scraping ---
    # iterate_items() dari dataset client SELALU mengembalikan dict biasa (hasil JSON API),
    # jadi .get() di bagian ini sudah aman apa adanya -- cuma objek `run` di atas yang perlu get_field().
    scraped_rows = []
    for place in client.dataset(dataset_id).iterate_items():
        nama_rs = place.get("title")
        lokasi = place.get("location") or {}
        lat = lokasi.get("lat") if lokasi else place.get("latitude")
        lng = lokasi.get("lng") if lokasi else place.get("longitude")

        for r in place.get("reviews", []):
            row = {
                "Nama RS": nama_rs,
                "Username": r.get("name"),
                "Rating": r.get("stars"),
                "Waktu Ulasan": r.get("publishedAtDate"),
                "Lokasi Tempat": place.get("address"),
                "Latitude": lat,
                "Longitude": lng,
                "Isi Ulasan": r.get("text"),
            }
            if not row["Isi Ulasan"] or not str(row["Isi Ulasan"]).strip():
                continue
            row["id"] = review_id(row)
            scraped_rows.append(row)

    # FIX: jaring pengaman -- buang baris yang koordinatnya di luar Indonesia
    # (bounding box kasar), berjaga-jaga kalau parameter countryCode di atas
    # tidak sepenuhnya dihormati oleh Actor untuk sebagian hasil pencarian.
    INDONESIA_BBOX = {"lat_min": -11, "lat_max": 6, "lng_min": 95, "lng_max": 141}
    before_filter = len(scraped_rows)
    scraped_rows = [
        r for r in scraped_rows
        if r["Latitude"] is not None and r["Longitude"] is not None
        and INDONESIA_BBOX["lat_min"] <= r["Latitude"] <= INDONESIA_BBOX["lat_max"]
        and INDONESIA_BBOX["lng_min"] <= r["Longitude"] <= INDONESIA_BBOX["lng_max"]
    ]
    dropped = before_filter - len(scraped_rows)
    if dropped:
        print(f"⚠️  {dropped} ulasan dibuang karena koordinatnya di luar Indonesia "
              f"(kemungkinan Actor salah menemukan tempat di luar negeri)")

    print(f"Total ulasan ter-scrape (termasuk yang sudah pernah diproses): {len(scraped_rows)}")

    # --- Filter yang BENAR-BENAR baru saja ---
    new_rows = [r for r in scraped_rows if r["id"] not in existing_ids]
    print(f"Ulasan BARU yang perlu diklasifikasi: {len(new_rows)}")

    if not new_rows:
        print("Tidak ada ulasan baru. Selesai, tidak ada perubahan file.")
        return

    # --- Klasifikasi sentimen untuk ulasan baru saja ---
    wake_up_svm_api()
    processed_new = []
    for i, row in enumerate(new_rows, 1):
        print(f"  [{i}/{len(new_rows)}] Klasifikasi: {row['Nama RS'][:30]}...")
        result = classify_sentiment(row["Isi Ulasan"])
        row["Sentimen_Prediksi"] = result.get("sentimen", "Netral")  # fallback aman kalau API gagal
        row["Confidence"] = result.get("confidence")
        row["Processed_At"] = datetime.utcnow().isoformat()
        processed_new.append(row)
        time.sleep(0.5)  # jaga-jaga rate limit

    # --- Gabungkan dengan data lama, simpan ---
    combined = existing + processed_new
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ Selesai. Total ulasan sekarang: {len(combined)} "
          f"(+{len(processed_new)} baru) -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()