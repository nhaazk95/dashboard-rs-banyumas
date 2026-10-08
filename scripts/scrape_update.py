import hashlib
import json
import os
import time
import sys
import requests
import smtplib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from email.message import EmailMessage
from apify_client import ApifyClient
from apify_client.errors import ApifyApiError


# ============================================================
# KONFIGURASI
# ============================================================
API_TOKEN = os.environ.get("APIFY_TOKEN")   # hanya wajib saat scraping
SVM_API_URL = "https://sentimen-api.onrender.com/predict"
SVM_WAKEUP_URL = "https://sentimen-api.onrender.com/"

OUTPUT_FILE = Path("docs/data/reviews.json")

MAX_REVIEWS_PER_RS = 5
MAX_CHARGE_USD = Decimal("50")
REQUEST_TIMEOUT = 90
NOTIFY_MAX_AGE_DAYS = 14   # email hanya untuk ulasan yang ditulis dalam N hari terakhir

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


def save(rows: list[dict]):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


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


# ============================================================
# NOTIFIKASI EMAIL (ulasan negatif)
# ============================================================
def _tgl(row):
    try:
        return datetime.fromisoformat(str(row["Waktu Ulasan"]).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.min


def kirim_notifikasi_negatif(rows) -> bool:
    """True = terkirim (atau memang tidak ada yang dikirim). False = gagal/dilewati."""
    if not rows:
        return True
    user = os.environ.get("GMAIL_USER")
    pwd = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    tujuan = os.environ.get("NOTIFY_TO")
    if not (user and pwd and tujuan):
        print("Notifikasi email dilewati: GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_TO belum diset.")
        return False

    rows = sorted(rows, key=lambda r: (r.get("Nama RS") or "", _tgl(r)))
    baris = []
    for r in rows[:30]:
        baris.append(f"- {r.get('Nama RS')} | {r.get('Rating')}★ | {_tgl(r).strftime('%d %b %Y')}\n"
                     f"  {(r.get('Isi Ulasan') or '').strip()[:500]}\n")
    if len(rows) > 30:
        baris.append(f"... dan {len(rows) - 30} ulasan negatif lainnya (lihat dashboard).")

    msg = EmailMessage()
    msg["Subject"] = f"[Dashboard RS] {len(rows)} ulasan negatif baru"
    msg["From"] = user
    msg["To"] = tujuan
    msg.set_content("Ulasan berikut diprediksi NEGATIF oleh model SVM. Prediksi bisa keliru, "
                    "cek isi ulasannya.\n\n" + "\n".join(baris))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
    except Exception as e:
        print(f"⚠️ Email notifikasi gagal dikirim: {e}")
        return False
    print(f"Email notifikasi terkirim: {len(rows)} ulasan negatif.")
    return True


def kirim_pending(rows) -> bool:
    """Kirim email untuk baris Notified=False, lalu tandai True.
    Return True kalau ada baris yang berubah (file perlu disimpan)."""
    pending = [r for r in rows if r.get("Notified") is False]
    if not pending:
        return False
    batas = datetime.utcnow() - timedelta(days=NOTIFY_MAX_AGE_DAYS)
    kirim = [r for r in pending
             if r.get("Sentimen_Prediksi") == "Negatif" and _tgl(r) >= batas]
    if not kirim_notifikasi_negatif(kirim):
        return False          # gagal: tetap False, dicoba lagi di run berikutnya
    for r in pending:
        r["Notified"] = True
    return True


# ============================================================
# MAIN
# ============================================================
def main():
    existing = load_existing()
    existing_ids = {r["id"] for r in existing}

    if "--reclassify" in sys.argv:
        wake_up_svm_api()
        dilewati = 0
        for row in existing:
            if row.get("Label_Manual"):
                row["Sentimen_Prediksi"] = row["Label_Manual"]   # pertahankan koreksi manual
                dilewati += 1
                continue
            res = classify_sentiment(row["Isi Ulasan"])
            if res.get("sentimen"):
                row["Sentimen_Prediksi"] = res["sentimen"]
                row["Confidence"] = res.get("confidence")
                row["Teks_Bersih"] = res.get("clean_text")
            time.sleep(0.5)
        save(existing)
        print(f"Klasifikasi ulang selesai: {len(existing)} ulasan ({dilewati} label manual dipertahankan)")
        return

    print(f"Data lama: {len(existing)} ulasan (ID unik: {len(existing_ids)})")

    # Email dimatikan saat backfill (--since) atau dengan --no-email
    notif_aktif = "--no-email" not in sys.argv and "--since" not in sys.argv

    # Kirim email untuk baris yang sudah ada tapi belum diberitahukan (Notified=False)
    if notif_aktif or "--notify-only" in sys.argv:
        if kirim_pending(existing):
            save(existing)
    if "--notify-only" in sys.argv:
        print("Mode --notify-only selesai.")
        return

    if not API_TOKEN:
        raise SystemExit("APIFY_TOKEN belum diset (dibutuhkan untuk scraping).")
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
            max_total_charge_usd=max_charge,
        )
    except ApifyApiError as e:
        print(f"⚠️ Apify gagal dijalankan: {e}")
        print("Data lama dipertahankan, tidak ada perubahan file.")
        return

    dataset_id = get_field(run, "defaultDatasetId")
    print(f"Selesai scraping. Dataset: {dataset_id}")

    # --- Flatten hasil scraping ---
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
        row["Teks_Bersih"] = result.get("clean_text")
        row["Processed_At"] = datetime.utcnow().isoformat()
        row["Notified"] = False if notif_aktif else True
        processed_new.append(row)
        time.sleep(0.5)  # jaga-jaga rate limit

    if skipped_failed:
        print(f"⚠️  {skipped_failed} ulasan baru gagal diklasifikasi dan akan dicoba lagi run berikutnya.")

    # --- Gabungkan dengan data lama, simpan ---
    combined = existing + processed_new
    save(combined)

    # --- Email untuk ulasan negatif yang baru masuk ---
    # processed_new berisi objek yang sama dengan di combined, jadi flag Notified ikut berubah
    if notif_aktif and kirim_pending(processed_new):
        save(combined)

    print(f"\n✅ Selesai. Total ulasan sekarang: {len(combined)} "
          f"(+{len(processed_new)} baru) -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()