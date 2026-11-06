// Load: загрузка подготовленных CSV в модель Power BI (Power Query, язык M).
// Это те же запросы, что хранятся в проекте dashboard/Genshin_dashboard.pbip;
// файл нужен, если модель собирается вручную в новом отчёте.
//
// 1. Главная -> Преобразовать данные -> Управление параметрами -> Создать параметр
//    DataFolder (Текст) = путь к папке data\processed\ (с \ в конце).
// 2. Создать -> Пустой запрос -> Расширенный редактор: вставить каждый запрос ниже
//    под указанным именем. Порядок важен: «Выбор периода» ссылается на dim_period.
// 3. Связи: dim_period[period_id] 1—* fact_abyss_usage[period_id],
//    dim_character[character_id] 1—* fact_abyss_usage[character_id].
// 4. Сортировка: dim_period[Период] по period_order, 'Выбор периода'[Период] по №.

// ---------- Запрос: dim_period
let
    Source = Csv.Document(File.Contents(DataFolder & "dim_period.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {{"period_id", type text}, {"version", type text}, {"phase", Int64.Type}, {"period_label", type text}, {"start_date", type date}, {"end_date", type date}, {"period_order", Int64.Type}, {"version_order", Int64.Type}, {"year", Int64.Type}, {"month_start", type date}}, "en-US"),
    Renamed = Table.RenameColumns(Typed, {{"version", "Версия"}, {"phase", "Фаза"}, {"period_label", "Период"}, {"start_date", "Начало"}, {"end_date", "Окончание"}, {"year", "Год"}, {"month_start", "Месяц"}})
in
    Renamed

// ---------- Запрос: dim_character
let
    Source = Csv.Document(File.Contents(DataFolder & "dim_character.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {{"character_id", Int64.Type}, {"name_en", type text}, {"name_ru", type text}, {"element", type text}, {"weapon", type text}, {"rarity", type text}, {"region", type text}, {"role", type text}, {"banner_type", type text}, {"release_version", type text}, {"release_version_sort", type number}}, "en-US"),
    Renamed = Table.RenameColumns(Typed, {{"name_en", "Персонаж (англ)"}, {"name_ru", "Персонаж"}, {"element", "Элемент"}, {"weapon", "Оружие"}, {"rarity", "Редкость"}, {"region", "Регион"}, {"role", "Роль"}, {"banner_type", "Тип баннера"}, {"release_version", "Версия выхода"}})
in
    Renamed

// ---------- Запрос: fact_abyss_usage
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_abyss_usage.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {{"record_id", Int64.Type}, {"period_id", type text}, {"character_id", Int64.Type}, {"cycle_date", type date}, {"players", Int64.Type}, {"owners", Int64.Type}, {"users", Int64.Type}, {"owner_rate_pct", type number}, {"usage_rate_pct", type number}, {"presence_rate_pct", type number}, {"usage_rate_prev_pct", type number}, {"usage_delta_pp", type number}, {"plan_min_pct", type number}, {"plan_max_pct", type number}, {"plan_deviation_pp", type number}, {"corridor_status", type text}, {"sharp_change_flag", Int64.Type}, {"is_release_patch", Int64.Type}, {"avg_damage_k", type number}, {"avg_damage_prev_k", type number}, {"clear_rate_pct", type number}, {"avg_clear_time_sec", type number}}, "en-US")
in
    Typed

// ---------- Запрос: Выбор периода
let
    Source = Table.SelectColumns(dim_period, {"Период", "period_order"}),
    Renamed = Table.RenameColumns(Source, {{"period_order", "№"}})
in
    Renamed
