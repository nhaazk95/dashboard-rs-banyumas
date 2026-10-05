import json, subprocess
from collections import Counter

lama = json.loads(subprocess.run(["git", "show", "HEAD:docs/data/reviews.json"],
                                 capture_output=True, encoding="utf-8").stdout)
baru = json.load(open("docs/data/reviews.json", encoding="utf-8"))

L = {r["id"]: r["Sentimen_Prediksi"] for r in lama}
ubah = Counter((L[r["id"]], r["Sentimen_Prediksi"]) for r in baru
               if r["id"] in L and L[r["id"]] != r["Sentimen_Prediksi"])

print("Total:", len(baru))
print("Label berubah:", sum(ubah.values()))
for (a, b), n in ubah.most_common():
    print(f"  {a} -> {b}: {n}")
print("Teks_Bersih kosong:", sum(1 for r in baru if not r.get("Teks_Bersih")))