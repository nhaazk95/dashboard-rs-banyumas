import hashlib
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import requests
from apify_client import ApifyClient
from apify_client.errors import ApifyApiError


# ============================================================
# KONFIGURASI
# ============================================================
API_TOKEN = os.environ.get("APIFY_TOKEN")   # hanya wajib saat scraping
SVM_API_URL = "https://sentimen-api.onrender.com/predict"
SVM_WAKEUP_URL = "https://sentimen-api.onrender.com/"
SARAN_URL = "https://sentimen-api.onrender.com/saran"

OUTPUT_FILE = Path("docs/data/reviews.json")
META_FILE = Path("docs/data/meta.json")

MAX_REVIEWS_PER_RS = 5
MAX_CHARGE_USD = Decimal("2")     # batas biaya per run (minimal $0.50 menurut Apify)
REQUEST_TIMEOUT = 90
NOTIFY_MAX_AGE_DAYS = 14          # email hanya untuk ulasan yang ditulis dalam N hari terakhir
MAX_SARAN_API = 8                 # maksimal panggilan AI per run untuk bagian Masukan

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


def tulis_meta(baru: int):
    """Catat kapan terakhir workflow berjalan (dipakai dashboard untuk 'Dicek terakhir')."""
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps({
        "last_run_utc": datetime.utcnow().isoformat() + "Z",
        "new_reviews": baru,
    }), encoding="utf-8")


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
# NOTIFIKASI EMAIL (ulasan negatif) -- satu email per RS, format surat
# ============================================================
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
         "Agustus", "September", "Oktober", "November", "Desember"]

DEFAULT_MASUKAN = ("Diharapkan pihak rumah sakit meninjau kembali pengalaman yang disampaikan "
                   "pasien pada ulasan ini dan melakukan perbaikan layanan yang diperlukan.")

# Cadangan bila /saran (AI) tidak tersedia: pola kata kunci -> saran umum sesuai topik
_ATURAN_MASUKAN = [
    (r"antre|antri|antrian|tunggu|menunggu|lama|lambat|lelet",
     "Diharapkan waktu tunggu dan informasi antrean dapat dikelola lebih baik agar pasien "
     "mengetahui perkiraan waktu pelayanan."),
    (r"igd|ugd|darurat",
     "Diharapkan penanganan di IGD dapat lebih cepat dan informasi kepada keluarga pasien lebih jelas."),
    (r"obat|farmasi|apotek|resep",
     "Diharapkan pelayanan farmasi dan pengambilan obat dapat dipercepat serta disertai penjelasan yang jelas."),
    (r"judes|kasar|ketus|galak|cuek|tidak ramah|kurang ramah|sikap",
     "Diharapkan petugas dapat melayani pasien dengan lebih ramah, sopan, dan responsif."),
    (r"biaya|tarif|mahal|bayar|pembayaran|qris|tagihan|kasir",
     "Diharapkan informasi biaya dan proses pembayaran dapat disampaikan lebih transparan dan mudah."),
    (r"bpjs|administrasi|pendaftaran|daftar|berkas|rujukan|prosedur|alur",
     "Diharapkan alur pendaftaran dan administrasi dapat disederhanakan dan dijelaskan dengan lebih jelas."),
    (r"parkir",
     "Diharapkan penataan area parkir dapat diperbaiki agar lebih nyaman dan mudah bagi pengunjung."),
    (r"kotor|bau|toilet|kamar mandi|kebersihan",
     "Diharapkan kebersihan dan kenyamanan fasilitas, seperti ruang tunggu, kamar, dan toilet, dapat lebih dijaga."),
    (r"dokter|spesialis|jadwal praktik|visit",
     "Diharapkan dokter dapat memberikan penjelasan yang lebih jelas kepada pasien dan jadwal praktik "
     "dapat lebih tepat waktu."),
]


