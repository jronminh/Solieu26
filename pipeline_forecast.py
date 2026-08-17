"""
pipeline_forecast.py
====================
Micro-database cho các bản ghi dự báo đã chọn bucket: CRUD trong bộ nhớ
(add/remove/edit_record), import/export CSV, và tra nhãn hiển thị cho từng
bucket theo cấu hình BUCKETS.
"""

import csv

from scoring.score_tables import BUCKETS

# Micro-database: TOÀN BỘ chương trình chỉ có 1 danh sách bản ghi dự báo,
# mỗi bản ghi là 1 dict với đúng 4 khóa:
#   start_hour       : giờ bắt đầu áp dụng (int, 0-23)
#   end_hour         : giờ kết thúc áp dụng, gồm cả giờ này (int, 0-23)
#   data_name        : tên trường dữ liệu (vd "tong_luong_may", "huong_gio")
#   bucket_selected  : giá trị bucket đã chọn cho trường đó
forecast_db: list = []


def export_csv(data_base: list, path: str) -> list:
    """
    data_base: micro-database (list các dict {start_hour, end_hour, data_name,
    bucket_selected}, giống forecast_db).

    Tìm giờ nhỏ nhất trong mọi start_hour và giờ lớn nhất trong mọi end_hour,
    sinh ra từng đó phần tử - một phần tử / giờ - đã điền số liệu ứng với
    giờ đó (2 bản ghi cùng data_name chồng giờ nhau -> bản ghi có start_hour
    muộn hơn thắng), rồi GHI THẲNG ra file CSV tại `path` (utf-8-sig +
    csv.DictWriter).

    Mỗi phần tử của result (và mỗi dòng CSV) là 1 dict
    {"hour": <giờ>, <data_name>: <NHÃN ĐỌC ĐƯỢC>, ...} - giá trị là
    bucket_label(data_name, bucket_selected), KHÔNG phải bucket_selected
    thô, để CSV xuất ra đã sẵn nhãn dễ đọc. Chỉ những data_name có bản ghi
    phủ giờ đó mới có giá trị, còn lại để trống. Cột CSV lấy đúng THỨ TỰ
    khai báo trong BUCKETS (không phải thứ tự xuất hiện trong data_base)
    cho những data_name THỰC SỰ có mặt.

    data_base rỗng -> không ghi file, trả về [].
    Trả về result để dùng tiếp nếu cần (vd hiển thị preview) mà không phải
    đọc lại file vừa ghi.
    """
    if not data_base:
        return []

    min_hour = min(r["start_hour"] for r in data_base)
    max_hour = max(r["end_hour"] for r in data_base)
    records_by_start = sorted(data_base, key=lambda r: r["start_hour"])

    result = []
    for hour in range(min_hour, max_hour + 1):
        row = {"hour": hour}
        for r in records_by_start:
            if r["start_hour"] <= hour <= r["end_hour"]:
                row[r["data_name"]] = bucket_label(r["data_name"], r["bucket_selected"])
        result.append(row)

    present_fields = {r["data_name"] for r in data_base}
    fieldnames = ["hour"] + [k for k in BUCKETS.keys() if k in present_fields]

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(result)

    return result


def window_labels(field: str) -> list:
    """Nhãn cửa sổ (kind="forecast_window"), chỉ số list = bucket_selected."""
    labels = []
    for lo, hi in BUCKETS[field]["windows"]:
        labels.append(f"{lo}+ trở lên" if hi == float("inf") else f"{lo}-{hi}")
    return labels


def linear_labels(field: str) -> list:
    """Nhãn bucket (kind="linear"), chỉ số list = bucket_selected. "Không
    màn" (nếu trường có no_ceiling) là bucket cuối, chỉ số cao nhất."""
    spec = BUCKETS[field]
    bounds = spec["bounds"]
    labels = [f"<{bounds[0]}"]
    labels += [f"{bounds[i]}-{bounds[i + 1]}" for i in range(len(bounds) - 1)]
    labels.append(f">{bounds[-1]}")
    if spec.get("no_ceiling") is not None:
        labels.append(f"{spec['no_ceiling']} (không có trần)")
    return labels


