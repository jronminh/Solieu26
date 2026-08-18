"""
pipeline/obs.py
====================
Adapter: 1 bản ghi quan trắc đã decode (bulletin/decode.py) + giờ quan trắc
-> dict "obs" đúng 6 khoá field mà scoring/scorer.py cần
(tong_luong_may/do_cao_man_may/hien_tuong/huong_gio/toc_do_gio/tam_nhin) +
"hour" + "buoi" (buổi tự suy từ giờ, xem sub_of_hour() bên scoring/scorer.py).
build_obs() chỉ biến đổi ĐÚNG 1 quan trắc (1 dòng, 1 trạm, 1 giờ) - không
biết gì về phía dự báo. build_scalar_history() lặp thêm 1 tầng: đọc 24
file/ngày, MỖI GIỜ lấy 1 trạm đại diện (chưa phân biệt nhiều trạm - việc
ghép trạm để sau, xem pipeline/scoring.py) - trả về 1 list cùng hình dạng
build_hourly_table() bên pipeline/forecast.py.

Chạy trực tiếp (python -m pipeline.obs) để xem demo trên
tests/fixtures/qt_files/Qt26081000.txt và
tests/fixtures/qt_files/full_day_20260810/.
"""

import datetime
import os

from bulletin.decode import decode_qt_file
from bulletin.filename import parse_obs_dt, quantrac_filename_at
from scoring.score_tables import BUCKETS
from scoring.scorer import solve_ceiling, sub_of_hour

# Mỗi hướng ứng với các mốc CHỤC ĐỘ nó bao, theo
# reference/Bang_cham_huong_gio_16_huong.md (4 hướng chính N/E/S/W ôm 3 mốc
# chục, còn lại ôm 2 - hệ quả làm tròn 22.5°/hướng về chục, không phải lỗi).
_DIRECTION_DECADES = {
    "N":   (350, 0, 10),
    "NNE": (20, 30),
    "NE":  (40, 50),
    "ENE": (60, 70),
    "E":   (80, 90, 100),
    "ESE": (110, 120),
    "SE":  (130, 140),
    "SSE": (150, 160),
    "S":   (170, 180, 190),
    "SSW": (200, 210),
    "SW":  (220, 230),
    "WSW": (240, 250),
    "W":   (260, 270, 280),
    "WNW": (290, 300),
    "NW":  (310, 320),
    "NNW": (330, 340),
}
_DECADE_TO_DIRECTION = {
    decade: name for name, decades in _DIRECTION_DECADES.items() for decade in decades
}


def wind_dd_to_huong_gio(wind_dd):
    """wind_dd: hướng gió quan trắc, ĐỘ (decode_wind()["wind_dd"], luôn bội
    số 10, 0-360) -> chỉ số 1 trong 16 hướng huong_gio (thứ tự
    BUCKETS["huong_gio"]["labels"]). None -> None (gió lặng/hướng không xác
    định - xem BUCKETS["huong_gio"]["na"]).

    Theo bảng tay reference/Bang_cham_huong_gio_16_huong.md: làm tròn về
    chục trước rồi tra (wind_dd ở đây đã sẵn là bội số 10 nên làm tròn
    không đổi gì, chỉ phòng khi có nguồn khác truyền độ lẻ vào)."""
    if wind_dd is None:
        return None
    decade = round(wind_dd / 10) * 10 % 360
    direction = _DECADE_TO_DIRECTION[decade]
    return BUCKETS["huong_gio"]["labels"].index(direction)


# Mã ww (2 ký tự) -> mega (BUCKETS["hien_tuong"]["mega_buckets"]). Chuyển
# nguyên từ scoring/score_tables.py (2026-08-18) - score_tables.py chỉ còn
# mô tả HÌNH DẠNG bucket, không biết quan trắc thô ánh xạ vào đó thế nào,
# cùng lý do bảng hướng gió ở trên không nằm ở đó.
#   - 13 (chớp không sấm), 18 (tố), 19 (vòi rồng): báo hiệu/đi kèm dông ->
#     gộp dong_mua_rao.
#   - 04 (khói), 06 (bụi lơ lửng): giảm tầm nhìn như mù khô -> gộp mu_mu_kho.
#   - 66,67 (mưa đông kết), 68,69 (mưa+tuyết), 83-86 (rào lẫn tuyết/tuyết
#     rào): hiếm gặp VN -> N_0 hết, không tách riêng.
#   - 20-29 (hiện tượng "giờ trước"): tính như hiện tượng hiện tại, xếp
#     theo loại, không gộp hết vào N_0.
#
# Lưu ý: mã 64/65 và 82 cùng nhãn tiếng Việt "Mưa to" nhưng khác mega-bucket
# (mưa thường to -> mua_mua_phun; mưa rào dữ dội -> dong_mua_rao). Tra bảng
# này dùng MÃ GỐC làm khóa nên đầu vào phải giữ mã ww (decode_weather()'s
# "ww_code"), không chỉ nhãn đã dịch, nếu không 2 trường hợp này sẽ không
# phân biệt được.
_WW_TO_MEGA = {
    # --- dong_mua_rao: dông, mưa rào, mưa đá rào, sau dông; chớp/tố/vòi
    #     rồng gộp vào (báo hiệu/đi kèm dông) ---
    **{c: "dong_mua_rao" for c in [
        "13", "17", "18", "19", "25", "27", "29",
        "80", "81", "82", "87", "88", "89", "90",
        "91", "92", "93", "94", "95", "96", "97", "98", "99",
    ]},
    # --- mua_mua_phun: mưa phùn, mưa THƯỜNG (không phải mưa rào) ---
    **{c: "mua_mua_phun" for c in [
        "20", "21",
        "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
        "60", "61", "62", "63", "64", "65",
    ]},
    # --- suong_mu: sương mù (kể cả mỏng, giờ trước) ---
    **{c: "suong_mu" for c in [
        "11", "12", "28",
        "40", "41", "42", "43", "44", "45", "46", "47", "48", "49",
    ]},
    # --- mu_mu_kho: mù, mù khô, khói, bụi lơ lửng ---
    **{c: "mu_mu_kho" for c in ["04", "05", "06", "10"]},
    # --- N_0: phần còn lại (mây tan/hình thành/không đổi, mưa xa chưa tới
    #     trạm, tuyết/băng/mưa đông kết/hỗn hợp mưa-tuyết hiếm gặp VN,
    #     bụi/lốc bụi/bão bụi-cát/tuyết cuốn) ---
    **{c: "N_0" for c in [
        "00", "01", "02", "03",
        "07", "08", "09",
        "14", "15", "16",
        "22", "23", "24", "26",
        "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
        "66", "67", "68", "69",
        "70", "71", "72", "73", "74", "75", "76", "77", "78", "79",
        "83", "84", "85", "86",
    ]},
}


