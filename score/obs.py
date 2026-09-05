"""
score/obs.py
====================
Adapter: 1 bulletin thô ("Qt..." record, 1 trạm 1 giờ) + giờ quan trắc ->
dict "obs" đủ 6 field chấm điểm (tong_luong_may/do_cao_man_may/hien_tuong/
huong_gio/toc_do_gio/tam_nhin) cộng "hour"+"buoi"+"station_code".
build_obs() xử lý đúng 1 bulletin; build_scalar_history() quét cả thư mục,
build_scalar_history_from_files() làm y hệt nhưng nhận thẳng danh sách file
(không quét gì thêm ngoài danh sách đó) — cả 2 đều giữ mọi trạm báo cáo mỗi
giờ, trả về 1 dict/ngày (station_code × 24 giờ).

Giải mã bulletin nhúng thẳng vào build_obs() (không qua bước decode trung
gian ra dict lồng nhau như decode.py cũ) — chỉ 6 field kể trên + station_code
được đọc, nên không có lý do giữ 1 tầng "decode() rồi adapt()" chỉ để rồi
build_obs() lọc lại đúng bằng đó field.

Chạy trực tiếp (python -m score.obs) để xem demo trên
tests/fixtures/qt_files/Qt26081000.txt và
tests/fixtures/qt_files/full_day_20260810/.
"""

import os

try:
    from .code_tables import TABLES
    from .score_tables import BUCKETS
    from .scorer import solve_ceiling, sub_of_hour
    from .filename_utils import parse_obs_dt
except ImportError:
    # chạy trực tiếp "python score/obs.py" (không phải -m score.obs) thì đây
    # không phải package, không import relative được — fallback sang import
    # tuyệt đối, hoạt động vì Python tự thêm thư mục chứa obs.py (score/) vào
    # sys.path khi chạy trực tiếp.
    from code_tables import TABLES
    from score_tables import BUCKETS
    from scorer import solve_ceiling, sub_of_hour
    from filename_utils import parse_obs_dt


# =============================================================================
# TOKEN HELPERS (bulletin thô -> token slots / giá trị số dùng chung)
# =============================================================================

def is_pressure_token(t: str) -> bool:
    return len(t) == 4 and t.isdigit() and t.startswith('7')


def split_record(record: str) -> dict:
    tokens = record.split()
    if not tokens:
        return {"head": None, "wind": None, "indicators": [],
                "pressure": None, "name": [], "tail": None}

    n = len(tokens)
    tail = tokens[-1]
    name_start = next((i for i, t in enumerate(tokens) if t.startswith('t')), n - 1)
    name = tokens[name_start:n - 1]

    if tokens[0].startswith('k'):
        head = tokens[0]
        wind = tokens[1] if n > 1 else None
        block_start = 2
    else:
        head = wind = None
        block_start = name_start

    middle = tokens[block_start:name_start]

    pressure = None
    indicators = list(middle)
    for j in range(len(middle) - 1, -1, -1):
        if is_pressure_token(middle[j]):
            pressure = middle[j]
            indicators = middle[:j] + middle[j + 1:]
            break

    return {"head": head, "wind": wind, "indicators": indicators,
            "pressure": pressure, "name": name, "tail": tail}


def hshs_value(code: str, tables: dict):
    try:
        h = int(code)
    except ValueError:
        return None
    if 1 <= h <= 5:
        return h * 30
    if 6 <= h <= 50:
        return round(h * 30 / 50) * 50
    return tables["hshs_special"].get(code)


def vv_value(vv_code: str, tables: dict):
    """Visibility in km (float), decoded from the raw VV code. Piecewise/
    lossy: several VV codes collapse to the same km value, so this only
    goes value -> km, never the reverse."""
    if len(vv_code) < 2:
        return None
    try:
        vv = int(vv_code)
    except ValueError:
        return None
    if vv < 51:
        s = f"{vv_code[0]}.{vv_code[1]}"
    elif vv <= 55:
        return None
    elif vv <= 80:
        s = str(vv - 50)
    elif vv <= 89:
        s = str(vv - 40)
    else:
        s = tables["VV_special"].get(vv_code)
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def get_qt_data(file_path: str) -> list:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = f.read()
    if not data:
        return []
    sep = ';' if ';' in data else '='
    return data.split(sep)[:-1]


