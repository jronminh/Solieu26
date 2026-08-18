"""
test_scorer.py
====================
Unit tests for scoring/scorer.py: solve_ceiling and the 6 score_<field>
functions, plus sub_of_hour (the giờ -> buổi mapping score_hien_tuong uses).

Every score_<field>() takes (forecast_row, obs) - 2 whole rows already
synced by hour (pipeline/scoring.py::join_forecast_obs()'s output shape) -
so tests build a 1-key forecast_row dict per case instead of passing a
scalar directly.
"""

from scoring.score_tables import BUCKETS, NO_CEILING
from scoring.scorer import (
    score_do_cao_man_may,
    score_hien_tuong,
    score_huong_gio,
    score_tam_nhin,
    score_toc_do_gio,
    score_tong_luong_may,
    solve_ceiling,
    sub_of_hour,
)

LABELS = BUCKETS["huong_gio"]["labels"]


# =============================================================================
# solve_ceiling
# =============================================================================

def test_solve_ceiling_no_data_is_none():
    assert solve_ceiling(None) is None


def test_solve_ceiling_no_layers_reported_is_no_ceiling():
    assert solve_ceiling([]) == NO_CEILING


def test_solve_ceiling_only_high_clouds_ignored_is_no_ceiling():
    """Ci/Cc/Cs (mây trên) don't count toward the ceiling at all."""
    assert solve_ceiling([{"type": "Ci", "amount": 10, "height": 9000}]) == NO_CEILING


def test_solve_ceiling_below_threshold_is_no_ceiling():
    """Total low+mid amount below CEILING_THRESHOLD (6/10) -> no màn even
    though a layer was observed."""
    assert solve_ceiling([{"type": "Cu", "amount": 3, "height": 500}]) == NO_CEILING


def test_solve_ceiling_single_strong_layer_uses_its_height():
    layers = [{"type": "Sc", "amount": 8, "height": 1400}]
    assert solve_ceiling(layers) == 1400


def test_solve_ceiling_multiple_strong_layers_uses_lowest():
    layers = [{"type": "Cu", "amount": 7, "height": 800}, {"type": "Sc", "amount": 8, "height": 500}]
    assert solve_ceiling(layers) == 500


def test_solve_ceiling_no_single_strong_layer_uses_largest_amount():
    """Neither layer alone reaches 6/10, but their sum does -> take the
    layer with the largest amount, not the lowest."""
    layers = [{"type": "Cu", "amount": 3, "height": 300}, {"type": "Sc", "amount": 4, "height": 900}]
    assert solve_ceiling(layers) == 900


def test_solve_ceiling_tie_on_amount_uses_lower_layer():
    layers = [{"type": "Cu", "amount": 4, "height": 500}, {"type": "Sc", "amount": 4, "height": 300}]
    assert solve_ceiling(layers) == 300


# =============================================================================
# score_tong_luong_may
# =============================================================================

def test_score_tong_luong_may_hit_within_window_tolerance():
    # forecast idx 2 -> window (2,4), ±1 window widens acceptance to (1,5)
    assert score_tong_luong_may({"tong_luong_may": 2}, {"tong_luong_may": 5}) is True


def test_score_tong_luong_may_miss_outside_window_tolerance():
    assert score_tong_luong_may({"tong_luong_may": 0}, {"tong_luong_may": 5}) is False


def test_score_tong_luong_may_clamps_at_edge_windows():
    assert score_tong_luong_may({"tong_luong_may": 8}, {"tong_luong_may": 5}) is False


def test_score_tong_luong_may_none_forecast_or_obs():
    assert score_tong_luong_may({"tong_luong_may": None}, {"tong_luong_may": 5}) is None
    assert score_tong_luong_may({"tong_luong_may": 2}, {"tong_luong_may": None}) is None


def test_score_tong_luong_may_obscured_sky_is_na():
    assert score_tong_luong_may({"tong_luong_may": 2}, {"tong_luong_may": "/"}) is None


# =============================================================================
# score_do_cao_man_may
# =============================================================================

def test_score_do_cao_man_may_no_ceiling_matches_top_bucket():
    assert score_do_cao_man_may({"do_cao_man_may": 14}, {"do_cao_man_may": NO_CEILING}) is True


def test_score_do_cao_man_may_no_ceiling_within_tolerance_of_neighbour():
    assert score_do_cao_man_may({"do_cao_man_may": 13}, {"do_cao_man_may": NO_CEILING}) is True


def test_score_do_cao_man_may_no_ceiling_outside_tolerance():
    assert score_do_cao_man_may({"do_cao_man_may": 12}, {"do_cao_man_may": NO_CEILING}) is False


def test_score_do_cao_man_may_bound_value_falls_in_upper_bucket():
    """side='right': a value equal to a bound (50) belongs to the bucket
    ABOVE it (idx 1, "50-100"), not the one below (idx 0, "<50")."""
    assert score_do_cao_man_may({"do_cao_man_may": 1}, {"do_cao_man_may": 50}) is True
    assert score_do_cao_man_may({"do_cao_man_may": 3}, {"do_cao_man_may": 50}) is False  # off by 2, outside tolerance


def test_score_do_cao_man_may_missing_data_is_none():
    assert score_do_cao_man_may({"do_cao_man_may": 1}, {"do_cao_man_may": None}) is None
    assert score_do_cao_man_may({"do_cao_man_may": None}, {"do_cao_man_may": 50}) is None


# =============================================================================
# score_tam_nhin
# =============================================================================

