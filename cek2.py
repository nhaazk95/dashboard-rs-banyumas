import csv, json, subprocess

lama = json.loads(subprocess.run(["git", "show", "HEAD:docs/data/reviews.json"],
                                 capture_output=True, encoding="utf-8").stdout)
baru = json.load(open("docs/data/reviews.json", encoding="utf-8"))
L = {r["id"]: r["Sentimen_Prediksi"] for r in lama}

def harap(rating):
    return "Positif" if rating >= 4 else "Negatif" if rating <= 2 else None

def cocok(ambil):
    ok = n = 0
    for r in baru:
        h = harap(r["Rating"])
        if h:
            n += 1
            ok += ambil(r) == h
    return f"{ok}/{n} ({ok / n:.1%})"

print("Cocok dengan rating - lama:", cocok(lambda r: L[r["id"]]))
print("Cocok dengan rating - baru:", cocok(lambda r: r["Sentimen_Prediksi"]))

ubah = [{"id": r["id"], "Rating": r["Rating"], "lama": L[r["id"]],
         "baru": r["Sentimen_Prediksi"], "Isi Ulasan": r["Isi Ulasan"]}
        for r in baru if L[r["id"]] != r["Sentimen_Prediksi"]]
ubah.sort(key=lambda x: (x["lama"], x["baru"]))
with open("perubahan.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(ubah[0]))
    w.writeheader()
    w.writerows(ubah)
print("Disimpan:", len(ubah), "baris -> perubahan.csv")