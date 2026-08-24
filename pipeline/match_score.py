"""
pipeline/match_score.py
====================
Matcher (join_forecast_obs) + chấm điểm (score_history): ghép bảng dự báo và
quan trắc theo khoá (station_code, hour) rồi chấm 6 field bằng
scoring/scorer.py; export_forecast_score() là điểm vào cho caller, nhận file
CSV dự báo và danh sách file quan trắc cục bộ, ghi ra 1 file
score_YYYYMMDD.csv/ngày.

Chạy trực tiếp (python -m pipeline.match_score) để xem demo trên
tests/fixtures/forecast_sample.csv ghép với
tests/fixtures/qt_files/full_day_20260810/.
"""

import os

from pipeline.forecast import build_hourly_table, load_records_csv
from pipeline.obs import build_scalar_history_from_files
from utils.csv_utils import write_csv
from scoring.scorer import (
    score_do_cao_man_may,
    score_hien_tuong,
    score_huong_gio,
    score_tam_nhin,
    score_toc_do_gio,
    score_tong_luong_may,
    sub_of_hour,
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


def _empty_forecast_row(station_code, hour: int) -> dict:
    """Trạm station_code không có dự báo (không xuất hiện trong
    forecast_rows): 1 dòng dự báo rỗng - 6 field None, "buoi" vẫn suy được
    từ hour - để join_forecast_obs() luôn ghép ra 1 dòng cho MỌI trạm quan
    trắc thực sự báo cáo, kể cả trạm chưa ai dự báo (rồi scorer tự bỏ cặp
    vì thiếu forecast_idx, không phải lỗi)."""
    return {"station_code": station_code, "hour": hour, "buoi": sub_of_hour(hour),
            **{field: None for field in FIELD_ORDER}}


def join_forecast_obs(forecast_rows: list, scalar_history: list) -> list:
    """
    forecast_rows: 1 dict/(trạm, giờ) đủ "station_code"+"hour"+"buoi"+6
    field, có thể chỉ phủ 1 phần các trạm quan trắc được (chỉ trạm có dự
    báo). scalar_history: cùng hình dạng nhưng bao mọi trạm thực sự báo cáo
    hôm đó.

    Ghép do obs dẫn dắt theo khoá (station_code, hour): mỗi phần tử
    scalar_history tra vào forecast_rows theo khoá đó; trạm/giờ nào không có
    dự báo tương ứng thì ghép với 1 dự báo rỗng (_empty_forecast_row())
    thay vì raise hay bỏ qua, giữ đúng mọi trạm quan trắc kể cả chưa ai dự
    báo (điểm sẽ tự bỏ cặp ở tầng scorer).

    Trả về list dict {"station_code": str, "hour": int, "forecast": <dict>,
    "obs": <dict>}; scalar_history rỗng thì trả về [].
    """
    forecast_by_key = {(r["station_code"], r["hour"]): r for r in forecast_rows}

    rows = []
    for obs_row in scalar_history:
        key = (obs_row["station_code"], obs_row["hour"])
        forecast_row = forecast_by_key.get(key) or _empty_forecast_row(*key)
        rows.append({
            "station_code": obs_row["station_code"],
            "hour": obs_row["hour"],
            "forecast": forecast_row,
            "obs": obs_row,
        })
    return rows


def score_history(joined_rows: list) -> list:
    """
    joined_rows: đầu ra join_forecast_obs(), mỗi phần tử {"station_code",
    "hour", "forecast", "obs"}.

    Chấm cả 6 field/dòng bằng score_<field>() tương ứng: mỗi hàm nhận thẳng
    forecast_row/obs_row (2 dòng đã ghép theo (trạm, giờ)) và tự đọc field
    nó cần từ mỗi bên (kể cả hien_tuong, đọc thêm "buoi").

    Trả về list dict {"station_code": str, "hour": int, "field_name": str,
    "score": bool|None}, 1 phần tử/(trạm, giờ, field) theo đúng FIELD_ORDER;
    score None nghĩa là bỏ cặp (thiếu dữ liệu hoặc rơi vào regime không
    chấm, vd tốc độ gió >15 m/s thì bỏ chấm tốc độ), không phải False.
    """
    rows = []
    for joined in joined_rows:
        station_code = joined["station_code"]
        hour = joined["hour"]
        forecast_row = joined["forecast"]
        obs_row = joined["obs"]

        for field in FIELD_ORDER:
            score = _SCORERS[field](forecast_row, obs_row)
            rows.append({"station_code": station_code, "hour": hour,
                         "field_name": field, "score": score})
    return rows


def export_forecast_score(local_files: list, forecast_csv_path: str, out_dir: str) -> dict:
    """
    local_files: list đường dẫn file QtYYMMDDHH.txt cục bộ đã tải sẵn — đúng
    các file này được gộp thành lịch sử quan trắc
    (build_scalar_history_from_files()), không quét thêm gì khác trong thư
    mục chứa chúng; có thể trải nhiều ngày trong 1 lần gọi nếu truyền đủ
    file của các ngày đó.
    forecast_csv_path: đường dẫn 1 file CSV đúng shape load_records_csv()
    đọc được (dự báo viên nhập trực tiếp hoặc file archive từ
    export_forecast_table(), cùng shape nên dùng chung tham số này); falsy
    (None/"") thì coi như chưa có dự báo (records rỗng), và 1 bảng dự báo
    dùng chung cho mọi ngày tìm thấy (chưa có khái niệm dự báo riêng theo
    ngày). out_dir: thư mục ghi CSV ra.

    Với mỗi ngày tìm thấy: ghép forecast+obs theo (station_code, hour) do
    obs dẫn dắt (phủ mọi trạm quan trắc thực sự báo cáo, kể cả trạm chưa ai
    dự báo), chấm cả 6 field/dòng qua _SCORERS, làm phẳng 3 dict
    forecast/obs/score thành các cột (forecast_<field>/obs_<field>/
    score_<field> theo FIELD_ORDER, cộng date/station_code/hour/buoi), rồi
    ghi ra 1 file score_YYYYMMDD.csv/ngày. Số dòng/ngày bằng số trạm quan
    trắc thực sự báo cáo hôm đó nhân 24, kể cả khi forecast_csv_path rỗng
    (forecast toàn None, score toàn bỏ cặp).

    Trả về {"YYYY-MM-DD": {"csv": path, "records": n}, ...}; local_files
    rỗng hoặc không file nào parse được thì trả về {}.
    """
    forecast_records = load_records_csv(forecast_csv_path) if forecast_csv_path else []
    forecast_rows = build_hourly_table(forecast_records)

    history_by_date = build_scalar_history_from_files(local_files)

    exported = {}
    for date_str, scalar_history in sorted(history_by_date.items()):
        joined = join_forecast_obs(forecast_rows, scalar_history)
        rows = [{
            "date": date_str,
            "station_code": j["station_code"],
            "hour": j["hour"],
            "buoi": j["obs"]["buoi"],
            **{f"forecast_{field}": j["forecast"][field] for field in FIELD_ORDER},
            **{f"obs_{field}": j["obs"][field] for field in FIELD_ORDER},
            **{f"score_{field}": _SCORERS[field](j["forecast"], j["obs"]) for field in FIELD_ORDER},
        } for j in joined]

        out_path = os.path.join(out_dir, f"score_{date_str.replace('-', '')}.csv")
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
            "tests/fixtures/forecast_sample.csv",
            tmp_dir)
        print(f"export_forecast_score: {exported}")
