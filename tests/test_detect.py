"""Cut detection on generated audio (acceptance tests 3, 4 and 5, plus edge cases)."""

import numpy as np
import pytest

from audio_assembler.core.detect import DetectionSettings, detect_segments
from audio_assembler.core.errors import DetectionError
from audiogen import make_track

AUTO = DetectionSettings()


def detect(track, settings=AUTO, expected=None):
    return detect_segments(track.samples[:, 0], track.rate, settings, expected, "test.wav")


def assert_segments_match(det, track):
    """Every detected segment contains exactly one true segment, completely (no clipping)."""
    assert len(det.segments) == len(track.segments)
    margin = round(0.1 * track.rate)
    for seg, (a, b) in zip(det.segments, track.segments):
        assert seg.start <= a and seg.end >= b, "speech would be clipped"
        assert a - seg.start <= margin + 0.03 * track.rate
        assert seg.end - b <= margin + 0.03 * track.rate


def test3_short_cut_pauses_auto():
    """Test 3: cut pauses 1 s, natural pauses 0.3 s. Automatic mode cuts correctly."""
    track = make_track([3, 5, 1, 4, 6, 2, 3], cut_pause=1.0, natural_pause=0.3, seed=3)
    det = detect(track)
    assert det.cut_auto and det.cut_method == "automatic"
    assert 0.3 < det.min_cut_seconds < 1.0
    assert_segments_match(det, track)
    assert det.warnings == []


def test4_ambiguous_pauses_stop_and_show_lengths():
    """Test 4: cut and natural pauses nearly the same. Automatic mode stops and shows the lengths."""
    track = make_track([4, 4, 4, 4, 4], cut_pause=lambda r: r.uniform(0.85, 1.0),
                       natural_pause=lambda r: r.uniform(0.7, 0.9), seed=4)
    with pytest.raises(DetectionError) as e:
        detect(track)
    err = e.value
    assert len(err.pause_lengths) == len(track.cut_pauses) + len(track.natural_pauses)
    assert "Longest pauses found" in err.text()
    assert "manually" in err.fix


@pytest.mark.parametrize("min_cut,expected", [(0.6, 7), (0.2, 3 + 5 + 1 + 4 + 6 + 2 + 3), (2.0, 1)])
def test5_manual_cut_length(min_cut, expected):
    """Test 5: a manual minimum silence length gives the expected segment count."""
    track = make_track([3, 5, 1, 4, 6, 2, 3], cut_pause=1.0, natural_pause=0.3, seed=5)
    det = detect(track, DetectionSettings(min_cut_seconds=min_cut))
    assert det.cut_method == "manual"
    assert len(det.segments) == expected


def test_long_cuts_like_production_files():
    track = make_track([4, 6, 2, 8, 3], cut_pause=lambda r: r.uniform(14.8, 15.2),
                       natural_pause=lambda r: r.uniform(0.2, 0.9), seed=6)
    det = detect(track)
    assert_segments_match(det, track)
    assert all(14 < c < 16 for c in det.cut_lengths)


def test_leading_and_trailing_silence_ignored():
    track = make_track([3, 3, 3], cut_pause=15.0, natural_pause=0.4, lead=15.0, trail=15.0, seed=7)
    det = detect(track)
    assert len(det.segments) == 3
    assert det.leading_silence > 14.5 and det.trailing_silence > 14.5
    assert_segments_match(det, track)


def test_digital_silence_without_noise():
    track = make_track([2, 3, 2], cut_pause=3.0, natural_pause=0.3, noise_db=None, seed=8)
    assert_segments_match(detect(track), track)


def test_noisy_background():
    track = make_track([3, 4, 2, 5], cut_pause=4.0, natural_pause=0.35, noise_db=-42, seed=9)
    assert_segments_match(detect(track), track)


def test_click_inside_cut_silence_is_ignored():
    track = make_track([3, 3, 3], cut_pause=5.0, natural_pause=0.3, seed=10)
    a_end = track.segments[0][1]
    click = a_end + int(2.5 * track.rate)
    track.samples[click:click + 40, 0] = 0.8
    assert_segments_match(detect(track), track)


def test_order_list_settles_uniform_pauses():
    """Single-word segments: every pause is a cut, which is ambiguous without an order list."""
    track = make_track([1, 1, 1, 1, 1], cut_pause=lambda r: r.uniform(1.9, 2.1), natural_pause=0.3, seed=11)
    with pytest.raises(DetectionError):
        detect(track)
    det = detect(track, expected=5)
    assert len(det.segments) == 5
    assert "order list" in det.cut_method


def test_order_list_never_overrides_clear_result():
    track = make_track([3, 4, 2], cut_pause=15.0, natural_pause=0.4, seed=12)
    det = detect(track, expected=4)  # wrong expectation must not change a clear detection
    assert len(det.segments) == 3


def test_unusual_cut_length_is_warned():
    lengths = iter([15.0, 15.0, 4.0, 15.0])
    track = make_track([3, 3, 3, 3, 3], cut_pause=lambda r: next(lengths), natural_pause=0.3, seed=13)
    det = detect(track)
    assert len(det.segments) == 5
    assert any("cut 3" in w for w in det.warnings)


def test_silent_file_is_reported():
    silent = np.zeros(16000 * 3, np.float32)
    with pytest.raises(DetectionError):
        detect_segments(silent, 16000, AUTO, None, "silent.wav")
