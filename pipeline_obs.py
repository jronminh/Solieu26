"""
pipeline_obs.py
====================
Adapter: 1 bản ghi quan trắc đã decode (bulletin/decode.py) + giờ quan trắc
-> dict "obs" đúng 6 khoá field mà scoring/scorer.py cần
(tong_luong_may/do_cao_man_may/hien_tuong/huong_gio/toc_do_gio/tam_nhin) +
"hour". Chỉ biến đổi ĐÚNG 1 quan trắc (1 dòng, 1 trạm, 1 giờ) - không biết
gì về phía dự báo, không ghép cặp trạm/giờ (việc của matcher, chưa xây).

Chạy trực tiếp (python pipeline_obs.py) để xem demo trên
tests/fixtures/qt_files/Qt26081000.txt.
"""

from bulletin.decode import decode_qt_file
from bulletin.filename import parse_obs_dt
from scoring.score_tables import BUCKETS
from scoring.scorer import solve_ceiling

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
    (BUCKETS["hien_tuong"]["mega_buckets"]). None -> None (chưa gán / không
    thuộc nhóm nào -> bỏ cặp, xem score_hien_tuong())."""
    if ww_code is None:
        return None
    return _WW_TO_MEGA.get(ww_code)


def build_obs(record: dict, hour: int) -> dict:
    """record: 1 phần tử decode_qt_file()/decode_record() (1 trạm, 1 giờ).
    hour: giờ quan trắc (0-23) - decode_record() không tự mang giờ (giờ nằm
    ở TÊN FILE, xem bulletin/filename.py::parse_obs_dt()), nên truyền riêng.

    tốc độ gió (wind_ff) không quy đổi - bulletin đã cho sẵn đơn vị m/s.
    hien_tuong quy ra MEGA ngay tại đây (ww_code_to_mega()) - scoring/scorer.py
    (score_hien_tuong()) nhận thẳng mega, không tự quy đổi nữa."""
    head        = record.get("head") or {}
    wind        = record.get("wind") or {}
    weather     = record.get("weather") or {}
    total_cloud = record.get("total_cloud") or {}

    return {
        "hour": hour,
        "tong_luong_may": total_cloud.get("total_cloud_N"),
        "do_cao_man_may": solve_ceiling(record.get("cloud")),
        "hien_tuong":     ww_code_to_mega(weather.get("ww_code")),
        "huong_gio":      wind_dd_to_huong_gio(wind.get("wind_dd")),
        "toc_do_gio":     wind.get("wind_ff"),
        "tam_nhin":       head.get("VV"),
    }


if __name__ == "__main__":
    path = "tests/fixtures/qt_files/Qt26081000.txt"
    hour = parse_obs_dt(path).hour
    for record in decode_qt_file(path):
        if record.get("location"):
            print(record["station"], build_obs(record, hour))
