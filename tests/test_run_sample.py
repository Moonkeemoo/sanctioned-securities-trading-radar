import shutil
from pathlib import Path
from radar.run import run_pipeline

FIX = Path(__file__).parent / "fixtures"

def test_pipeline_runs_on_sample(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()  # noqa: E702
    # map fixtures to the raw filenames stage1 expects
    shutil.copy(FIX / "opensanctions_securities.ftm.json", raw / "securities.ftm.json")
    shutil.copy(FIX / "opensanctions_entities.ftm.json", raw / "entities.ftm.json")
    shutil.copy(FIX / "gleif_isin_lei.csv", raw / "isin_lei.csv")
    shutil.copy(FIX / "gleif_rr.csv", raw / "rr.csv")

    run_pipeline(raw_dir=raw, interim_dir=tmp_path / "interim",
                 out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                 sample=True, fetched_at="2026-06-02")

    report = (tmp_path / "out" / "report.md").read_text()
    assert "# Feasibility Funnel" in report
    assert (tmp_path / "out" / "candidates.csv").exists()
