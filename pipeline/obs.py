"""
pipeline/obs.py
====================
Adapter: 1 bản ghi quan trắc đã decode + giờ quan trắc -> dict "obs" đủ 6
field chấm điểm (tong_luong_may/do_cao_man_may/hien_tuong/huong_gio/toc_do_gio/
tam_nhin) cộng "hour"+"buoi"+"station_code". build_obs() xử lý đúng 1 quan
trắc (1 dòng, 1 trạm, 1 giờ); build_scalar_history() quét cả thư mục, giữ
mọi trạm báo cáo mỗi giờ, và trả về 1 dict/ngày (station_code × 24 giờ).

Chạy trực tiếp (python -m pipeline.obs) để xem demo trên
tests/fixtures/qt_files/Qt26081000.txt và
tests/fixtures/qt_files/full_day_20260810/.
"""

import os

from bulletin.decode import decode_qt_file
from scoring.score_tables import BUCKETS
from scoring.scorer import solve_ceiling, sub_of_hour
from utils.filename_utils import parse_obs_dt

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
    """record: 1 phần tử decode_qt_file()/decode_record() (1 trạm, 1 giờ);
    hour: giờ quan trắc (0-23), truyền riêng vì record không tự mang giờ
    (giờ nằm ở tên file).

    wind_ff giữ nguyên đơn vị m/s có sẵn từ bulletin, không quy đổi;
    hien_tuong quy ra mega ngay tại đây (ww_code_to_mega()) nên phía chấm
    điểm nhận thẳng mega; "buoi" suy thẳng từ hour qua sub_of_hour().

    "station_code" lấy từ record["location"]["station_code"] (mã trạm dùng
    làm khoá ghép), không phải record["station"] (tên đã giải mã, chỉ để
    hiển thị, không đáng tin làm khoá)."""
    head        = record.get("head") or {}
    wind        = record.get("wind") or {}
    weather     = record.get("weather") or {}
    total_cloud = record.get("total_cloud") or {}
    location    = record.get("location") or {}

    return {
        "hour": hour,
        "buoi": sub_of_hour(hour),
        "station_code": location.get("station_code"),
        "tong_luong_may": total_cloud.get("total_cloud_N"),
        "do_cao_man_may": solve_ceiling(record.get("cloud")),
        "hien_tuong":     ww_code_to_mega(weather.get("ww_code")),
        "huong_gio":      wind_dd_to_huong_gio(wind.get("wind_dd")),
        "toc_do_gio":     wind.get("wind_ff"),
        "tam_nhin":       head.get("VV"),
    }


def _empty_obs_row(hour: int, station_code) -> dict:
    """Trạm station_code không báo cáo giờ hour (file thiếu, hoặc trạm đó
    không có mặt trong file giờ đó): vẫn trả đủ khoá như build_obs() -
    "hour"/"buoi" luôn suy được từ chính hour, "station_code" giữ nguyên
    (đã biết trạm nào, chỉ thiếu dữ liệu giờ này), 6 field còn lại None -
    cùng bộ khóa với pipeline/forecast.py's dòng giờ thiếu dữ liệu (đối
    xứng 2 bên, xem build_obs())."""
    return {
        "hour": hour,
        "buoi": sub_of_hour(hour),
        "station_code": station_code,
        "tong_luong_may": None,
        "do_cao_man_may": None,
        "hien_tuong": None,
        "huong_gio": None,
        "toc_do_gio": None,
        "tam_nhin": None,
    }


def build_scalar_history(local_dir: str) -> dict:
    """
    local_dir: thư mục chứa file QtYYMMDDHH.txt; tự quét và parse mỗi tên
    file qua parse_obs_dt() để biết nó thuộc ngày/giờ nào (không nhận date
    riêng, không tự dựng tên file kỳ vọng rồi kiểm tra tồn tại).

    Với mỗi ngày tìm thấy (còn ít nhất 1 file parse được thuộc ngày đó): gom
    tập hợp mọi station_code xuất hiện ở bất kỳ giờ nào trong ngày đó, rồi
    dựng đủ 24 dòng/giờ cho mỗi trạm đó, dùng build_obs() khi trạm có báo
    cáo giờ đó và _empty_obs_row(hour, station_code) khi không, không bỏ
    qua và không raise.

    Trả về {"YYYY-MM-DD": [(station_code × 24) dict, mỗi phần tử 1 (trạm,
    giờ) đủ khoá "station_code"/"hour"/"buoi"+6 field, sắp theo
    (station_code, hour) tăng dần], ...}, 1 entry/ngày thực sự có ít nhất 1
    file trong local_dir; local_dir rỗng hoặc không file nào parse được thì
    trả về {}.
    """
    by_date_hour = {}
    for name in os.listdir(local_dir):
        dt = parse_obs_dt(name)
        if dt is None:
            continue
        by_date_hour.setdefault(dt.date(), {})[dt.hour] = os.path.join(local_dir, name)

    result = {}
    for date, hour_to_path in sorted(by_date_hour.items()):
        # 1 lượt quét: giải mã mọi file có trong ngày, gom bản ghi theo
        # (hour, station_code) và tập hợp mọi station_code xuất hiện.
        record_at = {}   # (hour, station_code) -> decoded record
        stations = set()
        for hour, path in hour_to_path.items():
            for r in decode_qt_file(path):
                location = r.get("location")
                code = location.get("station_code") if location else None
                if code:
                    record_at[(hour, code)] = r
                    stations.add(code)

        rows = []
        for station_code in sorted(stations):
            for hour in range(24):
                record = record_at.get((hour, station_code))
                rows.append(build_obs(record, hour=hour) if record is not None
                            else _empty_obs_row(hour, station_code))
        result[date.strftime("%Y-%m-%d")] = rows
    return result


if __name__ == "__main__":
    path = "tests/fixtures/qt_files/Qt26081000.txt"
    hour = parse_obs_dt(path).hour
    for record in decode_qt_file(path):
        if record.get("location"):
            print(record["station"], build_obs(record, hour))

    print()
    history_by_date = build_scalar_history("tests/fixtures/qt_files/full_day_20260810")
    history = history_by_date["2026-08-10"]
    print(f"{len(history)} dòng")
    for row in history[:3]:
        print(row)