def test_score_tam_nhin_bound_value_falls_in_upper_bucket():
    assert score_tam_nhin({"tam_nhin": 1}, {"tam_nhin": 0.5}) is True
    assert score_tam_nhin({"tam_nhin": 3}, {"tam_nhin": 0.5}) is False


def test_score_tam_nhin_missing_data_is_none():
    assert score_tam_nhin({"tam_nhin": 1}, {"tam_nhin": None}) is None
    assert score_tam_nhin({"tam_nhin": None}, {"tam_nhin": 5}) is None


# =============================================================================
# score_toc_do_gio
# =============================================================================

def test_score_toc_do_gio_hit_within_window_tolerance():
    assert score_toc_do_gio({"toc_do_gio": 2}, {"toc_do_gio": 5}) is True


def test_score_toc_do_gio_above_no_speed_min_is_none():
    """Observed speed > 15 m/s -> speed itself is never scored (paired with
    direction, which takes over at high wind)."""
    assert score_toc_do_gio({"toc_do_gio": 0}, {"toc_do_gio": 16}) is None


def test_score_toc_do_gio_missing_data_is_none():
    assert score_toc_do_gio({"toc_do_gio": 2}, {"toc_do_gio": None}) is None
    assert score_toc_do_gio({"toc_do_gio": None}, {"toc_do_gio": 5}) is None


# =============================================================================
# score_huong_gio
# =============================================================================

def test_score_huong_gio_wraps_around_compass():
    """N (idx 0) and NNW (idx 15) are adjacent on the compass — ±1 must wrap."""
    assert score_huong_gio({"huong_gio": 0}, {"huong_gio": 15, "toc_do_gio": 5}) is True


def test_score_huong_gio_accepts_string_label_for_obs_dir():
    n_idx = LABELS.index("N")
    assert score_huong_gio({"huong_gio": n_idx}, {"huong_gio": "NNE", "toc_do_gio": 5}) is True


def test_score_huong_gio_calm_wind_drops_direction():
    """Observed speed <= WIND_NO_DIR_MAX (2 m/s) -> direction isn't scored,
    regardless of forecast/obs direction agreement."""
    assert score_huong_gio({"huong_gio": 0}, {"huong_gio": 0, "toc_do_gio": 2}) is None


def test_score_huong_gio_missing_data_is_none():
    assert score_huong_gio({"huong_gio": 0}, {"huong_gio": None, "toc_do_gio": 5}) is None
    assert score_huong_gio({"huong_gio": None}, {"huong_gio": 0, "toc_do_gio": 5}) is None
    assert score_huong_gio({"huong_gio": 0}, {"huong_gio": 0, "toc_do_gio": None}) is None


# =============================================================================
# score_hien_tuong
# =============================================================================

def test_score_hien_tuong_mega_mismatch_is_false():
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": "dem"},
        {"hien_tuong": "suong_mu", "buoi": "dem"}) is False


def test_score_hien_tuong_mega_match_sub_within_tolerance():
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": "dem"},
        {"hien_tuong": "N_0", "buoi": "dem"}) is True


def test_score_hien_tuong_mega_match_sub_outside_tolerance():
    # 'chieu' (idx 4) vs 'dem' (idx 1) -> off by 3, no wrap (sub_circular off)
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": "chieu"},
        {"hien_tuong": "N_0", "buoi": "dem"}) is False


def test_score_hien_tuong_missing_data_is_none():
    assert score_hien_tuong(
        {"hien_tuong": None, "buoi": "dem"},
        {"hien_tuong": "N_0", "buoi": "dem"}) is None
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": "dem"},
        {"hien_tuong": None, "buoi": "dem"}) is None


def test_score_hien_tuong_missing_buoi_is_none():
    """Mega khớp nhưng buổi 1 trong 2 phía không xác định được (nhãn lạ/
    thiếu) -> bỏ cặp, không coi như khớp."""
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": None},
        {"hien_tuong": "N_0", "buoi": "dem"}) is None
    assert score_hien_tuong(
        {"hien_tuong": "N_0", "buoi": "dem"},
        {"hien_tuong": "N_0", "buoi": None}) is None


def test_score_hien_tuong_no_ww_reported_scores_false_not_none():
    """Trạm không báo cáo ww (pipeline/obs.py::ww_code_to_mega(None) ==
    "N_0") mà dự báo lại chọn 1 mega khác "N_0" -> phải chấm SAI (False),
    không bị bỏ cặp."""
    from pipeline.obs import ww_code_to_mega

    obs = {"hien_tuong": ww_code_to_mega(None), "buoi": "dem"}
    forecast_row = {"hien_tuong": "dong_mua_rao", "buoi": "dem"}
    assert score_hien_tuong(forecast_row, obs) is False


# =============================================================================
# sub_of_hour
# =============================================================================

def test_sub_of_hour_covers_every_buổi():
    assert sub_of_hour(19) == "toi"
    assert sub_of_hour(23) == "toi"
    assert sub_of_hour(0) == "dem"
    assert sub_of_hour(4) == "dem"
    assert sub_of_hour(5) == "sang"
    assert sub_of_hour(9) == "sang"
    assert sub_of_hour(10) == "trua"
    assert sub_of_hour(13) == "trua"
    assert sub_of_hour(14) == "chieu"
    assert sub_of_hour(18) == "chieu"


def test_sub_of_hour_wraps_24_to_midnight():
    assert sub_of_hour(24) == "dem"


def test_sub_of_hour_none_is_none():
    assert sub_of_hour(None) is None
