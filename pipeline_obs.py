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
from pipeline_csv import parse_obs_dt
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


def build_obs(record: dict, hour: int) -> dict:
    """record: 1 phần tử decode_qt_file()/decode_record() (1 trạm, 1 giờ).
    hour: giờ quan trắc (0-23) - decode_record() không tự mang giờ (giờ nằm
    ở TÊN FILE, xem pipeline_csv.parse_obs_dt()), nên truyền riêng.

    tốc độ gió (wind_ff) không quy đổi - bulletin đã cho sẵn đơn vị m/s.
    hien_tuong giữ MÃ ww GỐC (không quy ra mega ở đây) - scoring/scorer.py
    tự quy qua mega_of() ngay bên trong score_hien_tuong()."""
    head        = record.get("head") or {}
    wind        = record.get("wind") or {}
    weather     = record.get("weather") or {}
    total_cloud = record.get("total_cloud") or {}

    return {
        "hour": hour,
        "tong_luong_may": total_cloud.get("total_cloud_N"),
        "do_cao_man_may": solve_ceiling(record.get("cloud")),
        "hien_tuong":     weather.get("ww_code"),
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
