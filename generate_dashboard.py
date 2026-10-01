"""
Generate Banyumas Hospital Sentiment Dashboard (HTML interaktif)
dari file Excel hasil prediksi SVM.

Cara pakai (di VS Code / terminal lokal):
    1. pip install pandas openpyxl
    2. Taruh file Excel kamu di folder ini, atau edit INPUT_FILE di bawah
    3. Jalankan: python generate_dashboard.py
    4. Hasilnya ada di docs/index.html -- buka langsung di browser untuk cek,
       atau push ke GitHub untuk hosting gratis (lihat README.md)
"""

import pandas as pd
import json
from pathlib import Path

# ============================================================
# 1. KONFIGURASI -- ganti path ini sesuai lokasi file Excel kamu
# ============================================================
INPUT_FILE = "Hasil_Prediksi_RS_2026.xlsx"
OUTPUT_FILE = Path("docs") / "index.html"

# Ganti dengan token Mapbox kamu sendiri (gratis, daftar di mapbox.com)
MAPBOX_TOKEN = "pk.eyJ1IjoibmhhYXprIiwiYSI6ImNtdW51Z3liajBkYmcyeHE3dHYwaW1wZmYifQ.CvBbuiQZHlSCpzni9EU-og"

# ============================================================
# 2. LOAD & VALIDASI DATA
# ============================================================
print(f"Reading file: {INPUT_FILE}")
df = pd.read_excel(INPUT_FILE)
print("File loaded successfully.")

required = ['Nama RS', 'Rating', 'Waktu Ulasan', 'Latitude', 'Longitude', 'Sentimen_Prediksi']
missing = [c for c in required if c not in df.columns]
if missing:
    raise ValueError(f"Kolom berikut tidak ditemukan di file Excel: {missing}")

# ============================================================
# 3. PREPROCESSING -- filter April 2026, bagi per minggu
# ============================================================
df['Waktu Ulasan'] = pd.to_datetime(df['Waktu Ulasan'])
df = df[
    (df['Waktu Ulasan'].dt.year == 2026) &
    (df['Waktu Ulasan'].dt.month == 4)
].copy().reset_index(drop=True)


def april_week(tgl):
    hari = tgl.day
    if hari <= 7:
        return 'W1'
    elif hari <= 14:
        return 'W2'
    elif hari <= 21:
        return 'W3'
    else:
        return 'W4'


df['Periode'] = df['Waktu Ulasan'].apply(april_week)

print(f"Total April 2026 records : {len(df):,} rows")
print(f"Number of hospitals      : {df['Nama RS'].nunique()}")
print(f"Weekly distribution:\n{df['Periode'].value_counts().sort_index().to_string()}")
print(f"Sentiment distribution:\n{df['Sentimen_Prediksi'].value_counts().to_string()}")


# ============================================================
# 4. AGREGASI
# ============================================================
def aggregate(data, periode_col=None):
    group_cols = ['Nama RS', 'Latitude', 'Longitude']
    if periode_col:
        group_cols.append(periode_col)
    agg = data.groupby(group_cols).agg(
        Avg_Rating=('Rating', 'mean'),
        Total=('Rating', 'count'),
        Positif=('Sentimen_Prediksi', lambda x: (x == 'Positif').sum()),
        Netral=('Sentimen_Prediksi', lambda x: (x == 'Netral').sum()),
        Negatif=('Sentimen_Prediksi', lambda x: (x == 'Negatif').sum()),
    ).reset_index()
    agg['Dominan'] = agg[['Positif', 'Netral', 'Negatif']].idxmax(axis=1)
    agg['Pct_Pos'] = (agg['Positif'] / agg['Total'] * 100).round(1)
    agg['Pct_Net'] = (agg['Netral'] / agg['Total'] * 100).round(1)
    agg['Pct_Neg'] = (agg['Negatif'] / agg['Total'] * 100).round(1)
    agg['Avg_Rating'] = agg['Avg_Rating'].round(2)
    return agg


agg_all = aggregate(df)
agg_all['Periode'] = 'ALL'
agg_minggu = aggregate(df, 'Periode')
combined = pd.concat([agg_all, agg_minggu], ignore_index=True)

tren_dict = {}
for rs, grp in agg_minggu.groupby('Nama RS'):
    tren_dict[rs] = grp[['Periode', 'Avg_Rating', 'Total', 'Positif', 'Netral', 'Negatif']] \
        .sort_values('Periode').to_dict(orient='records')

data_json = combined.to_dict(orient='records')
print(f"Aggregation complete: {len(data_json)} records")

DATA_JS = json.dumps(data_json, ensure_ascii=False)
TREN_JS = json.dumps(tren_dict, ensure_ascii=False)

# ============================================================
# 5. TEMPLATE HTML -- dibaca dari file terpisah (lihat dashboard_template.html)
#    supaya tidak perlu urus f-string + kurung kurawal CSS/JS secara manual
# ============================================================
template_path = Path("dashboard_template.html")
html_template = template_path.read_text(encoding="utf-8")

html_output = (
    html_template
    .replace("__DATA_JS__", DATA_JS)
    .replace("__TREN_JS__", TREN_JS)
    .replace("__MAPBOX_TOKEN__", MAPBOX_TOKEN)
)

# ============================================================
# 6. SIMPAN
# ============================================================
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.write_text(html_output, encoding="utf-8")
print(f"\n✅ Dashboard tersimpan di: {OUTPUT_FILE.resolve()}")
print("   Buka file itu langsung di browser untuk cek, atau push folder ini ke GitHub")
print("   untuk hosting gratis -- lihat README.md untuk langkah-langkahnya.")

# ============================================================
# 7. RINGKASAN MINGGUAN (opsional, cuma buat cek di terminal)
# ============================================================
PLABEL_PY = {
    'ALL': 'All Weeks',
    'W1': 'W1 (Apr 1-7)',
    'W2': 'W2 (Apr 8-14)',
    'W3': 'W3 (Apr 15-21)',
    'W4': 'W4 (Apr 22-30)',
}

print("\n" + "=" * 60)
print("WEEKLY STATISTICS SUMMARY -- APRIL 2026")
print("=" * 60)

for periode in ['ALL', 'W1', 'W2', 'W3', 'W4']:
    subset = combined[combined['Periode'] == periode]
    if subset.empty:
        continue
    pos = (subset['Dominan'] == 'Positif').sum()
    net = (subset['Dominan'] == 'Netral').sum()
    neg = (subset['Dominan'] == 'Negatif').sum()
    avg_r = subset['Avg_Rating'].mean()
    total = subset['Total'].sum()
    print(f"\n{PLABEL_PY[periode]}")
    print(f"   Positive: {pos} | Neutral: {net} | Negative: {neg}")
    print(f"   Avg Rating : {avg_r:.2f} | Total Reviews : {total:,}")
