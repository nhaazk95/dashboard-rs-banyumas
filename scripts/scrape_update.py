import hashlib
import json
import os
import time
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import requests
from apify_client import ApifyClient
from apify_client.errors import ApifyApiError


# ============================================================
# KONFIGURASI
# ============================================================
API_TOKEN = os.environ["APIFY_TOKEN"]  
SVM_API_URL = "https://sentimen-api.onrender.com/predict"
SVM_WAKEUP_URL = "https://sentimen-api.onrender.com/"

OUTPUT_FILE = Path("docs/data/reviews.json")

MAX_REVIEWS_PER_RS = 5          
MAX_CHARGE_USD = Decimal("50")  
REQUEST_TIMEOUT = 90              

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
    raw = f"{row['Nama RS']}|{row['Username']}|{row['Waktu Ulasan']}|{row['Isi Ulasan']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_existing() -> list[dict]:
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return []


def last_review_date(rows: list[dict], margin_days: int = 7) -> str | None:
    dates = [r["Waktu Ulasan"] for r in rows if r.get("Waktu Ulasan")]
    if not dates:
        return None
    d = datetime.fromisoformat(max(dates)[:10]) - timedelta(days=margin_days)
    return d.strftime("%Y-%m-%d")


def wake_up_svm_api():
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
    try:
        resp = requests.post(SVM_API_URL, json={"text": text}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"  Gagal klasifikasi: {e}")
        return {}

def arg_value(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

def main():
    existing = load_existing()
    existing_ids = {r["id"] for r in existing}

    if "--reclassify" in sys.argv:
        wake_up_svm_api()
        for row in existing:
            res = classify_sentiment(row["Isi Ulasan"])
            if res.get("sentimen"):
                row["Sentimen_Prediksi"] = res["sentimen"]
                row["Confidence"] = res.get("confidence")
                row["Teks_Bersih"] = res.get("clean_text")
            time.sleep(0.5)
        OUTPUT_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Klasifikasi ulang selesai: {len(existing)} ulasan")
        return
    
    print(f"Data lama: {len(existing)} ulasan (ID unik: {len(existing_ids)})")

    client = ApifyClient(API_TOKEN)

    max_reviews = int(arg_value("--max-reviews", MAX_REVIEWS_PER_RS))
    max_charge = Decimal(arg_value("--max-charge", str(MAX_CHARGE_USD)))

    run_input = {
        "startUrls": [{"url": u} for u in daftar_rs_url],
        "language": "id",
        "countryCode": "id",              
        "maxCrawledPlacesPerSearch": 1,   
        "maxReviews": max_reviews,
        "reviewsSort": "newest",
        "maxImages": 0,
        "maxQuestions": 0,

    }

    start_date = arg_value("--since") or last_review_date(existing)
    if start_date:
        run_input["reviewsStartDate"] = start_date  # hanya ulasan sejak tanggal ini
        print(f"Hanya mengambil ulasan sejak {start_date}")

    print(f"Menjalankan Apify actor untuk {len(daftar_rs_url)} RS "
          f"(maks {max_reviews} ulasan/RS, batas biaya ${max_charge})...")
    try:
        run = client.actor("compass/crawler-google-places").call(
            run_input=run_input,
            max_total_charge_usd=max_charge,   # <- ganti dari MAX_CHARGE_USD
        )
    except ApifyApiError as e:
        print(f"⚠️ Apify gagal dijalankan: {e}")
        print("Data lama dipertahankan, tidak ada perubahan file.")
        return

    dataset_id = get_field(run, "defaultDatasetId")
    print(f"Selesai scraping. Dataset: {dataset_id}")

    # --- Flatten hasil scraping ---
    # iterate_items() selalu mengembalikan dict biasa, jadi .get() aman di sini.
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

    # Jaring pengaman: buang baris yang koordinatnya di luar Indonesia (bounding box kasar)
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

    # --- Filter yang benar-benar baru ---
    new_rows = [r for r in scraped_rows if r["id"] not in existing_ids]
    print(f"Ulasan BARU yang perlu diklasifikasi: {len(new_rows)}")

    if not new_rows:
        print("Tidak ada ulasan baru. Selesai, tidak ada perubahan file.")
        return

    # --- Klasifikasi sentimen untuk ulasan baru saja ---
    wake_up_svm_api()
    processed_new = []
    skipped_failed = 0
    for i, row in enumerate(new_rows, 1):
        print(f"  [{i}/{len(new_rows)}] Klasifikasi: {(row['Nama RS'] or '-')[:30]}...")
        result = classify_sentiment(row["Isi Ulasan"])
        if not result or "sentimen" not in result:
            # Jangan simpan label palsu kalau API gagal -- skip supaya
            # otomatis dicoba lagi di run berikutnya.
            print("    Gagal/API tidak merespons dengan benar, dilewati (dicoba lagi run berikutnya).")
            skipped_failed += 1
            continue
        row["Sentimen_Prediksi"] = result.get("sentimen")
        row["Confidence"] = result.get("confidence")
        row["Teks_Bersih"] = result.get("clean_text")   # BARU: None jika API belum di-deploy ulang
        row["Processed_At"] = datetime.utcnow().isoformat()
        processed_new.append(row)
        time.sleep(0.5)  # jaga-jaga rate limit

    if skipped_failed:
        print(f"⚠️  {skipped_failed} ulasan baru gagal diklasifikasi dan akan dicoba lagi run berikutnya.")

    # --- Gabungkan dengan data lama, simpan ---
    combined = existing + processed_new
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ Selesai. Total ulasan sekarang: {len(combined)} "
          f"(+{len(processed_new)} baru) -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()