def ww_code_to_mega(ww_code):
    """Mã ww GỐC (decode_weather()'s "ww_code") -> nhãn mega-bucket
    (BUCKETS["hien_tuong"]["mega_buckets"]). KHÔNG báo cáo mã (ww_code is
    None) -> "N_0", không phải thiếu dữ liệu (giả định này chưa kiểm chứng
    chắc chắn, xem TODO.md). Mã CÓ báo cáo nhưng không khớp nhóm nào (lỗi
    giải mã/mã lạ ngoài 00-99) mới -> None (bỏ cặp thật sự, xem
    score_hien_tuong()) - _WW_TO_MEGA đã phủ đủ 00-99 nên ca này gần như
    không xảy ra với dữ liệu hợp lệ."""
    if ww_code is None:
        return "N_0"
    return _WW_TO_MEGA.get(ww_code)


def build_obs(record: dict, hour: int) -> dict:
    """record: 1 phần tử decode_qt_file()/decode_record() (1 trạm, 1 giờ).
    hour: giờ quan trắc (0-23) - decode_record() không tự mang giờ (giờ nằm
    ở TÊN FILE, xem bulletin/filename.py::parse_obs_dt()), nên truyền riêng.

    tốc độ gió (wind_ff) không quy đổi - bulletin đã cho sẵn đơn vị m/s.
    hien_tuong quy ra MEGA ngay tại đây (ww_code_to_mega()) - scoring/scorer.py
    (score_hien_tuong()) nhận thẳng mega, không tự quy đổi nữa. "buoi" quy
    thẳng từ hour qua sub_of_hour() - scorer.py so buổi 2 phía trực tiếp,
    không tự suy từ hour nữa."""
    head        = record.get("head") or {}
    wind        = record.get("wind") or {}
    weather     = record.get("weather") or {}
    total_cloud = record.get("total_cloud") or {}

    return {
        "hour": hour,
        "buoi": sub_of_hour(hour),
        "tong_luong_may": total_cloud.get("total_cloud_N"),
        "do_cao_man_may": solve_ceiling(record.get("cloud")),
        "hien_tuong":     ww_code_to_mega(weather.get("ww_code")),
        "huong_gio":      wind_dd_to_huong_gio(wind.get("wind_dd")),
        "toc_do_gio":     wind.get("wind_ff"),
        "tam_nhin":       head.get("VV"),
    }


def build_scalar_history(date: datetime.date, local_dir: str) -> list:
    """
    date: ngày quan trắc. local_dir: thư mục chứa file QtYYMMDDHH.txt
    (cùng quy ước tham số với pipeline/fetch.py::download_files()).

    Với mỗi giờ 0-23: dựng tên file qua quantrac_filename_at(), lấy bản ghi
    ĐẦU TIÊN có "location" trong file đó (1 trạm đại diện/giờ - matcher
    hiện chưa cần phân biệt trạm, xem pipeline/scoring.py) rồi build_obs().
    File giờ nào không tồn tại trên đĩa (chưa tải/đã mất) -> bỏ qua giờ đó,
    không raise (cùng chính sách "thiếu file -> giảm số dòng, không lỗi"
    như bulletin/decode.py::decode_history()); file tồn tại nhưng không
    bản ghi nào có "location" thì cũng bỏ qua giờ đó.

    Trả về: list dict, CÙNG HÌNH DẠNG build_hourly_table()
    (pipeline/forecast.py) - mỗi phần tử 1 giờ, đủ khoá "hour" + "buoi" +
    6 field, sắp theo giờ tăng dần. Giờ thiếu dữ liệu thì vắng mặt trong
    list (không
    phải None) - khác build_hourly_table() ở chỗ đó (bên forecast pivot đủ
    24 dòng, bên obs chỉ có dòng cho giờ THẬT SỰ đọc được).
    """
    rows = []
    for hour in range(24):
        dt = datetime.datetime(date.year, date.month, date.day, hour)
        path = os.path.join(local_dir, quantrac_filename_at(dt))
        if not os.path.exists(path):
            continue
        record = next((r for r in decode_qt_file(path) if r.get("location")), None)
        if record is None:
            continue
        rows.append(build_obs(record, hour=hour))
    return rows


if __name__ == "__main__":
    path = "tests/fixtures/qt_files/Qt26081000.txt"
    hour = parse_obs_dt(path).hour
    for record in decode_qt_file(path):
        if record.get("location"):
            print(record["station"], build_obs(record, hour))

    print()
    history = build_scalar_history(
        datetime.date(2026, 8, 10), "tests/fixtures/qt_files/full_day_20260810")
    print(f"{len(history)} dòng")
    for row in history[:3]:
        print(row)
