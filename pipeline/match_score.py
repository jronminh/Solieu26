"""
pipeline/match_score.py
====================
Matcher (join_forecast_obs) + chấm điểm (score_history) - xem TODO.md mục
"Matcher ghép cặp dự báo ↔ quan trắc". pipeline/forecast.py::build_hourly_table()
và pipeline/obs.py::build_scalar_history() đều trả về 1 list LUÔN đủ 24
dòng/giờ (0-23), cùng bộ khóa "hour"+"buoi"+"station"+6 field (khác nhau ở
giá trị):

  join_forecast_obs()    ghép 2 list đó theo khoá "hour", không tự
                          decode/đọc file gì cả. Chưa phân biệt nhiều trạm
                          quan trắc/giờ (mỗi giờ quan trắc hiện chỉ có 1 trạm
                          đại diện, xem build_scalar_history()) - ghép theo
                          trạm để dành cho khi có nhu cầu multi-trạm thật.
  score_history()         chấm từng cặp (forecast, obs) đã ghép bằng
                          scoring/scorer.py's score_<field>(), pivot ngược
                          lại thành 1 dòng/(giờ, field).
  export_forecast_score() điểm vào cho caller (runner.py) - gọi
                          build_hourly_table/build_scalar_history/
                          join_forecast_obs/score_<field> bên trên, làm
                          phẳng thành cột rồi GHI 1 file forecast_YYYYMMDD.csv/
                          ngày ra out_dir, trả về {"YYYY-MM-DD": {"csv","records"}}
                          - đúng vai trò + đúng quy ước trả về
                          pipeline/decode_files.py::export_history_by_date().

Chạy trực tiếp (python -m pipeline.match_score) để xem demo trên
tests/fixtures/forecast_sample.csv ghép với
tests/fixtures/qt_files/full_day_20260810/.
"""

import os

from pipeline.forecast import build_hourly_table
from pipeline.obs import build_scalar_history
from utils.csv_utils import write_csv
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
    forecast_rows: đầu ra pipeline/forecast.py::build_hourly_table() (1
    dict/giờ, đủ "hour"+"buoi"+6 field).
    scalar_history: đầu ra pipeline/obs.py::build_scalar_history() - cùng
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


def export_forecast_score(local_files: list, forecast_records: list, out_dir: str) -> dict:
    """
    local_files: list đường dẫn file QtYYMMDDHH.txt cục bộ đã tải sẵn - cùng
    quy ước với pipeline/decode_files.py::export_history_by_date(); chỉ
    dùng để xác định thư mục chứa chúng (build_scalar_history() tự quét
    thư mục đó để tìm mọi ngày có mặt, có thể nhiều ngày trong 1 lần gọi).
    forecast_records: list bản ghi dự báo viên nhập - cùng hình dạng tham số
    `records` của build_hourly_table(). 1 bảng dự báo dùng CHUNG cho MỌI
    ngày tìm thấy (chưa có khái niệm dự báo riêng theo ngày ở đâu trong code
    - build_hourly_table() cũng không có tham số ngày).
    out_dir: thư mục ghi CSV ra - cùng vai trò out_dir của
    export_history_by_date().

    Với MỖI ngày tìm thấy: ghép forecast+obs theo giờ (join_forecast_obs()),
    chấm cả 6 field/giờ (scoring/scorer.py's score_<field>() qua _SCORERS),
    làm phẳng 3 dict forecast/obs/score thành các cột
    (forecast_<field>/obs_<field>/score_<field>, theo FIELD_ORDER) + cột
    date/hour/buoi/station, rồi ghi ra 1 file forecast_YYYYMMDD.csv/ngày
    (write_csv(), cùng hàm export_history_by_date() dùng) - "buoi" ghi 1
    lần (2 bên luôn tính giống nhau qua sub_of_hour() ở thực tế), station
    lấy từ phía obs (forecast["station"] luôn None, không ghi cột riêng).

    Trả về: {"YYYY-MM-DD": {"csv": path, "records": n}, ...} - đúng quy ước
    export_history_by_date(). local_files rỗng (hoặc thư mục không có ngày
    nào parse được) -> {}.
    """
    forecast_rows = build_hourly_table(forecast_records)

    history_by_date = build_scalar_history(os.path.dirname(local_files[0])) if local_files else {}

    exported = {}
    for date_str, scalar_history in sorted(history_by_date.items()):
        joined = join_forecast_obs(forecast_rows, scalar_history)
        rows = [{
            "date": date_str,
            "hour": j["hour"],
            "buoi": j["obs"]["buoi"],
            "station": j["obs"]["station"],
            **{f"forecast_{field}": j["forecast"][field] for field in FIELD_ORDER},
            **{f"obs_{field}": j["obs"][field] for field in FIELD_ORDER},
            **{f"score_{field}": _SCORERS[field](j["forecast"], j["obs"]) for field in FIELD_ORDER},
        } for j in joined]

        out_path = os.path.join(out_dir, f"forecast_{date_str.replace('-', '')}.csv")
        write_csv(out_path, rows)
        exported[date_str] = {"csv": out_path, "records": len(rows)}
    return exported


if __name__ == "__main__":
    import tempfile

    from pipeline.forecast import build_hourly_table, load_records_csv
    from pipeline.obs import build_scalar_history

    forecast_rows = build_hourly_table(load_records_csv("tests/fixtures/forecast_sample.csv"))
    scalar_history = build_scalar_history("tests/fixtures/qt_files/full_day_20260810")["2026-08-10"]

    joined_rows = join_forecast_obs(forecast_rows, scalar_history)
    print(f"{len(joined_rows)} dòng ghép")
    for row in joined_rows[:3]:
        print(row)

    print()
    scores = score_history(joined_rows)
    print(f"{len(scores)} dòng điểm")
    for row in scores[:12]:
        print(row)

    print()
    with tempfile.TemporaryDirectory() as tmp_dir:
        exported = export_forecast_score(
            ["tests/fixtures/qt_files/full_day_20260810/Qt26081000.txt"],
            load_records_csv("tests/fixtures/forecast_sample.csv"),
            tmp_dir)
        print(f"export_forecast_score: {exported}")
