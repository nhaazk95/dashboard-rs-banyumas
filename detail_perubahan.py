import json
import subprocess

PATH = "docs/data/reviews.json"
COMMITS = ["8773df8", "52341c4", "7096e15", "0890cff"]

def muat(rev):
    data = json.loads(subprocess.check_output(["git", "show", f"{rev}:{PATH}"], encoding="utf-8"))
    return {r["id"]: r for r in data if "id" in r}

for c in COMMITS:
    a, b = muat(f"{c}^"), muat(c)
    print(f"\n=== {c} ===")
    for i in a:
        if i in b and a[i].get("Sentimen_Prediksi") != b[i].get("Sentimen_Prediksi"):
            print(f"{a[i]['Sentimen_Prediksi']:8} -> {b[i]['Sentimen_Prediksi']:8} "
                  f"| conf {a[i].get('Confidence')} -> {b[i].get('Confidence')} "
                  f"| {b[i]['Isi Ulasan'][:55]!r}")