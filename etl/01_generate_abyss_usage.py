"""
Генерация синтетических данных: статистика использования персонажей в «Витой бездне».

Реальной открытой выгрузки с метриками по каждому персонажу и периоду нет,
поэтому статистика генерируется по сценарию, а справочные атрибуты
(элемент, оружие, редкость, регион) берутся из реального источника genshin-db.

Зерно данных: персонаж × период (половина патча; 2 фазы на патч).
Окно: патчи 4.0–5.8 (16.08.2023 – 09.09.2025), 36 периодов.

Заложенные закономерности
  1. Power creep: использование персонажа снижается с каждым патчем после выхода.
  2. Эффект релиза: новый персонаж получает всплеск использования в патч выхода.
  3. Роли: у хилеров и щитовиков использование постепенно падает (контент
     поощряет урон, а не выживание).
  4. Благословение бездны: в каждом периоде один элемент получает бонус.
  5. Владение: 4★ и бесплатные есть у большинства, лимитированные 5★ — у меньшинства,
     доля владельцев растёт со временем (повторные баннеры).

Заложенные отклонения (то, что должен найти руководитель)
  A. Фурина (с 4.2) и Беннет — стабильные доминанты, usage > 40 %.
  B. Шилонен (с 5.1) и Ситлали (с 5.3) — новые доминанты; Пиро-отряды
     резко растут после выхода Мавуики (5.3).
  C. Нёвиллет — доминант 4.1–4.8, затем резкое падение в 5.0 (контент с
     устойчивыми к Гидро врагами) — сильное отклонение к прошлому периоду.
  D. Син Цю — ускоренный power creep: со ~35 % до < 15 %.
  E. Качина и Фремине — новые 4★, почти сразу «мёртвый груз» (< 5 %).
  F. Ци Ци, Эмбер, Элой, Синь Янь, Саю — устойчиво невостребованы.
  G. Период 5.4 (фаза 2) — провал выборки игроков (сбой сбора данных).

Загрязнения сырого файла (их исправляет Transform в 02_etl_pipeline.py)
  - смешанные форматы дат (YYYY-MM-DD и DD.MM.YYYY);
  - версия как «4.0», «v4.0», « 4.0 »;
  - имена персонажей: регистр, без пробелов, на русском;
  - дубликаты строк;
  - пропуски и десятичная запятая в среднем уроне;
  - ошибочные значения времени прохождения (0, -1, 9999);
  - users > owners (невозможное значение);
  - записи по персонажу до даты его выхода (тестовые аккаунты);
  - тестовый персонаж «Test_Dummy».

Выход: data/raw/abyss_usage_raw.csv
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2026
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# Сила персонажа в мете на старте окна (или в момент выхода), 0..1.
# Экспертная оценка по уровням: S=0.9, A=0.72, B=0.52, C=0.32, D=0.15
S, A, B, C, D = 0.9, 0.72, 0.52, 0.32, 0.15
POWER = {
    "Furina": S, "Kaedehara Kazuha": S, "Bennett": S, "Nahida": S, "Yelan": S,
    "Zhongli": A, "Raiden Shogun": A, "Neuvillette": S, "Arlecchino": S,
    "Xilonen": S, "Citlali": S, "Mavuika": S, "Escoffier": S, "Skirk": S,
    "Xingqiu": A, "Xiangling": A, "Fischl": A, "Faruzan": A, "Kokomi": A,
    "Sangonomiya Kokomi": A, "Shenhe": A, "Kamisato Ayaka": A, "Hu Tao": A,
    "Alhaitham": A, "Wriothesley": A, "Navia": A, "Clorinde": A, "Mualani": A,
    "Kinich": A, "Varesa": A, "Emilie": A, "Ineffa": A, "Sucrose": A,
    "Yae Miko": A, "Nilou": A, "Wanderer": A, "Lyney": A, "Chasca": A,
    "Iansan": A, "Xianyun": A, "Chevreuse": A, "Venti": B, "Baizhu": B,
    "Tighnari": B, "Chiori": B, "Ororon": B, "Lan Yan": B,
    "Yumemizuki Mizuki": B, "Ifa": B, "Dahlia": B, "Lynette": B,
    "Sigewinne": B, "Yaoyao": B, "Layla": B, "Diona": B, "Kirara": B,
    "Kuki Shinobu": B, "Thoma": B, "Gorou": B, "Ganyu": B, "Arataki Itto": B,
    "Cyno": B, "Keqing": B, "Tartaglia": B, "Yoimiya": B, "Xiao": B,
    "Kamisato Ayato": B, "Jean": B, "Mona": B, "Albedo": B, "Beidou": B,
    "Gaming": B, "Sethos": C, "Charlotte": C, "Candace": C, "Dori": C,
    "Mika": C, "Yun Jin": C, "Eula": C, "Klee": C, "Dehya": C, "Diluc": C,
    "Barbara": C, "Noelle": C, "Kaeya": C, "Lisa": C, "Razor": C,
    "Yanfei": C, "Ningguang": C, "Rosaria": C, "Chongyun": C,
    "Kujou Sara": C, "Collei": C, "Kaveh": C, "Shikanoin Heizou": C,
    "Kachina": D, "Freminet": D, "Qiqi": D, "Aloy": D, "Amber": D,
    "Xinyan": D, "Sayu": D,
}
ROLE_DAMAGE_K = {"Основной DPS": 1250, "Саб-DPS": 680, "Поддержка": 260, "Хил/Щит": 190}
ELEMENTS = ["Pyro", "Hydro", "Anemo", "Electro", "Dendro", "Cryo", "Geo"]


def build_periods():
    cal = pd.read_csv(RAW / "patch_calendar.csv", dtype=str)
    cal["release_date"] = pd.to_datetime(cal["release_date"])
    periods = []
    for i in range(len(cal) - 1):
        v, start, nxt = cal.loc[i, "version"], cal.loc[i, "release_date"], cal.loc[i + 1, "release_date"]
        mid = start + pd.Timedelta(days=21)
        periods.append((v, 1, start, i))
        periods.append((v, 2, mid, i))
    return periods, list(cal["version"][:-1])


def main():
    rng = np.random.default_rng(SEED)
    meta = pd.read_csv(RAW / "character_meta_manual.csv")
    chars = json.loads((RAW / "genshin_db_characters.json").read_text(encoding="utf-8"))["characters"]
    info = {c["name"]: c for c in chars}
    periods, versions = build_periods()
    vidx = {v: i for i, v in enumerate(versions)}

    in_scope = meta[meta["release_version"].isin(["до 4.0"] + versions)].copy()
    in_scope["rel_idx"] = in_scope["release_version"].map(lambda v: -1 if v == "до 4.0" else vidx[v])

    # «Благословение бездны»: один элемент с бонусом на каждый период
    blessing = rng.choice(ELEMENTS, size=len(periods))

    # Стартовая доля владельцев для персонажей, вышедших до окна
    base_own = {}
    for _, r in in_scope.iterrows():
        bt = r["banner_type"]
        if bt == "Бесплатный":
            base_own[r.name_en] = rng.uniform(0.90, 0.97)
        elif bt == "4★ баннерный":
            base_own[r.name_en] = rng.uniform(0.62, 0.92) if r.rel_idx < 0 else 0.30
        elif bt == "Стандартный 5★":
            base_own[r.name_en] = rng.uniform(0.38, 0.52)
        else:
            base_own[r.name_en] = rng.uniform(0.16, 0.42) if r.rel_idx < 0 else 0.16 + 0.14 * POWER[r.name_en]

    rows = []
    for t, (ver, phase, start, p) in enumerate(periods):
        players = int(rng.normal(62000, 2500) * (1 + 0.006 * t))
        if ver == "5.4" and phase == 2:          # отклонение G
            players = int(players * 0.58)
        for _, r in in_scope.iterrows():
            name, role, rel = r.name_en, r.role, r.rel_idx
            if p < rel:
                continue
            age = p - max(rel, 0)
            el = info[name]["elementText"]

            # --- владение
            growth = {"Бесплатный": 0.002, "4★ баннерный": 0.035,
                      "Стандартный 5★": 0.006, "Лимитированный 5★": 0.010}[r.banner_type]
            cap = {"Бесплатный": 0.99, "4★ баннерный": 0.95,
                   "Стандартный 5★": 0.65, "Лимитированный 5★": 0.62}[r.banner_type]
            own_rate = min(cap, base_own[name] + growth * (age + phase / 2))
            own_rate = float(np.clip(own_rate * rng.normal(1, 0.015), 0.05, 0.995))

            # --- сила в мете с учётом power creep
            creep = 0.012 if role in ("Основной DPS", "Саб-DPS") else 0.006
            if name == "Xingqiu":
                creep = 0.028                                  # отклонение D
            pw = max(0.05, POWER[name] - creep * age)
            usage = 0.015 + 0.62 * pw ** 2

            # эффект релиза
            if p == rel:
                usage *= 1.45 if phase == 1 else 1.28
            elif p == rel + 1:
                usage *= 1.12
            # роль хилеров со временем теряет ценность
            if role == "Хил/Щит":
                usage *= 1 - 0.014 * p
            # благословение бездны
            if el == blessing[t]:
                usage *= 1.22

            # сценарные отклонения
            if name == "Furina":
                usage = 0.70 + 0.03 * np.sin(t)                # A
            if name == "Bennett":
                usage = 0.57 + (0.05 if p >= vidx["5.3"] else 0)  # A + пиро-волна
            if name == "Xilonen":
                usage = 0.62 if p > rel else usage             # B
            if name == "Citlali":
                usage = 0.55 if p > rel else usage
            if el == "Pyro" and p >= vidx["5.3"] and name not in ("Bennett",):
                usage *= 1.35                                  # B: пиро-волна
            if name == "Neuvillette":                          # C
                usage = 0.52 if p < vidx["5.0"] else 0.24 - 0.01 * (p - vidx["5.0"])
            if name in ("Kachina", "Freminet") and p > rel:    # E
                usage = 0.03

            usage = float(np.clip(usage * rng.normal(1, 0.06), 0.003, 0.92))
            owners = int(round(players * own_rate))
            users = int(round(owners * usage))

            dmg = ROLE_DAMAGE_K[role] * (0.55 + pw) * (1 + 0.015 * t) * rng.lognormal(0, 0.07)
            clear = float(np.clip(58 + 38 * pw + rng.normal(0, 3), 25, 99))
            ctime = float(np.clip(165 - 85 * pw + rng.normal(0, 7), 45, 200))

            rows.append({
                "Cycle Date": start.strftime("%Y-%m-%d"), "Version": ver, "Phase": phase,
                "Character": name, "Players Sampled": players, "Owners": owners,
                "Users": users, "Avg Damage (k)": round(dmg, 1),
                "Clear Rate %": round(clear, 1), "Avg Clear Time (s)": round(ctime, 1),
            })

    df = pd.DataFrame(rows)
    df = inject_noise(df, rng, info, in_scope, periods)
    df.insert(0, "record_id", range(100001, 100001 + len(df)))
    out = RAW / "abyss_usage_raw.csv"
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"[generate] {len(df)} строк -> {out.relative_to(ROOT)}")


def inject_noise(df, rng, info, in_scope, periods):
    n = len(df)
    pick = lambda share: rng.choice(n, size=int(n * share), replace=False)

    # даты в формате DD.MM.YYYY
    i = pick(0.15)
    df.loc[i, "Cycle Date"] = pd.to_datetime(df.loc[i, "Cycle Date"]).dt.strftime("%d.%m.%Y")
    # версия с префиксом и пробелами
    df.loc[pick(0.10), "Version"] = "v" + df["Version"]
    i = pick(0.05)
    df.loc[i, "Version"] = " " + df.loc[i, "Version"] + " "
    # имена: нижний регистр, без пробелов, по-русски
    i = pick(0.08); df.loc[i, "Character"] = df.loc[i, "Character"].str.lower()
    i = pick(0.03); df.loc[i, "Character"] = df.loc[i, "Character"].str.replace(" ", "")
    i = pick(0.03); df.loc[i, "Character"] = df.loc[i, "Character"].map(lambda x: info.get(x, {}).get("name_ru", x))
    # урон: пропуски и десятичная запятая
    df["Avg Damage (k)"] = df["Avg Damage (k)"].astype(object)
    df.loc[pick(0.02), "Avg Damage (k)"] = np.nan
    i = pick(0.01)
    df.loc[i, "Avg Damage (k)"] = df.loc[i, "Avg Damage (k)"].map(lambda x: str(x).replace(".", ","))
    # ошибочное время прохождения
    df.loc[pick(0.006), "Avg Clear Time (s)"] = rng.choice([0, -1, 9999], size=int(n * 0.006))
    # users > owners
    i = pick(0.003); df.loc[i, "Users"] = df.loc[i, "Owners"] + rng.integers(50, 500, size=len(i))

    extra = []
    # записи по персонажу до его выхода
    late = in_scope[in_scope["rel_idx"] > 2]["name_en"].tolist()
    for _ in range(12):
        name = rng.choice(late)
        v, ph, start, p = periods[int(rng.integers(0, 4))]
        extra.append({"Cycle Date": start.strftime("%Y-%m-%d"), "Version": v, "Phase": ph,
                      "Character": name, "Players Sampled": 120, "Owners": 40, "Users": 38,
                      "Avg Damage (k)": 2500.0, "Clear Rate %": 100.0, "Avg Clear Time (s)": 40.0})
    # тестовый персонаж
    for v, ph, start, p in periods[::6]:
        extra.append({"Cycle Date": start.strftime("%Y-%m-%d"), "Version": v, "Phase": ph,
                      "Character": "Test_Dummy", "Players Sampled": 10, "Owners": 10, "Users": 10,
                      "Avg Damage (k)": 99999.0, "Clear Rate %": 100.0, "Avg Clear Time (s)": 1.0})
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    # дубликаты
    dup = df.sample(frac=0.015, random_state=SEED)
    df = pd.concat([df, dup], ignore_index=True)
    return df.sample(frac=1, random_state=SEED).reset_index(drop=True)


if __name__ == "__main__":
    main()
