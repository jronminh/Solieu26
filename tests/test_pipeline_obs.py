"""
test_pipeline_obs.py
====================
Unit tests for pipeline/obs.py: wind_dd_to_huong_gio, ww_code_to_mega,
build_obs (the 6-key obs adapter scoring/scorer.py expects), and
build_scalar_history (24-file/day loop on top of build_obs).
"""

import datetime
import os
import shutil

from bulletin.decode import decode_qt_file
from pipeline.obs import build_obs, build_scalar_history, ww_code_to_mega, wind_dd_to_huong_gio
from scoring.score_tables import BUCKETS
from utils.filename_utils import quantrac_filename_at

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
    """Không báo cáo ww -> "N_0" (không có gì đáng kể), không phải None -
    thiếu dữ liệu thật chỉ xảy ra khi mã CÓ báo cáo nhưng không khớp nhóm
    nào (xem test_ww_code_to_mega_unknown_code)."""
    assert ww_code_to_mega(None) == "N_0"


def test_ww_code_to_mega_unknown_code():
    assert ww_code_to_mega("zz") is None


# =============================================================================
# build_obs
# =============================================================================

def test_build_obs_real_fixture_yenbai(qt_00):
    """Hand-verified against Qt26081000.txt's first (Yên Bái) record — same
    record test_pipeline_decode.py's flatten_record test is anchored to."""
    records = decode_qt_file(qt_00)
    obs = build_obs(records[0], hour=0)
    assert obs == {
        "hour": 0,
        "buoi": "dem",
        "station": "Yên Bái",
        "tong_luong_may": 8,
        "do_cao_man_may": 1400,   # solve_ceiling: Sc layer, amount 8 >= threshold
        "hien_tuong": "mu_mu_kho",  # ww_code '10' -> Mù
        "huong_gio": LABELS.index("N"),
        "toc_do_gio": 0,
        "tam_nhin": 8.0,
    }


def test_build_obs_missing_groups_come_back_none_except_hien_tuong_and_buoi():
    """A record with none of the optional groups reported (only location) —
    5 field + station ra None (thiếu dữ liệu thật), không raise trên dict
    thiếu. Riêng hien_tuong ra "N_0" (không báo cáo ww = không có gì đáng
    kể, xem ww_code_to_mega()) và buoi luôn tính được từ hour truyền vào
    (giờ 5 -> "sang") - 2 trường này không phụ thuộc record có báo cáo gì
    hay không."""
    record = {"location": {"station_code": "k31"}}
    obs = build_obs(record, hour=5)
    assert obs == {
        "hour": 5,
        "buoi": "sang",
        "station": None,
        "tong_luong_may": None,
        "do_cao_man_may": None,
        "hien_tuong": "N_0",
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


# =============================================================================
# build_scalar_history
# =============================================================================

FIELD_KEYS = {"hour", "buoi", "station", "tong_luong_may", "do_cao_man_may", "hien_tuong",
              "huong_gio", "toc_do_gio", "tam_nhin"}


def test_build_scalar_history_full_day_has_24_rows_in_order(full_day_dir):
    history = build_scalar_history(full_day_dir)

    assert list(history.keys()) == ["2026-08-10"]
    rows = history["2026-08-10"]
    assert [r["hour"] for r in rows] == list(range(24))
    for r in rows:
        assert set(r.keys()) == FIELD_KEYS


def test_build_scalar_history_hour_0_matches_build_obs_on_first_station(full_day_dir, qt_00):
    """Giờ 0 phải khớp build_obs() gọi tay trên bản ghi ĐẦU TIÊN có
    location của Qt26081000.txt (Yên Bái) - cùng bản ghi
    test_build_obs_real_fixture_yenbai đã hand-verify."""
    rows = build_scalar_history(full_day_dir)["2026-08-10"]

    first_record = next(r for r in decode_qt_file(qt_00) if r.get("location"))
    assert rows[0] == build_obs(first_record, hour=0)


def test_build_scalar_history_missing_hour_files_get_empty_rows_not_skipped(tmp_path, full_day_dir):
    """Chỉ copy 3/24 file vào thư mục tạm - vẫn đủ 24 dòng (không raise,
    không bỏ giờ), 3 giờ có file thì có station/dữ liệu thật, 21 giờ còn
    lại là dòng rỗng (station + 6 field None, hour/buoi vẫn suy được)."""
    kept_hours = [0, 5, 23]
    for hour in kept_hours:
        name = quantrac_filename_at(datetime.datetime(2026, 8, 10, hour))
        shutil.copy(os.path.join(full_day_dir, name), tmp_path / name)

    rows = build_scalar_history(str(tmp_path))["2026-08-10"]

    assert [r["hour"] for r in rows] == list(range(24))
    for r in rows:
        if r["hour"] in kept_hours:
            assert r["station"] is not None
        else:
            assert r["station"] is None
            assert r["tong_luong_may"] is None
            assert r["do_cao_man_may"] is None
            assert r["hien_tuong"] is None
            assert r["huong_gio"] is None
            assert r["toc_do_gio"] is None
            assert r["tam_nhin"] is None


def test_build_scalar_history_empty_dir_returns_empty_dict(tmp_path):
    """Không file nào parse được ngày -> không có gì để neo 24 giờ vào -
    khác test trên (thư mục rỗng thật, không phải thiếu vài giờ)."""
    assert build_scalar_history(str(tmp_path)) == {}


def test_build_scalar_history_multi_date_dir_splits_per_date(tmp_path, full_day_dir, qt_other_day):
    """1 thư mục có file của 2 ngày khác nhau -> 2 entry riêng, mỗi entry
    đủ 24 dòng, không lẫn giờ giữa 2 ngày."""
    name_10 = quantrac_filename_at(datetime.datetime(2026, 8, 10, 0))
    shutil.copy(os.path.join(full_day_dir, name_10), tmp_path / name_10)
    shutil.copy(qt_other_day, tmp_path / os.path.basename(qt_other_day))

    history = build_scalar_history(str(tmp_path))

    assert set(history.keys()) == {"2026-08-10", "2026-08-11"}
    for rows in history.values():
        assert [r["hour"] for r in rows] == list(range(24))
