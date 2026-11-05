# UZEX deals agent

ИИ-агент, отвечающий на вопросы о биржевых сделках (RU / UZ) строго по данным реестра.
Gemini (function calling) → инструменты `lookup` и `run_sql` над DuckDB (Parquet в памяти) → программная проверка чисел и имён в ответе.

- `build/build_data.py` — нормализация исходных CSV в Parquet
- `app/` — агент, инструменты, промпт, валидатор
- `api/index.py` — FastAPI (Vercel function), `public/index.html` — веб-чат
- `eval/` — эталонные вопросы (ответы посчитаны SQL независимо от агента) и прогонщик

Переменная окружения: `GEMINI_API_KEY`.
