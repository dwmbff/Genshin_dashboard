"""
ETL-пайплайн: сырые данные -> модель для Power BI (звёздная схема).

Extract   data/raw/abyss_usage_raw.csv           статистика бездны (синтетика)
          data/raw/genshin_db_characters.json    справочник персонажей (genshin-db)
          data/raw/character_meta_manual.csv     роли, тип баннера, версия выхода
          data/raw/patch_calendar.csv            календарь патчей
Transform очистка, нормализация, проверки качества, расчёт метрик
Load      data/processed/fact_abyss_usage.csv
          data/processed/dim_character.csv
          data/processed/dim_period.csv
          data/processed/dq_report.md            журнал проверок качества

Запуск: python etl/02_etl_pipeline.py
При повторном запуске на тех же сырых файлах результат идентичен.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

# Целевой коридор баланса (плановые значения) для usage rate, %
PLAN_MIN, PLAN_MAX = 5.0, 40.0
# Порог резкого изменения к прошлому периоду, п.п.
ALERT_DELTA_PP = 10.0

log = []


def step(name, before, after, note=""):
    log.append((name, before, after, note))
    print(f"  {name:<52} {before:>6} -> {after:<6} {note}")


# ----------------------------------------------------------------- EXTRACT
def extract():
    print("[E] Extract")
    raw = pd.read_csv(RAW / "abyss_usage_raw.csv", dtype=str, keep_default_na=False)
    chars = json.loads((RAW / "genshin_db_characters.json").read_text(encoding="utf-8"))
    meta = pd.read_csv(RAW / "character_meta_manual.csv", dtype=str)
    cal = pd.read_csv(RAW / "patch_calendar.csv", dtype=str)
    print(f"  abyss_usage_raw: {len(raw)} строк; персонажей в справочнике: {chars['count']}")
    return raw, pd.DataFrame(chars["characters"]), meta, cal


# --------------------------------------------------------------- TRANSFORM
def build_dim_period(cal):
    cal = cal.copy()
    cal["release_date"] = pd.to_datetime(cal["release_date"])
    rows = []
    for i in range(len(cal) - 1):
        v, start, nxt = cal.loc[i, "version"], cal.loc[i, "release_date"], cal.loc[i + 1, "release_date"]
        mid = start + pd.Timedelta(days=21)
        for phase, s, e in ((1, start, mid - pd.Timedelta(days=1)), (2, mid, nxt - pd.Timedelta(days=1))):
            rows.append({"period_id": f"{v}-{phase}", "version": v, "phase": phase,
                         "period_label": f"{v} ф{phase}", "start_date": s, "end_date": e})
    dp = pd.DataFrame(rows)
    dp["period_order"] = range(1, len(dp) + 1)
    dp["version_order"] = dp["version"].rank(method="dense").astype(int)
    dp["year"] = dp["start_date"].dt.year
    dp["month_start"] = dp["start_date"].dt.to_period("M").dt.to_timestamp()
    return dp


def build_dim_character(chars, meta, versions):
    m = meta[meta["release_version"].isin(["до 4.0"] + versions)]
    d = m.merge(chars, left_on="name_en", right_on="name", how="left", validate="1:1")
    dim = pd.DataFrame({
        "character_id": d["id"].astype(int),
        "name_en": d["name_en"],
        "name_ru": d["name_ru"],
        "element": d["elementText_ru"],
        "weapon": d["weaponText_ru"],
        "rarity": d["rarity"].astype(int).astype(str) + "★",
        "region": d["region_ru"].replace("", "Не указан").fillna("Не указан"),
        "role": d["role"],
        "banner_type": d["banner_type"],
        "release_version": d["release_version"],
    })
    dim["release_version_sort"] = dim["release_version"].map(
        lambda v: 3.9 if v == "до 4.0" else float(v))
    return dim.sort_values("name_en").reset_index(drop=True)


def norm_key(s):
    return re.sub(r"[\s_\-]", "", str(s)).lower().replace("ё", "е")


def transform(raw, chars, meta, cal):
    print("[T] Transform")
    df = raw.copy()
    n0 = len(df)

    # T1. Имена столбцов -> snake_case
    df.columns = ["record_id", "cycle_date", "version", "phase", "character",
                  "players", "owners", "users", "avg_damage_k", "clear_rate_pct", "avg_clear_time_sec"]
    step("T1 Переименование столбцов", n0, len(df))

    # T2. Обрезка пробелов во всех строковых полях, нормализация версии
    df = df.apply(lambda s: s.str.strip())
    bad_ver = (~df["version"].str.fullmatch(r"\d\.\d")).sum()
    df["version"] = df["version"].str.replace(r"^[vV]", "", regex=True)
    step("T2 Нормализация версии («v4.0», пробелы)", len(df), len(df), f"исправлено {bad_ver}")

    # T3. Даты: два формата -> datetime
    iso = pd.to_datetime(df["cycle_date"], format="%Y-%m-%d", errors="coerce")
    ru = pd.to_datetime(df["cycle_date"], format="%d.%m.%Y", errors="coerce")
    df["cycle_date"] = iso.fillna(ru)
    step("T3 Приведение дат (YYYY-MM-DD / DD.MM.YYYY)", len(df), len(df),
         f"формат ДД.ММ.ГГГГ: {iso.isna().sum()}, не распознано: {df['cycle_date'].isna().sum()}")

    # T4. Имена персонажей -> единый ключ name_en (англ./рус., регистр, пробелы)
    alias = {}
    for _, c in chars.iterrows():
        alias[norm_key(c["name"])] = c["name"]
        if c.get("name_ru"):
            alias[norm_key(c["name_ru"])] = c["name"]
    mapped = df["character"].map(lambda x: alias.get(norm_key(x)))
    renamed = (mapped.notna() & (mapped != df["character"])).sum()
    unknown = df.loc[mapped.isna(), "character"].unique().tolist()
    n = len(df)
    df["character"] = mapped
    df = df[df["character"].notna()]
    step("T4 Унификация имён персонажей", n, len(df),
         f"переименовано {renamed}; удалены неизвестные: {unknown}")

    # T5. Дубликаты: полные и по ключу (период, персонаж)
    n = len(df)
    df = df.drop_duplicates(subset=[c for c in df.columns if c != "record_id"])
    n_full = len(df)
    df = df.sort_values("record_id").drop_duplicates(subset=["version", "phase", "character"], keep="first")
    step("T5 Удаление дубликатов", n, len(df), f"полных: {n - n_full}, по ключу: {n_full - len(df)}")

    # T6. Типы данных; десятичная запятая
    comma = df["avg_damage_k"].str.contains(",").sum()
    df["avg_damage_k"] = pd.to_numeric(df["avg_damage_k"].str.replace(",", "."), errors="coerce")
    for col in ["phase", "players", "owners", "users"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ["clear_rate_pct", "avg_clear_time_sec"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    step("T6 Приведение типов (десятичная запятая)", len(df), len(df),
         f"запятых: {comma}, пропусков урона: {df['avg_damage_k'].isna().sum()}")

    # T7. Привязка к календарю: период и проверка даты
    dp = build_dim_period(cal)
    df["period_id"] = df["version"] + "-" + df["phase"].astype(str)
    n = len(df)
    df = df.merge(dp[["period_id", "start_date", "period_order"]], on="period_id", how="inner")
    mismatch = (df["cycle_date"] != df["start_date"]).sum()
    df["cycle_date"] = df["start_date"]
    df = df.drop(columns="start_date")
    step("T7 Привязка к периоду, сверка даты с календарём", n, len(df), f"расхождений дат: {mismatch}")

    # T8. Записи до выхода персонажа и вне окна анализа
    versions = list(dp["version"].unique())
    dim_char = build_dim_character(chars, meta, versions)
    rel = dim_char.set_index("name_en")["release_version_sort"]
    n = len(df)
    df = df[df["character"].isin(rel.index)]
    df = df[df["version"].astype(float) >= df["character"].map(rel)]
    step("T8 Удаление записей до даты выхода персонажа", n, len(df))

    # T9. Логические проверки: users > owners, время прохождения вне [30; 600] с
    bad_users = df["users"] > df["owners"]
    bad_time = ~df["avg_clear_time_sec"].between(30, 600)
    df.loc[bad_users, "users"] = pd.NA
    df.loc[bad_time, "avg_clear_time_sec"] = np.nan
    step("T9 Невозможные значения -> пропуск", len(df), len(df),
         f"users>owners: {bad_users.sum()}, время вне диапазона: {bad_time.sum()}")

    # T10. Метрики-доли; восстановление пропусков интерполяцией внутри персонажа
    df = df.sort_values(["character", "period_order"]).reset_index(drop=True)
    df["usage_rate_pct"] = df["users"].astype(float) / df["owners"].astype(float) * 100
    gaps = df[["usage_rate_pct", "avg_damage_k", "avg_clear_time_sec"]].isna().sum().to_dict()
    for col in ["usage_rate_pct", "avg_damage_k", "avg_clear_time_sec"]:
        df[col] = df.groupby("character")[col].transform(
            lambda s: s.interpolate(limit_direction="both"))
    df["users"] = df["users"].fillna((df["owners"] * df["usage_rate_pct"] / 100).round()).astype(int)
    step("T10 Интерполяция пропусков по персонажу", len(df), len(df), f"заполнено: {gaps}")

    # T11. Производные метрики и сравнение с прошлым периодом и планом
    df["owner_rate_pct"] = df["owners"] / df["players"] * 100
    df["presence_rate_pct"] = df["users"] / df["players"] * 100
    g = df.groupby("character")
    prev_order = g["period_order"].shift(1)
    consecutive = prev_order == df["period_order"] - 1
    df["usage_rate_prev_pct"] = g["usage_rate_pct"].shift(1).where(consecutive)
    df["usage_delta_pp"] = df["usage_rate_pct"] - df["usage_rate_prev_pct"]
    df["avg_damage_prev_k"] = g["avg_damage_k"].shift(1).where(consecutive)
    df["plan_min_pct"], df["plan_max_pct"] = PLAN_MIN, PLAN_MAX
    df["corridor_status"] = np.select(
        [df["usage_rate_pct"] > PLAN_MAX, df["usage_rate_pct"] < PLAN_MIN],
        ["Доминант (>40%)", "Невостребован (<5%)"], "В коридоре")
    df["plan_deviation_pp"] = np.select(
        [df["usage_rate_pct"] > PLAN_MAX, df["usage_rate_pct"] < PLAN_MIN],
        [df["usage_rate_pct"] - PLAN_MAX, df["usage_rate_pct"] - PLAN_MIN], 0.0)
    df["sharp_change_flag"] = (df["usage_delta_pp"].abs() >= ALERT_DELTA_PP).astype(int)
    df["is_release_patch"] = (df["version"] == df["character"].map(
        dim_char.set_index("name_en")["release_version"])).astype(int)
    step("T11 Расчёт метрик, Δ к прошлому периоду, статус коридора", len(df), len(df))

    # T12. Финальная структура факта
    df = df.merge(dim_char[["name_en", "character_id"]], left_on="character", right_on="name_en")
    fact = df[[
        "record_id", "period_id", "character_id", "cycle_date", "players", "owners", "users",
        "owner_rate_pct", "usage_rate_pct", "presence_rate_pct", "usage_rate_prev_pct",
        "usage_delta_pp", "plan_min_pct", "plan_max_pct", "plan_deviation_pp", "corridor_status",
        "sharp_change_flag", "is_release_patch", "avg_damage_k", "avg_damage_prev_k",
        "clear_rate_pct", "avg_clear_time_sec"]].copy()
    for c in fact.select_dtypes("float").columns:
        fact[c] = fact[c].round(2)
    fact = fact.sort_values(["period_id", "character_id"]).reset_index(drop=True)
    step("T12 Итоговая таблица фактов", len(df), len(fact))
    return fact, dim_char, dp


# -------------------------------------------------------------------- LOAD
def load(fact, dim_char, dim_period, n_raw):
    print("[L] Load")
    OUT.mkdir(parents=True, exist_ok=True)
    dim_period = dim_period.copy()
    for c in ["start_date", "end_date", "month_start"]:
        dim_period[c] = dim_period[c].dt.strftime("%Y-%m-%d")
    fact = fact.copy()
    fact["cycle_date"] = fact["cycle_date"].dt.strftime("%Y-%m-%d")

    files = {"fact_abyss_usage.csv": fact, "dim_character.csv": dim_char,
             "dim_period.csv": dim_period}
    for fname, frame in files.items():
        frame.to_csv(OUT / fname, index=False, encoding="utf-8-sig", lineterminator="\n")
        print(f"  {fname}: {len(frame)} строк")

    # Контроль целостности модели
    assert fact["period_id"].isin(dim_period["period_id"]).all()
    assert fact["character_id"].isin(dim_char["character_id"]).all()
    assert not fact.duplicated(["period_id", "character_id"]).any()
    assert (fact["users"] <= fact["owners"]).all()

    lines = ["# Журнал ETL и проверок качества данных", "",
             f"Строк в сыром файле: **{n_raw}**; строк в таблице фактов: **{len(fact)}**.", "",
             "| Шаг | Строк до | Строк после | Примечание |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in log]
    lines += ["", "## Итоговые проверки", "",
              "- все period_id факта есть в dim_period;",
              "- все character_id факта есть в dim_character;",
              "- ключ (period_id, character_id) уникален;",
              "- users ≤ owners во всех строках.",
              "", "## Сводка по статусу коридора (все периоды)", "",
              fact["corridor_status"].value_counts().rename_axis("Статус")
              .reset_index(name="Строк").to_markdown(index=False)]
    (OUT / "dq_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  dq_report.md")


def main():
    raw, chars, meta, cal = extract()
    fact, dim_char, dim_period = transform(raw, chars, meta, cal)
    load(fact, dim_char, dim_period, len(raw))


if __name__ == "__main__":
    main()
