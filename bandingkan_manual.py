import csv
import json
import subprocess

import pandas as pd

HASH = "8773df8^"          # kondisi tepat sebelum editan pertama
PATH = "docs/data/reviews.json"

lama = json.loads(subprocess.check_output(
    ["git", "show", f"{HASH}:{PATH}"], encoding="utf-8"))
lama = {r["id"]: r for r in lama}

with open(PATH, encoding="utf-8") as f:
    sekarang = json.load(f)

ekspor = []
for r in sekarang:
    o = lama.get(r["id"])
    # Tanpa filter Confidence: 1 baris confidence-nya ikut kamu ubah
    if o and o.get("Sentimen_Prediksi") != r.get("Sentimen_Prediksi"):
        r["Label_Manual"] = r["Sentimen_Prediksi"]
        ekspor.append({"text": r["Isi Ulasan"], "label": r["Sentimen_Prediksi"]})

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(sekarang, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(ekspor).drop_duplicates()
df.to_csv("koreksi_dari_dashboard.csv", index=False, quoting=csv.QUOTE_NONNUMERIC)
print(f"Ditandai Label_Manual: {len(ekspor)} baris | unik untuk training: {len(df)}")
print(df["label"].value_counts().to_dict())