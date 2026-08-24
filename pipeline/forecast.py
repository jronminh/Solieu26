"""
pipeline/forecast.py
====================
Dựng bảng dự báo theo giờ từ các bản ghi {station_code, start_hour, end_hour,
field_name, bucket_selected} do dự báo viên chọn (mỗi field 1 bucket rời rạc,
không nhập giá trị tự do).
Chạy trực tiếp (python -m pipeline.forecast) để xem demo trên
tests/fixtures/forecast_sample.csv.
"""

import csv
import os

from core.score_tables import BUCKETS
from core.scorer import sub_of_hour
from utils.csv_utils import write_csv

FIELD_ORDER = list(BUCKETS.keys())

# Nhóm field theo cấu trúc bucket khai báo trong BUCKETS - dispatch tường
# minh theo field_name, không qua 1 nhãn "kind" chung (xem TODO.md).
WINDOW_FIELDS = ("tong_luong_may", "toc_do_gio")
LINEAR_FIELDS = ("do_cao_man_may", "tam_nhin")
CIRCULAR_FIELDS = ("huong_gio",)
# "hien_tuong" xử lý riêng (mega_buckets), không thuộc 3 nhóm trên.


def _valid_bucket(field_name: str, bucket_selected) -> bool:
    """bucket_selected có hợp lệ với field_name theo BUCKETS không."""
    if field_name == "hien_tuong":
        return bucket_selected in BUCKETS["hien_tuong"]["mega_buckets"]

    if not isinstance(bucket_selected, int) or isinstance(bucket_selected, bool):
        return False
    if field_name in WINDOW_FIELDS:
        n = len(BUCKETS[field_name]["windows"])
    elif field_name in LINEAR_FIELDS:
        n = len(BUCKETS[field_name]["bounds"]) + 1
        if BUCKETS[field_name].get("no_ceiling") is not None:
            n += 1
    elif field_name in CIRCULAR_FIELDS:
        n = BUCKETS[field_name]["n"]
    else:
        return False
    return 0 <= bucket_selected < n


def _build_station_block(station_code, station_records: list) -> list:
    """1 trạm: gộp station_records (đã lọc đúng station_code này) thành 24
    dòng/giờ, cùng luật merge/overlap như trước (start_hour muộn hơn thắng)."""
    by_start_hour = sorted(station_records, key=lambda r: r["start_hour"])

    bucket_at = {}   # (hour, field_name) -> bucket_selected
    for r in by_start_hour:
        for hour in range(r["start_hour"], r["end_hour"] + 1):
            bucket_at[(hour, r["field_name"])] = r["bucket_selected"]

    return [
        {"station_code": station_code,
         "hour": hour,
         "buoi": sub_of_hour(hour),
         **{field: bucket_at.get((hour, field)) for field in FIELD_ORDER}}
        for hour in range(24)
    ]


def build_hourly_table(records: list) -> list:
    """
    records: list các dict {station_code, start_hour, end_hour, field_name,
    bucket_selected}, mỗi bản ghi áp dụng cho MỌI giờ trong đoạn [start_hour,
    end_hour] (bao gồm 2 đầu) của đúng station_code đó. Validate từng bản ghi
    trước khi gộp: sai bất kỳ bản ghi nào (field_name lạ hoặc bucket_selected
    ngoài phạm vi BUCKETS) thì raise ValueError ngay, không nhận 1 phần.

    Trả về 24 dòng (giờ 0-23) cho mỗi station_code tìm thấy trong records, sort
    theo (station_code, hour); records rỗng thì trả về [] (không trạm nào để
    dựng bảng). Mỗi dòng đủ khoá "station_code"+"hour"+"buoi" (buoi tự suy từ
    hour qua sub_of_hour(), không phải dự báo viên chọn) cộng 6 tên field
    trong BUCKETS; giờ không có bản ghi nào phủ thì field đó là None.

    2 bản ghi cùng (station_code, field_name) chồng giờ nhau: bản ghi
    start_hour muộn hơn thắng (duyệt theo thứ tự start_hour tăng dần, ghi
    đè bản ghi cũ), luật này áp riêng trong phạm vi từng trạm.
    """
    for r in records:
        if r["field_name"] not in BUCKETS:
            raise ValueError(
                f"field_name {r['field_name']!r} không hợp lệ "
                f"(hợp lệ: {', '.join(BUCKETS.keys())})")
        if not _valid_bucket(r["field_name"], r["bucket_selected"]):
            raise ValueError(
                f"bucket_selected {r['bucket_selected']!r} không hợp lệ "
                f"cho field_name {r['field_name']!r}")

    by_station = {}
    for r in records:
        by_station.setdefault(r["station_code"], []).append(r)

    rows = []
    for station_code in sorted(by_station):
        rows.extend(_build_station_block(station_code, by_station[station_code]))
    return rows


def load_records_csv(path: str) -> list:
    """Đọc CSV 5 cột (station_code,start_hour,end_hour,field_name,
    bucket_selected) -> list bản ghi cho build_hourly_table(). station_code
    giữ nguyên string; ép start_hour/end_hour/bucket_selected sang int, TRỪ
    bucket_selected của hien_tuong giữ nguyên string (mega). Không validate
    ở đây - build_hourly_table() làm hết, để 1 chỗ duy nhất chịu trách
    nhiệm đúng/sai dữ liệu."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    records = []
    for r in rows:
        bucket_selected = r["bucket_selected"]
        if r["field_name"] != "hien_tuong":
            bucket_selected = int(bucket_selected)
        records.append({
            "station_code": r["station_code"],
            "start_hour": int(r["start_hour"]),
            "end_hour": int(r["end_hour"]),
            "field_name": r["field_name"],
            "bucket_selected": bucket_selected,
        })
    return records


def export_forecast_table(records: list, date_str: str, out_dir: str) -> dict:
    """Lưu records (đúng shape load_records_csv() đọc/trả về, chưa qua
    build_hourly_table()) ra out_dir/forecast_YYYYMMDD.csv: archive độc lập
    cho 1 ngày dự báo viên chọn, không gắn với obs (obs có thể chưa tồn tại
    khi dự báo cho ngày tương lai).

    date_str: "YYYY-MM-DD" do dự báo viên chọn, vì records chỉ mang giờ
    trong ngày, không mang ngày.

    Trả về {"csv": path, "records": len(records)}; records rỗng thì
    write_csv() không tạo file trên đĩa."""
    out_path = os.path.join(out_dir, f"forecast_{date_str.replace('-', '')}.csv")
    write_csv(out_path, records)
    return {"csv": out_path, "records": len(records)}


if __name__ == "__main__":
    records = load_records_csv("tests/fixtures/forecast_sample.csv")
    for row in build_hourly_table(records):
        print(row)
