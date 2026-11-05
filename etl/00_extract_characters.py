"""
Extract (часть 1): справочник персонажей Genshin Impact из открытого источника.

Источник: открытая база genshin-db (https://github.com/theBowja/genshin-db),
данные извлекаются из игровых файлов и поддерживаются сообществом.
Берутся JSON-файлы персонажей на английском и русском языках
из зафиксированного коммита — так результат воспроизводим.

Выход: data/raw/genshin_db_characters.json
"""
import json
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/theBowja/genshin-db.git"
PINNED_COMMIT = "8e5badd60b5d894284ccc927a56c9683529d2592"  # снимок от 04.11.2026

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "etl" / ".cache" / "genshin-db"
OUT = ROOT / "data" / "raw" / "genshin_db_characters.json"

# Поля, нужные для анализа (тяжёлые поля вроде costs отбрасываются уже на входе)
KEEP = ["id", "name", "title", "rarity", "elementText", "weaponText",
        "region", "gender", "bodyType", "substatText", "affiliation"]


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fetch_snapshot():
    if not (CACHE / ".git").exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--filter=blob:none", "--no-checkout", REPO_URL, str(CACHE))
    git("sparse-checkout", "set",
        "src/data/English/characters", "src/data/Russian/characters", cwd=CACHE)
    git("checkout", "-q", PINNED_COMMIT, cwd=CACHE)


def main():
    fetch_snapshot()
    en_dir = CACHE / "src/data/English/characters"
    ru_dir = CACHE / "src/data/Russian/characters"
    records = []
    for f in sorted(en_dir.glob("*.json")):
        en = json.loads(f.read_text(encoding="utf-8"))
        ru_path = ru_dir / f.name
        ru = json.loads(ru_path.read_text(encoding="utf-8")) if ru_path.exists() else {}
        rec = {"source_file": f.name, **{k: en.get(k) for k in KEEP}}
        rec["name_ru"] = ru.get("name")
        rec["elementText_ru"] = ru.get("elementText")
        rec["weaponText_ru"] = ru.get("weaponText")
        rec["region_ru"] = ru.get("region")
        records.append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": REPO_URL, "commit": PINNED_COMMIT,
               "count": len(records), "characters": records}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[extract] {len(records)} персонажей -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
