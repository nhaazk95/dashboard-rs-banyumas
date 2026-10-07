import json
import subprocess

PATH = "docs/data/reviews.json"

def git(*args):
    return subprocess.check_output(["git", *args], encoding="utf-8")

def muat(rev):
    try:
        data = json.loads(git("show", f"{rev}:{PATH}"))
        return {r["id"]: r for r in data if "id" in r}
    except Exception:
        return {}

# Commit lama -> baru, plus kondisi file sekarang (termasuk yang belum di-commit)
log = git("log", "--reverse", "--format=%h|%an|%ad|%s", "--date=short", "--", PATH)
commits = [l.split("|", 3) for l in log.strip().splitlines()]

with open(PATH, encoding="utf-8") as f:
    kini = {r["id"]: r for r in json.load(f) if "id" in r}

urutan = [(c[0], f"{c[1]} {c[2]} {c[3][:40]}", muat(c[0])) for c in commits]
urutan.append(("SEKARANG", "file di disk (belum tentu di-commit)", kini))

print("Perubahan label per commit:\n")
for (h1, _, a), (h2, ket, b) in zip(urutan, urutan[1:]):
    ubah = [i for i in a if i in b and a[i].get("Sentimen_Prediksi") != b[i].get("Sentimen_Prediksi")]
    if ubah:
        print(f"{h2:9} {ket} -> {len(ubah)} label berubah")