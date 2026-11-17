"""Acceptance tests 1 and 2 with real files (never part of the public repository).

Expected files: TEST_LV.<audio>, TEST_EN.<audio>, TEST_ORDER.csv, TEST_ORDER_BROKEN.csv
Location: the folder named in AUDIO_ASSEMBLER_TEST_DATA, else test_data/ inside this project,
else test_data/ next to this project folder.
"""

import os
from pathlib import Path

import pytest

from audio_assembler.core import Job, OrderListError, Settings, assemble, export, prepare
from audio_assembler.core.audio_io import AUDIO_EXTENSIONS, decode

def _data_folder() -> Path:
    if os.environ.get("AUDIO_ASSEMBLER_TEST_DATA"):
        return Path(os.environ["AUDIO_ASSEMBLER_TEST_DATA"])
    project = Path(__file__).resolve().parents[1]
    inside = project / "test_data"
    return inside if inside.is_dir() else project.parent / "test_data"


DATA = _data_folder()


def find(stem):
    for ext in AUDIO_EXTENSIONS:
        p = DATA / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


LV, EN = find("TEST_LV"), find("TEST_EN")
ORDER, BROKEN = DATA / "TEST_ORDER.csv", DATA / "TEST_ORDER_BROKEN.csv"
pytestmark = pytest.mark.skipif(not (LV and EN and ORDER.is_file()), reason="user test files not in test_data/")


def test1_user_files(tmp_path):
    job = Job(str(LV), str(EN), str(ORDER), "LV", "EN", Settings(), output_dir=str(tmp_path))
    plan = prepare(job)
    lv, en = plan.tracks
    assert lv.detection.cut_auto and en.detection.cut_auto
    assert len(lv.detection.segments) == 9
    assert len(en.detection.segments) == 7
    assert en.detection.leading_silence > 1.0      # EN leading silence ignored
    assert lv.detection.trailing_silence > 1.0     # LV trailing silence ignored
    assert len(plan.order.rows) == 16
    assert plan.order.total_gap == pytest.approx(30.0)

    result = export(plan)
    out, rate, _ = decode(str(result.output_path))
    assert abs(out.shape[0] / rate - plan.duration) < 0.2
    # No clicks / no clipped speech: every placed segment begins and ends in silence.
    for t in plan.tracks:
        for seg in t.detection.segments:
            assert not seg.near_edge, f"{t.label} segment {seg.number} has sound at its edge"
    print(result.report_path.read_text(encoding="utf-8"))


@pytest.mark.skipif(not BROKEN.is_file(), reason="TEST_ORDER_BROKEN.csv not in test_data/")
def test2_user_files_broken(tmp_path):
    job = Job(str(LV), str(EN), str(BROKEN), "LV", "EN", Settings(), output_dir=str(tmp_path))
    with pytest.raises(OrderListError) as e:
        assemble(job)
    text = e.value.text()
    print(text)
    assert "Row 4" in text and "EN segment 8 does not exist" in text and "EN has only 7 segments" in text
    assert not list(tmp_path.iterdir())