def _valid_index_count(field: str) -> int:
    """Số chỉ số bucket hợp lệ (0..n-1) cho 1 trường theo đúng khai báo
    trong BUCKETS - KHÔNG áp cho kind="phenomenon" (hien_tuong dùng
    mega_buckets)."""
    kind = BUCKETS[field]["kind"]
    if kind == "forecast_window":
        return len(window_labels(field))
    if kind == "linear":
        return len(linear_labels(field))
    if kind == "circular":
        return BUCKETS[field]["n"]
    raise ValueError(f"_valid_index_count không áp cho kind={kind!r}")


HUONG_GIO_LABELS = BUCKETS["huong_gio"]["labels"]
PHENOMENON_MEGA_KEYS = BUCKETS["hien_tuong"]["mega_buckets"]
PHENOMENON_MEGA_LABEL_TEXT = [BUCKETS["hien_tuong"]["mega_labels"][k] for k in PHENOMENON_MEGA_KEYS]


# =============================================================================
# Metadata hiển thị cho 6 trường - BUCKETS có nhãn cho GIÁ TRỊ bên trong mỗi
# trường (mega_labels, sub_labels...) nhưng không có nhãn cho chính TÊN
# trường, nên FIELD_LABELS khai báo riêng ở đây.
# =============================================================================

FIELD_ORDER = ["tong_luong_may", "do_cao_man_may", "hien_tuong",
               "huong_gio", "toc_do_gio", "tam_nhin"]

FIELD_LABELS = {
    "tong_luong_may": "Tổng lượng mây",
    "do_cao_man_may": "Độ cao màn mây (trần)",
    "hien_tuong":     "Hiện tượng",
    "huong_gio":      "Hướng gió",
    "toc_do_gio":     "Tốc độ gió",
    "tam_nhin":       "Tầm nhìn xa",
}

FIELD_DEFAULTS = {
    "tong_luong_may": 4,
    "do_cao_man_may": 0,
    "hien_tuong":     PHENOMENON_MEGA_KEYS[-1],
    "huong_gio":      0,
    "toc_do_gio":     0,
    "tam_nhin":       0,
}


def field_key_from_label(label: str):
    for k, v in FIELD_LABELS.items():
        if v == label:
            return k
    return None


def bucket_label(data_name: str, bucket_selected) -> str:
    """Nhãn đọc được của 1 bucket_selected, đúng theo kind của data_name -
    dùng để hiển thị (vd trong Treeview), không dùng để so sánh/lưu trữ."""
    kind = BUCKETS[data_name]["kind"]
    if kind == "phenomenon":
        return BUCKETS[data_name]["mega_labels"][bucket_selected]
    if kind == "forecast_window":
        return window_labels(data_name)[bucket_selected]
    if kind == "linear":
        return linear_labels(data_name)[bucket_selected]
    if kind == "circular":
        return BUCKETS[data_name]["labels"][bucket_selected]
    raise ValueError(f"bucket_label không áp cho kind={kind!r}")


def _validate_record(record: dict, context: str = "") -> None:
    """Kiểm tra 1 bản ghi {start_hour, end_hour, data_name, bucket_selected}
    đúng định dạng khai báo trong BUCKETS. Raise ValueError nếu sai (chỉ
    kiểm tra, không sửa/trả về gì) - dùng chung cho import_csv/add_record/
    edit_record để cả 3 lối ghi vào database đều tuân cùng 1 luật.
    `context`: tiền tố cho thông báo lỗi (vd "Dòng 5: ")."""
    data_name = record.get("data_name")
    if data_name not in BUCKETS:
        raise ValueError(
            f"{context}data_name '{data_name}' không hợp lệ "
            f"(hợp lệ: {', '.join(BUCKETS.keys())})")

    start_hour, end_hour = record.get("start_hour"), record.get("end_hour")
    if not (isinstance(start_hour, int) and isinstance(end_hour, int)) or \
            isinstance(start_hour, bool) or isinstance(end_hour, bool):
        raise ValueError(f"{context}start_hour/end_hour phải là số nguyên")
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        raise ValueError(f"{context}start_hour/end_hour phải trong khoảng 0-23")
    if end_hour < start_hour:
        raise ValueError(f"{context}end_hour phải >= start_hour")

    bucket_selected = record.get("bucket_selected")
    if BUCKETS[data_name]["kind"] == "phenomenon":
        mega_buckets = BUCKETS[data_name]["mega_buckets"]
        if bucket_selected not in mega_buckets:
            raise ValueError(
                f"{context}bucket_selected '{bucket_selected}' không phải mega hợp lệ "
                f"của {data_name} (hợp lệ: {', '.join(mega_buckets)})")
    else:
        if not isinstance(bucket_selected, int) or isinstance(bucket_selected, bool):
            raise ValueError(
                f"{context}bucket_selected '{bucket_selected}' phải là số nguyên cho {data_name}")
        n = _valid_index_count(data_name)
        if not (0 <= bucket_selected < n):
            raise ValueError(
                f"{context}bucket_selected {bucket_selected} ngoài phạm vi cho {data_name} "
                f"(hợp lệ: 0..{n - 1})")