def _tgl(row):
    try:
        return datetime.fromisoformat(str(row["Waktu Ulasan"]).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.min


def masukan_fallback(teks: str) -> str:
    t = (teks or "").lower()
    for pola, saran in _ATURAN_MASUKAN:
        if re.search(r"\b(?:" + pola + r")\b", t):
            return saran
    return DEFAULT_MASUKAN


def buat_masukan(row: dict, pakai_api: bool = True) -> str:
    teks = " ".join((row.get("Isi Ulasan") or "").split())
    if pakai_api:
        try:
            r = requests.post(SARAN_URL, timeout=45, json={
                "rs": row.get("Nama RS") or "", "text": teks, "rating": row.get("Rating")})
            if r.status_code == 200:
                m = " ".join((r.json().get("masukan") or "").split())
                if m:
                    return m
        except requests.exceptions.RequestException as e:
            print(f"  Masukan via AI gagal, pakai aturan kata kunci: {e}")
    return masukan_fallback(teks)


def _fmt_tanggal(row: dict) -> str:
    d = _tgl(row)
    return "-" if d == datetime.min else f"{d.day:02d} {BULAN[d.month - 1]} {d.year}"


def _fmt_rating(v) -> str:
    try:
        f = float(v)
        return f"{int(f) if f.is_integer() else f}/5"
    except (TypeError, ValueError):
        return "-"


def _susun_email(rs: str, rows: list, masukan: dict) -> str:
    n = len(rows)
    kepala = f"Yth. Pihak {rs},\n\n" + (
        "Terdapat ulasan yang terdeteksi sebagai sentimen negatif:\n" if n == 1
        else f"Terdapat {n} ulasan yang terdeteksi sebagai sentimen negatif:\n")
    blok = []
    for r in rows:
        teks = " ".join((r.get("Isi Ulasan") or "").split())[:1500]
        blok.append(f"\n⭐ Rating: {_fmt_rating(r.get('Rating'))}\n"
                    f"📅 Tanggal: {_fmt_tanggal(r)}\n"
                    f"“{teks}”\n"
                    f"Masukan: {masukan[id(r)]}\n")
    penutup = ("\nCatatan: Prediksi sentimen oleh model SVM dapat mengandung kesalahan. "
               "Mohon melakukan pengecekan terhadap isi ulasan.\n\n"
               "Terima kasih atas perhatian dan tindak lanjutnya.")
    return kepala + "\n──────────\n".join(blok) + penutup


def kirim_notifikasi_negatif(rows) -> set:
    """Kirim satu email per RS. Return set id(row) yang berhasil terkirim."""
    terkirim = set()
    if not rows:
        return terkirim
    user = (os.environ.get("GMAIL_USER") or "").strip()
    pwd = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    tujuan = (os.environ.get("NOTIFY_TO") or "").strip()
    kosong = [n for n, v in (("GMAIL_USER", user), ("GMAIL_APP_PASSWORD", pwd), ("NOTIFY_TO", tujuan)) if not v]
    if kosong:
        print(f"Notifikasi email dilewati: secret kosong -> {', '.join(kosong)}")
        return terkirim

    per_rs = {}
    for r in sorted(rows, key=_tgl):
        per_rs.setdefault(r.get("Nama RS") or "RS tidak diketahui", []).append(r)

    wake_up_svm_api()          # endpoint /saran ada di server yang sama
    dipakai_api = 0
    paket = []
    for rs, daftar in per_rs.items():
        masukan = {}
        for r in daftar:
            if dipakai_api < MAX_SARAN_API:
                masukan[id(r)] = buat_masukan(r, True)
                dipakai_api += 1
            else:
                masukan[id(r)] = masukan_fallback(r.get("Isi Ulasan"))
        paket.append((rs, daftar, _susun_email(rs, daftar, masukan)))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            for rs, daftar, isi in paket:
                msg = EmailMessage()
                msg["Subject"] = f"[Dashboard RS] Ulasan negatif baru - {rs}" + (
                    f" ({len(daftar)})" if len(daftar) > 1 else "")
                msg["From"] = user
                msg["To"] = tujuan
                msg.set_content(isi)
                try:
                    s.send_message(msg)
                    terkirim.update(id(r) for r in daftar)
                    print(f"Email terkirim: {rs} ({len(daftar)} ulasan)")
                except Exception as e:
                    print(f"⚠️ Email untuk {rs} gagal: {e}")
    except Exception as e:
        print(f"⚠️ Email notifikasi gagal dikirim: {e}")
    return terkirim


def kirim_pending(rows) -> bool:
    """Kirim email untuk baris Notified=False. Hanya baris yang berhasil terkirim
    (atau memang tidak perlu dikirim) yang ditandai True; sisanya dicoba lagi di run berikutnya.
    Return True bila ada baris yang berubah (file perlu disimpan)."""
    pending = [r for r in rows if r.get("Notified") is False]
    if not pending:
        return False
    batas = datetime.utcnow() - timedelta(days=NOTIFY_MAX_AGE_DAYS)
    layak = [r for r in pending if r.get("Sentimen_Prediksi") == "Negatif" and _tgl(r) >= batas]
    layak_ids = {id(r) for r in layak}
    terkirim = kirim_notifikasi_negatif(layak) if layak else set()

    berubah = False
    for r in pending:
        if id(r) not in layak_ids or id(r) in terkirim:
            r["Notified"] = True
            berubah = True
    return berubah


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
    menunggu = sum(1 for r in existing if r.get("Notified") is False)
    print(f"Notifikasi aktif: {notif_aktif} | baris menunggu notifikasi (Notified=False): {menunggu}")

    # Kirim email untuk baris yang sudah ada tapi belum diberitahukan
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
        print("Tidak ada ulasan baru. Selesai, tidak ada perubahan file ulasan.")
        tulis_meta(0)
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

    tulis_meta(len(processed_new))
    print(f"\n✅ Selesai. Total ulasan sekarang: {len(combined)} "
          f"(+{len(processed_new)} baru) -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()