# =============================================================================
# QUAN TRẮC THÔ -> "obs" (vocab chấm điểm)
# =============================================================================

# Mỗi hướng ứng với các mốc CHỤC ĐỘ nó bao (4 hướng chính N/E/S/W ôm 3 mốc
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
    """wind_dd: hướng gió quan trắc, ĐỘ (luôn bội số 10, 0-360) -> chỉ số 1
    trong 16 hướng huong_gio (thứ tự BUCKETS["huong_gio"]["labels"]).
    None -> None (gió lặng/hướng không xác định - xem BUCKETS["huong_gio"]["na"]).

    Làm tròn về chục trước rồi tra (wind_dd ở đây đã sẵn là bội số 10 nên
    làm tròn không đổi gì, chỉ phòng khi có nguồn khác truyền độ lẻ vào)."""
    if wind_dd is None:
        return None
    decade = round(wind_dd / 10) * 10 % 360
    direction = _DECADE_TO_DIRECTION[decade]
    return BUCKETS["huong_gio"]["labels"].index(direction)


# Mã ww (2 ký tự) -> mega (BUCKETS["hien_tuong"]["mega_buckets"]). Chuyển
# nguyên từ core/score_tables.py (2026-08-18) - score_tables.py chỉ còn
# mô tả HÌNH DẠNG bucket, không biết quan trắc thô ánh xạ vào đó thế nào,
# cùng lý do bảng hướng gió ở trên không nằm ở đó.
#   - 13 (chớp không sấm), 18 (tố), 19 (vòi rồng): báo hiệu/đi kèm dông ->
#     gộp dong_mua_rao.
#   - 04 (khói), 06 (bụi lơ lửng): giảm tầm nhìn như mù khô -> gộp mu_mu_kho.
#   - 66,67 (mưa đông kết), 68,69 (mưa+tuyết), 83-86 (rào lẫn tuyết/tuyết
#     rào): hiếm gặp VN -> khong hết, không tách riêng.
#   - 20-29 (hiện tượng "giờ trước"): tính như hiện tượng hiện tại, xếp
#     theo loại, không gộp hết vào khong.
#
# Lưu ý: mã 64/65 và 82 cùng nhãn tiếng Việt "Mưa to" nhưng khác mega-bucket
# (mưa thường to -> mua_mua_phun; mưa rào dữ dội -> dong_mua_rao). Tra bảng
# này dùng MÃ GỐC làm khóa nên đầu vào phải giữ mã ww thô (2 ký tự sau '7'
# trong nhóm hiện tượng), không chỉ nhãn đã dịch, nếu không 2 trường hợp
# này sẽ không phân biệt được.
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
    # --- khong: phần còn lại (mây tan/hình thành/không đổi, mưa xa chưa tới
    #     trạm, tuyết/băng/mưa đông kết/hỗn hợp mưa-tuyết hiếm gặp VN,
    #     bụi/lốc bụi/bão bụi-cát/tuyết cuốn) ---
    **{c: "khong" for c in [
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
    """Mã ww GỐC (2 ký tự) -> nhãn mega-bucket
    (BUCKETS["hien_tuong"]["mega_buckets"]). KHÔNG báo cáo mã (ww_code is
    None) -> None (bỏ cặp, thiếu dữ liệu thật - không đồng nghĩa quan trắc
    viên xác nhận trời quang). Mã CÓ báo cáo, dù rơi vào nhóm "khong" (không
    có hiện tượng gì đáng kể) hay không khớp nhóm nào (lỗi giải mã/mã lạ
    ngoài 00-99), đều là 1 lần quan trắc thật; nhóm không khớp cũng -> None
    (bỏ cặp, xem score_hien_tuong()) nhưng _WW_TO_MEGA đã phủ đủ 00-99 nên
    ca này gần như không xảy ra với dữ liệu hợp lệ."""
    if ww_code is None:
        return None
    return _WW_TO_MEGA.get(ww_code)


def build_obs(record: str, hour: int) -> dict:
    """record: 1 bulletin thô CHƯA decode (1 phần tử get_qt_data(), 1 trạm 1
    giờ); hour: giờ quan trắc (0-23), truyền riêng vì record không tự mang
    giờ (giờ nằm ở tên file).

    Đọc thẳng từ token, không dựng dict trung gian: wind_ff giữ nguyên đơn
    vị m/s có sẵn từ bulletin, không quy đổi; hien_tuong quy ra mega ngay
    tại đây (ww_code_to_mega()) nên phía chấm điểm nhận thẳng mega; "buoi"
    suy thẳng từ hour qua sub_of_hour().

    "station_code" lấy từ token cuối (tail, dạng kXX+DDMM+DDDMM) — None nếu
    record này không phải bản ghi trạm thật (vd phần header đầu file); caller
    tự lọc bỏ theo station_code, xem _obs_records_for_file()."""
    p = split_record(record)

    head_token = p["head"]
    tam_nhin = (vv_value(head_token[3:], TABLES)
                if head_token and head_token.startswith('k') else None)

    wind_token = p["wind"]
    tong_luong_may = huong_gio_deg = toc_do_gio = None
    if wind_token and len(wind_token) >= 5:
        N = TABLES["N_oktas"].get(wind_token[0])
        try:
            tong_luong_may = N if N in (None, "/") else int(N)
        except ValueError:
            tong_luong_may = None
        try:
            huong_gio_deg = int(wind_token[1:3]) * 10
            toc_do_gio = int(wind_token[3:5])
        except ValueError:
            huong_gio_deg = toc_do_gio = None

    ww_code = None
    cloud_layers = None   # None = không có nhóm mây nào; [] = có nhưng rỗng/hỏng
    for t in p["indicators"]:
        if not t:
            continue
        if t[0] == '7':
            ww_code = t[1:3] if len(t) >= 5 else None
        elif t[0] == '8':
            if cloud_layers is None:
                cloud_layers = []
            if len(t) >= 5:
                Ns = TABLES["N_oktas"].get(t[1])
                try:
                    Ns = Ns if Ns in (None, "/") else int(Ns)
                except ValueError:
                    Ns = None
                cloud_layers.append({"amount": Ns,
                                      "type":   TABLES["cloud_type"].get(t[2]),
                                      "height": hshs_value(t[3:5], TABLES)})

    tail_token = p["tail"]
    station_code = (tail_token[0:3]
                     if tail_token and tail_token.startswith('k') and len(tail_token) == 12
                     else None)

    return {
        "hour": hour,
        "buoi": sub_of_hour(hour),
        "station_code": station_code,
        "tong_luong_may": tong_luong_may,
        "do_cao_man_may": solve_ceiling(cloud_layers),
        "hien_tuong":     ww_code_to_mega(ww_code),
        "huong_gio":      wind_dd_to_huong_gio(huong_gio_deg),
        "toc_do_gio":     toc_do_gio,
        "tam_nhin":       tam_nhin,
    }


def _empty_obs_row(hour: int, station_code) -> dict:
    """Trạm station_code không báo cáo giờ hour (file thiếu, hoặc trạm đó
    không có mặt trong file giờ đó): vẫn trả đủ khoá như build_obs() -
    "hour"/"buoi" luôn suy được từ chính hour, "station_code" giữ nguyên
    (đã biết trạm nào, chỉ thiếu dữ liệu giờ này), 6 field còn lại None -
    cùng bộ khóa với score/forecast.py's dòng giờ thiếu dữ liệu (đối
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


def _obs_records_for_file(path: str, hour: int) -> list:
    """1 file (1 giờ) -> list obs dict cho mọi trạm báo cáo trong file đó,
    bỏ qua bulletin lỗi (hỏng/không đúng khuôn dạng) hoặc không có
    station_code (vd phần header đầu file, không phải bản ghi trạm)."""
    rows = []
    for raw in get_qt_data(path):
        try:
            obs = build_obs(raw, hour)
        except Exception:
            continue
        if obs["station_code"]:
            rows.append(obs)
    return rows


def _group_by_date_hour(paths: list) -> dict:
    """path list -> {date: {hour: path}}, bỏ qua path không parse được qua
    parse_obs_dt() (hàm đó tự đọc os.path.basename(), nên path ở đây giữ
    nguyên trạng, không join lại với thư mục nào)."""
    by_date_hour = {}
    for path in paths:
        dt = parse_obs_dt(path)
        if dt is None:
            continue
        by_date_hour.setdefault(dt.date(), {})[dt.hour] = path
    return by_date_hour


def _scalar_history_for_dates(by_date_hour: dict) -> dict:
    """{date: {hour: path}} -> {"YYYY-MM-DD": [(station_code × 24) dict, ...], ...}.

    Với mỗi ngày: gom tập hợp mọi station_code xuất hiện ở bất kỳ giờ nào
    trong ngày đó, rồi dựng đủ 24 dòng/giờ cho mỗi trạm đó, dùng obs dict đã
    build sẵn khi trạm có báo cáo giờ đó và _empty_obs_row(hour, station_code)
    khi không, không bỏ qua và không raise. Mỗi dòng đủ khoá
    "station_code"/"hour"/"buoi"+6 field, sắp theo (station_code, hour)
    tăng dần.
    """
    result = {}
    for date, hour_to_path in sorted(by_date_hour.items()):
        # 1 lượt quét: build obs cho mọi bulletin có trong ngày, gom theo
        # (hour, station_code) và tập hợp mọi station_code xuất hiện.
        obs_at = {}   # (hour, station_code) -> obs dict
        stations = set()
        for hour, path in hour_to_path.items():
            for obs in _obs_records_for_file(path, hour):
                obs_at[(hour, obs["station_code"])] = obs
                stations.add(obs["station_code"])

        rows = []
        for station_code in sorted(stations):
            for hour in range(24):
                obs = obs_at.get((hour, station_code))
                rows.append(obs if obs is not None else _empty_obs_row(hour, station_code))
        result[date.strftime("%Y-%m-%d")] = rows
    return result


def build_scalar_history(local_dir: str) -> dict:
    """
    local_dir: thư mục chứa file QtYYMMDDHH.txt; tự quét và parse mỗi tên
    file qua parse_obs_dt() để biết nó thuộc ngày/giờ nào (không nhận date
    riêng, không tự dựng tên file kỳ vọng rồi kiểm tra tồn tại).

    Trả về {"YYYY-MM-DD": [...], ...}, 1 entry/ngày thực sự có ít nhất 1
    file trong local_dir (xem _scalar_history_for_dates() cho hình dạng mỗi
    dòng); local_dir rỗng hoặc không file nào parse được thì trả về {}.
    """
    paths = [os.path.join(local_dir, name) for name in os.listdir(local_dir)]
    return _scalar_history_for_dates(_group_by_date_hour(paths))


def build_scalar_history_from_files(paths: list) -> dict:
    """Như build_scalar_history(), nhưng nhận thẳng danh sách đường dẫn file
    thay vì quét cả 1 thư mục — dùng khi thư mục chứa các file này có thể
    lẫn dữ liệu của lượt tải khác (vd thư mục tải tạm dùng chung giữa các
    lượt chạy), chỉ đúng các file trong `paths` mới được xét tới."""
    return _scalar_history_for_dates(_group_by_date_hour(paths))


if __name__ == "__main__":
    path = "tests/fixtures/qt_files/Qt26081000.txt"
    hour = parse_obs_dt(path).hour
    for obs in _obs_records_for_file(path, hour):
        print(obs["station_code"], obs)

    print()
    history_by_date = build_scalar_history("tests/fixtures/qt_files/full_day_20260810")
    history = history_by_date["2026-08-10"]
    print(f"{len(history)} dòng")
    for row in history[:3]:
        print(row)
