"""
pipeline_scoring.py
====================
Matcher (join_forecast_obs) + chấm điểm (score_history) - xem TODO.md mục
"Matcher ghép cặp dự báo ↔ quan trắc". pipeline_forecast.py::build_hourly_table()
và pipeline_obs.py::build_scalar_history() đều trả về 1 list cùng hình
dạng (1 dict/giờ, đủ "hour"+"buoi"+6 field):

  join_forecast_obs()  ghép 2 list đó theo khoá "hour", không tự
                        decode/đọc file gì cả. Chưa phân biệt trạm (mỗi giờ
                        quan trắc hiện chỉ có 1 trạm đại diện, xem
                        build_scalar_history()) - ghép theo trạm để dành
                        cho khi có nhu cầu multi-trạm thật.
  score_history()       chấm từng cặp (forecast, obs) đã ghép bằng
                        scoring/scorer.py's score_<field>(), pivot ngược
                        lại thành 1 dòng/(giờ, field).

Chạy trực tiếp (python pipeline_scoring.py) để xem demo trên
tests/fixtures/forecast_sample.csv ghép với
tests/fixtures/qt_files/full_day_20260810/.
"""

from scoring.scorer import (
    score_do_cao_man_may,
    score_hien_tuong,
    score_huong_gio,
    score_tam_nhin,
    score_toc_do_gio,
    score_tong_luong_may,
)

# Cùng thứ tự BUCKETS.keys() (score_tables.py) - để mỗi giờ trong
# score_history() ra đúng 6 dòng liên tiếp theo 1 thứ tự cố định.
FIELD_ORDER = ("tong_luong_may", "do_cao_man_may", "hien_tuong", "huong_gio",
               "toc_do_gio", "tam_nhin")

# Cả 6 hàm cùng chữ ký (forecast_row, obs) -> bool|None (scoring/scorer.py) -
# dispatch đồng nhất, không còn ngoại lệ nào.
_SCORERS = {
    "tong_luong_may": score_tong_luong_may,
    "do_cao_man_may": score_do_cao_man_may,
    "hien_tuong": score_hien_tuong,
    "huong_gio": score_huong_gio,
    "toc_do_gio": score_toc_do_gio,
    "tam_nhin": score_tam_nhin,
}


def join_forecast_obs(forecast_rows: list, scalar_history: list) -> list:
    """
    forecast_rows: đầu ra pipeline_forecast.py::build_hourly_table() (1
    dict/giờ, đủ "hour"+"buoi"+6 field).
    scalar_history: đầu ra pipeline_obs.py::build_scalar_history() - cùng
    hình dạng, không mang định danh trạm.

    Ghép theo "hour": mỗi phần tử scalar_history tra thẳng vào
    forecast_rows theo "hour" - giờ nào không có dòng dự báo tương ứng thì
    raise ValueError ngay, không nhận 1 phần.

    Trả về: list dict {"hour": int, "forecast": <dict 8 khoá>,
    "obs": <dict 8 khoá>}. scalar_history rỗng -> trả về [].
    """
    forecast_by_hour = {r["hour"]: r for r in forecast_rows}

    rows = []
    for obs_row in scalar_history:
        hour = obs_row["hour"]
        if hour not in forecast_by_hour:
            raise ValueError(f"giờ {hour} không có dòng dự báo tương ứng")
        rows.append({
            "hour": hour,
            "forecast": forecast_by_hour[hour],
            "obs": obs_row,
        })
    return rows


def score_history(joined_rows: list) -> list:
    """
    joined_rows: đầu ra join_forecast_obs() - mỗi phần tử {"hour",
    "forecast", "obs"}.

    Chấm cả 6 field/dòng bằng scoring/scorer.py's score_<field>() - mỗi hàm
    nhận THẲNG forecast_row/obs_row (2 dòng đã ghép theo giờ), tự đọc field
    nó cần từ mỗi bên (kể cả hien_tuong - đọc thêm "buoi", đã tự suy sẵn
    bởi build_hourly_table()/build_obs()) - dispatch đồng nhất, không còn
    ngoại lệ nào.

    Trả về: list dict {"hour": int, "field_name": str, "score": bool|None} -
    1 phần tử/(giờ, field), theo đúng FIELD_ORDER trong mỗi giờ. score None
    nghĩa là BỎ CẶP (thiếu dữ liệu hoặc rơi vào regime không chấm - vd tốc
    độ gió >15 m/s thì bỏ chấm tốc độ), không phải False.
    """
    rows = []
    for joined in joined_rows:
        hour = joined["hour"]
        forecast_row = joined["forecast"]
        obs_row = joined["obs"]

        for field in FIELD_ORDER:
            score = _SCORERS[field](forecast_row, obs_row)
            rows.append({"hour": hour, "field_name": field, "score": score})
    return rows


if __name__ == "__main__":
    import datetime

    from pipeline_forecast import build_hourly_table, load_records_csv
    from pipeline_obs import build_scalar_history

    forecast_rows = build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))
    scalar_history = build_scalar_history(
        datetime.date(2026, 8, 10), "tests/fixtures/qt_files/full_day_20260810")

    joined_rows = join_forecast_obs(forecast_rows, scalar_history)
    print(f"{len(joined_rows)} dòng ghép")
    for row in joined_rows[:3]:
        print(row)

    print()
    scores = score_history(joined_rows)
    print(f"{len(scores)} dòng điểm")
    for row in scores[:12]:
        print(row)
