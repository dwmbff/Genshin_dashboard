// Load: загрузка подготовленных CSV в модель Power BI (Power Query, язык M)
//
// Как использовать:
// 1. Power BI Desktop -> Главная -> Преобразовать данные -> Создать параметр
//    Имя: DataFolder, Тип: Текст, Значение: путь к папке data\processed
//    например  C:\Projects\Genshin_dashboard\data\processed\
// 2. Создать -> Пустой запрос -> Расширенный редактор -> вставить каждый
//    запрос ниже как отдельный запрос с указанным именем.
// 3. Закрыть и применить. При повторном прогоне ETL достаточно нажать «Обновить».
//
// Culture "en-US" задана явно: в CSV десятичный разделитель — точка,
// и это не должно зависеть от региональных настроек Windows.

// ---------- Запрос: dim_period
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_period.csv"),
                 [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"period_id", type text}, {"version", type text}, {"phase", Int64.Type},
                 {"period_label", type text}, {"start_date", type date}, {"end_date", type date},
                 {"period_order", Int64.Type}, {"version_order", Int64.Type},
                 {"year", Int64.Type}, {"month_start", type date}}, "en-US")
in
    Typed

// ---------- Запрос: dim_character
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_character.csv"),
                 [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"character_id", Int64.Type}, {"name_en", type text}, {"name_ru", type text},
                 {"element", type text}, {"weapon", type text}, {"rarity", type text},
                 {"region", type text}, {"role", type text}, {"banner_type", type text},
                 {"release_version", type text}, {"release_version_sort", type number}}, "en-US")
in
    Typed

// ---------- Запрос: fact_abyss_usage
let
    Source   = Csv.Document(File.Contents(DataFolder & "fact_abyss_usage.csv"),
                 [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"record_id", Int64.Type}, {"period_id", type text}, {"character_id", Int64.Type},
                 {"cycle_date", type date}, {"players", Int64.Type}, {"owners", Int64.Type},
                 {"users", Int64.Type}, {"owner_rate_pct", type number},
                 {"usage_rate_pct", type number}, {"presence_rate_pct", type number},
                 {"usage_rate_prev_pct", type number}, {"usage_delta_pp", type number},
                 {"plan_min_pct", type number}, {"plan_max_pct", type number},
                 {"plan_deviation_pp", type number}, {"corridor_status", type text},
                 {"sharp_change_flag", Int64.Type}, {"is_release_patch", Int64.Type},
                 {"avg_damage_k", type number}, {"avg_damage_prev_k", type number},
                 {"clear_rate_pct", type number}, {"avg_clear_time_sec", type number}}, "en-US")
in
    Typed

// ---------- Связи модели (Представление модели)
// dim_period[period_id]       1 — * fact_abyss_usage[period_id]
// dim_character[character_id] 1 — * fact_abyss_usage[character_id]
// Направление фильтрации: одностороннее, от измерений к факту.
// dim_period[period_label]  -> Сортировать по столбцу period_order
// dim_period[version]       -> Сортировать по столбцу version_order
