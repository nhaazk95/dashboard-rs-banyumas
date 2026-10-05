import json
import pandas as pd

d = pd.DataFrame(json.load(open("docs/data/reviews.json", encoding="utf-8")))

kondisi = {
    "rating rendah tapi bukan Negatif": (d.Rating <= 2) & (d.Sentimen_Prediksi != "Negatif"),
    "rating tinggi tapi Negatif": (d.Rating >= 4) & (d.Sentimen_Prediksi == "Negatif"),
    "rating 5 tapi Netral": (d.Rating == 5) & (d.Sentimen_Prediksi == "Netral"),
    "pertanyaan": d["Isi Ulasan"].str.contains(
        r"\?|\b(?:apakah|adakah|apa ada|mau tanya)\b", case=False, regex=True),
}
d["alasan"] = ""
for nama, mask in kondisi.items():
    d.loc[mask, "alasan"] += nama + "; "

out = d[d.alasan != ""][["id", "Isi Ulasan", "Rating", "Sentimen_Prediksi", "Confidence", "alasan"]]
out = out.assign(label_final="")
out.to_csv("cek_label.csv", index=False, encoding="utf-8-sig")
print(len(out), "baris")