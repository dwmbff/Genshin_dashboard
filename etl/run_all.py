"""Полный прогон пайплайна в фиксированном порядке: python etl/run_all.py"""
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
for script in ["00_extract_characters.py", "01_generate_abyss_usage.py", "02_etl_pipeline.py"]:
    print(f"\n=== {script} ===")
    runpy.run_path(str(HERE / script), run_name="__main__")
