"""
test_pipeline_obs.py
====================
Unit tests for pipeline_obs.py: wind_dd_to_huong_gio, ww_code_to_mega, and
build_obs (the 6-key obs adapter scoring/scorer.py expects).
"""

from bulletin.decode import decode_qt_file
from pipeline_obs import build_obs, ww_code_to_mega, wind_dd_to_huong_gio
from scoring.score_tables import BUCKETS

LABELS = BUCKETS["huong_gio"]["labels"]


# =============================================================================
# wind_dd_to_huong_gio
# =============================================================================

def test_wind_dd_to_huong_gio_cardinals():
    assert wind_dd_to_huong_gio(0) == LABELS.index("N")
    assert wind_dd_to_huong_gio(90) == LABELS.index("E")
    assert wind_dd_to_huong_gio(180) == LABELS.index("S")
    assert wind_dd_to_huong_gio(270) == LABELS.index("W")


def test_wind_dd_to_huong_gio_n_wraps_both_neighbouring_decades():
    """N owns 3 decades (350, 0, 10) — both the decade just below 360 and
    the one just above 0 must resolve to N."""
    assert wind_dd_to_huong_gio(350) == LABELS.index("N")
    assert wind_dd_to_huong_gio(10) == LABELS.index("N")


def test_wind_dd_to_huong_gio_intercardinal():
    assert wind_dd_to_huong_gio(40) == LABELS.index("NE")
    assert wind_dd_to_huong_gio(220) == LABELS.index("SW")


def test_wind_dd_to_huong_gio_none_is_calm_or_variable():
    assert wind_dd_to_huong_gio(None) is None


# =============================================================================
# ww_code_to_mega
# =============================================================================

def test_ww_code_to_mega_dong_mua_rao_group():
    for code in ["13", "17", "18", "19", "99"]:
        assert ww_code_to_mega(code) == "dong_mua_rao"


def test_ww_code_to_mega_mua_mua_phun_group():
    for code in ["20", "50", "60", "61"]:
        assert ww_code_to_mega(code) == "mua_mua_phun"


def test_ww_code_to_mega_suong_mu_group():
    assert ww_code_to_mega("40") == "suong_mu"
    assert ww_code_to_mega("28") == "suong_mu"


def test_ww_code_to_mega_mu_mu_kho_group():
    assert ww_code_to_mega("10") == "mu_mu_kho"
    assert ww_code_to_mega("04") == "mu_mu_kho"


def test_ww_code_to_mega_n_0_group():
    assert ww_code_to_mega("00") == "N_0"
    assert ww_code_to_mega("66") == "N_0"  # rare mưa đông kết, VN edge case


def test_ww_code_to_mega_distinguishes_identical_labels_by_raw_code():
    """64/65 and 82 both decode to the Vietnamese label 'Mưa to' but must
    land in different mega-buckets — this only works if the lookup keys on
    the raw ww code, not the translated label."""
    assert ww_code_to_mega("64") == "mua_mua_phun"
    assert ww_code_to_mega("65") == "mua_mua_phun"
    assert ww_code_to_mega("82") == "dong_mua_rao"


def test_ww_code_to_mega_none():
    assert ww_code_to_mega(None) is None


def test_ww_code_to_mega_unknown_code():
    assert ww_code_to_mega("zz") is None


# =============================================================================
# build_obs
# =============================================================================

def test_build_obs_real_fixture_yenbai(qt_00):
    """Hand-verified against Qt26081000.txt's first (Yên Bái) record — same
    record test_pipeline_csv.py's flatten_record test is anchored to."""
    records = decode_qt_file(qt_00)
    obs = build_obs(records[0], hour=0)
    assert obs == {
        "hour": 0,
        "tong_luong_may": 8,
        "do_cao_man_may": 1400,   # solve_ceiling: Sc layer, amount 8 >= threshold
        "hien_tuong": "mu_mu_kho",  # ww_code '10' -> Mù
        "huong_gio": LABELS.index("N"),
        "toc_do_gio": 0,
        "tam_nhin": 8.0,
    }


def test_build_obs_missing_groups_come_back_none():
    """A record with none of the optional groups reported (only location) —
    every derived field must come back None, not raise on a missing dict."""
    record = {"location": {"station_code": "k31"}}
    obs = build_obs(record, hour=5)
    assert obs == {
        "hour": 5,
        "tong_luong_may": None,
        "do_cao_man_may": None,
        "hien_tuong": None,
        "huong_gio": None,
        "toc_do_gio": None,
        "tam_nhin": None,
    }


def test_build_obs_cloud_none_vs_no_layers():
    """record['cloud'] absent (key never set) means "no report" -> solve_ceiling
    gets None -> do_cao_man_may None; an explicit empty list means "observed,
    no low/mid layers" -> NO_CEILING, a different value entirely."""
    from scoring.score_tables import NO_CEILING

    assert build_obs({}, hour=0)["do_cao_man_may"] is None
    assert build_obs({"cloud": []}, hour=0)["do_cao_man_may"] == NO_CEILING