def import_csv(path: str) -> list:
    """
    Đọc 1 file CSV đúng định dạng micro-database (4 cột start_hour,end_hour,
    data_name,bucket_selected - header đặt tên đúng 4 khóa đó) -> trả về
    data_base: list các dict {start_hour, end_hour, data_name, bucket_selected}.

    Mỗi dòng được ép kiểu (start_hour/end_hour/bucket_selected -> int, trừ
    bucket_selected của hien_tuong là chuỗi mega) rồi kiểm tra bằng
    _validate_record() - sai bất kỳ điểm nào thì raise ValueError NGAY (không
    nhận một phần file, không âm thầm bỏ qua).
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    data_base = []
    for i, r in enumerate(rows, start=2):   # dòng 1 là header
        context = f"Dòng {i}: "
        data_name = r.get("data_name")

        try:
            start_hour = int(r["start_hour"])
            end_hour = int(r["end_hour"])
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"{context}start_hour/end_hour phải là số nguyên")

        raw_bucket = r.get("bucket_selected")
        if data_name in BUCKETS and BUCKETS[data_name]["kind"] == "phenomenon":
            bucket = raw_bucket
        else:
            try:
                bucket = int(raw_bucket)
            except (TypeError, ValueError):
                bucket = raw_bucket   # để _validate_record báo lỗi rõ hơn "không phải số nguyên"

        record = {"start_hour": start_hour, "end_hour": end_hour,
                  "data_name": data_name, "bucket_selected": bucket}
        _validate_record(record, context=context)
        data_base.append(record)
    return data_base


def add_record(data_base: list, start_hour: int, end_hour: int, data_name: str, bucket_selected) -> dict:
    """Thêm 1 bản ghi mới vào CUỐI data_base (sửa list TRUYỀN VÀO trực tiếp -
    in-place, không trả về database mới). Kiểm tra đúng định dạng BUCKETS
    (_validate_record) TRƯỚC khi thêm - sai thì raise ValueError, không thêm
    gì cả. Trả về bản ghi vừa thêm."""
    record = {
        "start_hour": start_hour,
        "end_hour": end_hour,
        "data_name": data_name,
        "bucket_selected": bucket_selected,
    }
    _validate_record(record)
    data_base.append(record)
    return record


def remove_record(data_base: list, index: int) -> dict:
    """Xóa bản ghi tại vị trí `index` trong data_base (sửa list TRUYỀN VÀO
    trực tiếp). Trả về bản ghi vừa xóa. Raise IndexError nếu index không hợp
    lệ (hành vi mặc định của list.pop)."""
    return data_base.pop(index)


def edit_record(data_base: list, index: int, **kwargs) -> dict:
    """Sửa bản ghi tại vị trí `index` - CHỈ ghi đè các khóa truyền vào qua
    kwargs, vd edit_record(db, 0, bucket_selected=3) chỉ đổi bucket_selected,
    giữ nguyên start_hour/end_hour/data_name. Raise KeyError nếu kwargs có
    khóa lạ (không thuộc 4 khóa của bản ghi). Bản ghi SAU khi gộp kwargs
    được kiểm tra bằng _validate_record() TRƯỚC khi áp vào data_base - sai
    thì raise ValueError và bản ghi cũ giữ nguyên (không sửa nửa chừng).
    Trả về bản ghi sau khi sửa."""
    valid_keys = {"start_hour", "end_hour", "data_name", "bucket_selected"}
    invalid_keys = set(kwargs) - valid_keys
    if invalid_keys:
        raise KeyError(f"Khóa không hợp lệ: {', '.join(sorted(invalid_keys))} "
                        f"(chỉ nhận {', '.join(sorted(valid_keys))})")

    updated = {**data_base[index], **kwargs}
    _validate_record(updated)
    data_base[index] = updated
    return updated
