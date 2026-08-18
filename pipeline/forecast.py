"""
pipeline/forecast.py
====================
Việc dựng lại pipeline dự báo (bản trước đã xoá - xem TODO.md mục VỠ).
Input: nhiều bản ghi {start_hour, end_hour, field_name, bucket_selected} -
dự báo viên chọn 1 BUCKET (không nhập giá trị vô hướng tự do), hợp lệ theo
scoring/score_tables.py.BUCKETS[field_name]. build_hourly_table() gộp lại
thành 1 dòng/giờ, đủ 6 khoá field + "buoi" (tự suy từ giờ dòng đó, xem
scoring/scorer.py::sub_of_hour()) - cùng hình dạng obs bên
scoring/scorer.py, để gọi thẳng score_<field>(forecast_row, obs_row) không
cần biến đổi thêm.

Chạy trực tiếp (python -m pipeline.forecast) để xem demo trên
tests/fixtures/forecast_sample.csv.
"""

import csv

from scoring.score_tables import BUCKETS
from scoring.scorer import sub_of_hour

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


def build_hourly_table(records: list) -> list:
    """
    records: list các dict {start_hour, end_hour, field_name, bucket_selected}
    - bucket_selected áp dụng cho MỌI giờ trong đoạn [start_hour, end_hour]
    (bao gồm 2 đầu). Validate từng bản ghi TRƯỚC khi gộp - sai bất kỳ bản
    ghi nào (field_name lạ hoặc bucket_selected ngoài phạm vi BUCKETS) thì
    raise ValueError ngay, không nhận 1 phần.

    Trả về: list các dict, MỖI PHẦN TỬ 1 GIỜ (trải từ giờ nhỏ nhất đến giờ
    lớn nhất trong records), đủ khoá "hour" + "buoi" (tự suy từ hour qua
    sub_of_hour(), không phải dự báo viên chọn) + 6 tên field trong BUCKETS -
    field không có bản ghi nào phủ giờ đó -> None.

    2 bản ghi CÙNG field_name chồng giờ nhau: bản ghi start_hour muộn hơn
    thắng (duyệt theo thứ tự start_hour tăng dần, ghi đè bản ghi cũ).
    records rỗng -> trả về [].
    """
    if not records:
        return []

    for r in records:
        if r["field_name"] not in BUCKETS:
            raise ValueError(
                f"field_name {r['field_name']!r} không hợp lệ "
                f"(hợp lệ: {', '.join(BUCKETS.keys())})")
        if not _valid_bucket(r["field_name"], r["bucket_selected"]):
            raise ValueError(
                f"bucket_selected {r['bucket_selected']!r} không hợp lệ "
                f"cho field_name {r['field_name']!r}")

    by_start_hour = sorted(records, key=lambda r: r["start_hour"])

    bucket_at = {}   # (hour, field_name) -> bucket_selected
    for r in by_start_hour:
        for hour in range(r["start_hour"], r["end_hour"] + 1):
            bucket_at[(hour, r["field_name"])] = r["bucket_selected"]

    min_hour = min(r["start_hour"] for r in records)
    max_hour = max(r["end_hour"] for r in records)

    return [
        {"hour": hour,
         "buoi": sub_of_hour(hour),
         **{field: bucket_at.get((hour, field)) for field in FIELD_ORDER}}
        for hour in range(min_hour, max_hour + 1)
    ]


def load_records_csv(path: str) -> list:
    """Đọc CSV 4 cột (start_hour,end_hour,field_name,bucket_selected) ->
    list bản ghi cho build_hourly_table(). Ép start_hour/end_hour/
    bucket_selected sang int, TRỪ bucket_selected của hien_tuong giữ nguyên
    string (mega). Không validate ở đây - build_hourly_table() làm hết, để
    1 chỗ duy nhất chịu trách nhiệm đúng/sai dữ liệu."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    records = []
    for r in rows:
        bucket_selected = r["bucket_selected"]
        if r["field_name"] != "hien_tuong":
            bucket_selected = int(bucket_selected)
        records.append({
            "start_hour": int(r["start_hour"]),
            "end_hour": int(r["end_hour"]),
            "field_name": r["field_name"],
            "bucket_selected": bucket_selected,
        })
    return records


if __name__ == "__main__":
    records = load_records_csv("tests/fixtures/forecast_sample.csv")
    for row in build_hourly_table(records):
        print(row)
