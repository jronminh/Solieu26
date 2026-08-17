"""
scorer.py
====================
Bộ máy chấm điểm cho 6 trường dự báo: bucket_of (quy giá trị quan trắc về
bucket cho linear/circular), is_hit_window (chấm kind=forecast_window),
solve_ceiling (giải trần từ các lớp mây), và 3 lối vào chấm score_field /
score_wind / score_phenomenon — mỗi lối ứng với một nhóm kind, xem chi tiết
ngay tại từng hàm. Cấu hình bucket (dữ liệu thuần, không có logic) nằm ở
module riêng, import vào đây làm BUCKETS/NO_CEILING.

Mô hình chung: dự báo viên chọn thẳng 1 bucket (không nhập số, không qua
bucket_of); quan trắc là 1 giá trị vô hướng, được quy về dạng so được tùy
kind rồi so lệch với bucket dự báo trong phạm vi tolerance của trường đó.
Mọi hàm score_* trả về True/False, hoặc None nếu bỏ cặp (thiếu dữ liệu/na).
"""

from bisect import bisect_left, bisect_right

from .score_tables import BUCKETS, NO_CEILING


# ====================================================================== #
# SOLVER MÀN MÂY (nghiệp vụ)                                              #
# Bên quan trắc gọi để ra 1 giá trị trần rồi mới bucket hóa; bên dự báo   #
# nhập thẳng nên KHÔNG gọi solver.                                        #
# ====================================================================== #

# Phân loại mây cho bài toán màn (tên loại theo bảng cloud_type):
CEILING_LOW    = {"Cu", "Sc", "St", "Cb"}   # mây dưới
CEILING_MIDDLE = {"As", "Ac", "Ns"}          # mây giữa
# Mây trên (Ci, Cc, Cs) KHÔNG tính vào màn.

CEILING_THRESHOLD = 6   # 6/10 — cùng thang phần mười với lượng mây đã giải


def solve_ceiling(layers):
    """
    Tính độ cao màn mây từ các lớp mây riêng lẻ (theo mô tả nghiệp vụ).

    Tham số
    -------
    layers : list[dict] | None
        Mỗi lớp: {"type": <tên loại "Cu"/"Sc"/...>,
                   "amount": <lượng, PHẦN MƯỜI 0-10>,
                   "height": <độ cao, MÉT>}
        - "type"   : tên loại đã giải (bảng cloud_type). Nếu decode trả CODE
                     thì map qua TABLES["cloud_type"] TRƯỚC khi gọi hàm này.
        - "amount" : phải cùng thang phần mười với CEILING_THRESHOLD. Nếu
                     decode trả octa/khác thì quy về phần mười trước.
        - None     : không có dữ liệu để tính -> trả None (bỏ cặp).
        - []       : quan sát được nhưng không có lớp mây dưới/giữa -> NO_CEILING.

    Trả về
    ------
    float | int   : có màn -> độ cao trần (mét)
    NO_CEILING    : quan sát được nhưng không thành màn ("không màn", có chấm)
    None          : thiếu dữ liệu -> bỏ cặp (KHÁC "không màn")

    Quy tắc (đúng theo nghiệp vụ):
      1. Là "màn" khi TỔNG lượng mây dưới (Cu,Sc,St,Cb) + mây giữa
         (As,Ac,Ns) >= 6/10. Không đạt -> "không màn".
      2. Có lớp tự nó >= 6/10 -> lấy độ cao LỚP THẤP NHẤT trong số đó.
      3. Không lớp nào >= 6/10 (nhưng tổng >= 6/10) -> lấy độ cao lớp có
         LƯỢNG LỚN NHẤT.
      4. Lượng bằng nhau -> lấy lớp THẤP HƠN.
    """
    if layers is None:
        return None

    # Chỉ giữ mây dưới + mây giữa; mây trên bỏ.
    relevant = [L for L in layers
                if L.get("type") in CEILING_LOW or L.get("type") in CEILING_MIDDLE]
    if not relevant:
        return NO_CEILING

    # (1) Có phải màn không: tổng lượng dưới + giữa >= 6/10
    if sum(L["amount"] for L in relevant) < CEILING_THRESHOLD:
        return NO_CEILING

    # (2) Có lớp nào tự nó >= 6/10 -> lớp thấp nhất trong số đó
    strong = [L for L in relevant if L["amount"] >= CEILING_THRESHOLD]
    if strong:
        return min(strong, key=lambda L: L["height"])["height"]

    # (3)+(4) Không lớp nào đạt: lớp lượng lớn nhất; bằng nhau -> lớp thấp hơn
    return min(relevant, key=lambda L: (-L["amount"], L["height"]))["height"]


# ====================================================================== #
# CHẤM CỬA SỔ CHỒNG NHAU (kind="forecast_window")                        #
# Dùng cho tổng lượng mây VÀ tốc độ gió: dự báo là 1 CỬA SỔ, quan trắc   #
# là 1 SỐ; ±1 áp cho CỬA SỔ dự báo. Không bucket hóa quan trắc.          #
# ====================================================================== #

def is_hit_window(field, forecast_idx, obs_value):
    """
    forecast_idx : cửa sổ dự báo viên chọn (chỉ số).
    obs_value    : số quan trắc. None hoặc thuộc na -> bỏ cặp.

    Đúng khi obs rơi vào HỢP của cửa dự báo và ±tolerance cửa kề (kẹp mép).
    Ví dụ (mây): forecast_idx=2 ("2-4") -> dải [1,5].
    Trả True/False, hoặc None nếu bỏ cặp.
    """
    spec = BUCKETS[field]
    if forecast_idx is None or obs_value is None or obs_value in spec.get("na", []):
        return None
    wins = spec["windows"]
    tol = spec.get("tolerance", 1)
    lo_idx = max(0, forecast_idx - tol)
    hi_idx = min(len(wins) - 1, forecast_idx + tol)
    lo = wins[lo_idx][0]          # mép dưới cửa thấp nhất được chấp nhận
    hi = wins[hi_idx][1]          # mép trên cửa cao nhất được chấp nhận
    return lo <= obs_value <= hi


# ====================================================================== #
# BUCKETER — số vô hướng -> chỉ số bucket (cho quan trắc)                 #
# Chỉ dùng cho linear / circular. forecast_window (mây) KHÔNG bucket hóa  #
# quan trắc (bucket chồng nhau); categorical dùng bảng groups.            #
# ====================================================================== #

def bucket_of(field, value):
    """Số vô hướng -> chỉ số bucket. Trả None nếu thiếu/không chấm (bỏ cặp)."""
    spec = BUCKETS[field]
    if value is None or value in spec.get("na", []):
        return None
    if spec["kind"] == "categorical":
        return spec["groups"].get(value)           # value = mã (vd ww) -> nhãn nhóm
    if spec["kind"] == "linear":
        b = spec["bounds"]
        # trạng thái "không màn" (trần): bucket TRÊN CÙNG, kề bucket cao nhất
        if "no_ceiling" in spec and value == spec["no_ceiling"]:
            return len(b) + 1
        f = bisect_left if spec.get("side") == "left" else bisect_right
        return f(b, value)
    if spec["kind"] == "circular":
        # Giá trị đã là HƯỚNG (chỉ số 0..n-1 hoặc nhãn "N"/"NNE"...), KHÔNG phải độ.
        labels = spec.get("labels")
        if isinstance(value, str) and labels is not None:
            return labels.index(value) if value in labels else None
        return int(value)
    raise ValueError("bucket_of không áp cho kind=%r (vd forecast_window)" % spec["kind"])


# ====================================================================== #
# CHẤM CHUNG — dự báo là 1 BUCKET, quan trắc là 1 SỐ, đúng khi lệch      #
# <= tolerance BUCKET. Áp cho tầm nhìn, trần, tốc độ gió (linear) và      #
# hướng gió (circular). Mây dùng is_hit_cloud; hiện tượng khớp nhóm.      #
# ====================================================================== #

def is_hit_scalar(field, forecast_idx, obs_value):
    """
    forecast_idx : bucket dự báo viên CHỌN (chỉ số).
    obs_value    : số quan trắc (với trần có thể là NO_CEILING).
    Đúng khi bucket của quan trắc lệch <= tolerance so với bucket dự báo.
    linear: kẹp mép tự nhiên (chỉ số quan trắc luôn hợp lệ). circular: cuộn vòng.
    Trả True/False, hoặc None nếu bỏ cặp.
    """
    obs_idx = bucket_of(field, obs_value)
    if forecast_idx is None or obs_idx is None:
        return None
    spec = BUCKETS[field]
    tol = spec.get("tolerance", 1)
    d = abs(forecast_idx - obs_idx)
    if spec["kind"] == "circular":
        d = min(d, spec["n"] - d)                   # cuộn vòng
    return d <= tol


def score_field(field, forecast_choice, obs_value):
    """
    Điểm vào chung cho cả 6 trường. Luôn: DỰ BÁO là lựa chọn bucket,
    QUAN TRẮC là 1 giá trị vô hướng.

    forecast_choice:
        - forecast_window (mây)   -> chỉ số cửa sổ (0..8)
        - linear / circular       -> chỉ số bucket dự báo viên chọn
        - categorical (hiện tượng)-> nhãn nhóm dự báo viên chọn
    obs_value:
        - forecast_window / linear / circular -> số quan trắc (trần: có thể NO_CEILING)
        - categorical -> mã quan trắc (vd mã ww), sẽ map qua groups

    Trả True/False, hoặc None nếu bỏ cặp.
    """
    kind = BUCKETS[field]["kind"]
    if kind == "forecast_window":
        return is_hit_window(field, forecast_choice, obs_value)
    if kind in ("linear", "circular"):
        return is_hit_scalar(field, forecast_choice, obs_value)
    if kind == "phenomenon":
        raise ValueError("hien_tuong 2 tầng -> dùng score_phenomenon(), không phải score_field()")
    if kind == "categorical":
        spec = BUCKETS[field]
        obs_group = bucket_of(field, obs_value)     # mã -> nhóm
        if forecast_choice is None or obs_group is None or obs_group in spec.get("na", []):
            return None
        return forecast_choice == obs_group          # tolerance 0: khớp đúng nhóm
    raise ValueError("kind lạ: %r" % kind)


# ====================================================================== #
# SOLVER CHẤM GIÓ (tốc độ + hướng) — có coupling, chấm CẢ CẶP một lần    #
# Regime theo TỐC ĐỘ QUAN TRẮC (xem TODO.md: cơ sở này còn chờ xác nhận):#
#   - obs_speed <= 2 m/s : CHỈ chấm tốc độ, bỏ hướng                     #
#   - obs_speed > 15 m/s : CHỈ chấm hướng, bỏ tốc độ                     #
#   - 2 < obs_speed <= 15: chấm cả hai                                   #
# Dùng score_wind() cho gió/hướng, KHÔNG gọi score_field lẻ cho 2 trường #
# này (vì có/không chấm mỗi trường phụ thuộc tốc độ).                    #
# ====================================================================== #

WIND_NO_DIR_MAX   = 2    # tốc độ <= 2 m/s -> không chấm HƯỚNG
WIND_NO_SPEED_MIN = 15   # tốc độ > 15 m/s -> không chấm TỐC ĐỘ


def score_wind(forecast_speed_idx, forecast_dir, obs_speed, obs_dir):
    """
    forecast_speed_idx : cửa sổ tốc độ dự báo viên chọn (chỉ số)
    forecast_dir       : hướng dự báo viên chọn (chỉ số 0..15 hoặc nhãn)
    obs_speed          : tốc độ quan trắc (m/s). None -> không xác định regime.
    obs_dir            : hướng quan trắc (chỉ số/nhãn).

    Trả dict {"toc_do_gio": hit|None, "huong_gio": hit|None}
      True/False = chấm và kết quả; None = KHÔNG chấm trường đó cho cặp này.
    """
    if obs_speed is None:
        return {"toc_do_gio": None, "huong_gio": None}
    score_speed = obs_speed <= WIND_NO_SPEED_MIN          # >15 -> bỏ tốc độ
    score_dir   = obs_speed >  WIND_NO_DIR_MAX            # <=2 -> bỏ hướng
    return {
        "toc_do_gio": score_field("toc_do_gio", forecast_speed_idx, obs_speed) if score_speed else None,
        "huong_gio":  score_field("huong_gio",  forecast_dir,       obs_dir)   if score_dir   else None,
    }


# ====================================================================== #
# CHẤM HIỆN TƯỢNG — 2 tầng: MEGA (loại, khớp chính xác) × SUB (buổi, ±1  #
# kẹp mép). GIỜ quan trắc -> buổi bằng sub_of_hour (ánh xạ trong config).#
# Đúng khi MEGA khớp đúng VÀ buổi lệch <= 1. Dùng score_phenomenon(),    #
# KHÔNG dùng score_field cho hiện tượng.                                 #
# ====================================================================== #

def mega_of(ww_code):
    """Mã ww -> nhãn mega-bucket (None nếu chưa gán / không thuộc nhóm nào)."""
    return BUCKETS["hien_tuong"]["groups"].get(ww_code)


def _sub_index(x):
    """Buổi: nhãn 'toi'/'dem'/... hoặc chỉ số 0..4 -> chỉ số (None nếu lạ/thiếu)."""
    if x is None:
        return None
    subs = BUCKETS["hien_tuong"]["sub_buckets"]
    if isinstance(x, str):
        return subs.index(x) if x in subs else None
    return int(x)


def sub_of_hour(hour):
    """
    GIỜ quan trắc (0-23; 24 -> 0) -> nhãn buổi, theo ánh xạ trong config:
      tối 19->24 | đêm 0->5 | sáng 5->10 | trưa 10->14 | chiều 14->19.
    Trả None nếu thiếu giờ.
    """
    if hour is None:
        return None
    h = int(hour) % 24
    for name, (lo, hi) in BUCKETS["hien_tuong"]["sub_hours"].items():
        if lo <= h < hi:
            return name
    return None


def score_phenomenon(forecast_mega, forecast_sub, obs_mega, obs_hour):
    """
    forecast_mega / obs_mega : nhãn mega-bucket (loại hiện tượng).
        Nếu quan trắc còn là mã ww thì map trước bằng mega_of().
    forecast_sub : buổi DỰ BÁO viên chọn ('toi'..'chieu' hoặc chỉ số 0..4).
    obs_hour     : GIỜ quan trắc (0-23) -> tự quy ra buổi bằng sub_of_hour().

    Đúng khi: MEGA khớp CHÍNH XÁC (tolerance 0) VÀ buổi lệch <= sub_tolerance
    (kẹp mép, KHÔNG cuộn vòng).
    Trả True/False, hoặc None nếu thiếu dữ liệu.
    """
    spec = BUCKETS["hien_tuong"]
    if forecast_mega is None or obs_mega is None:
        return None
    if forecast_mega != obs_mega:            # tầng mega: chính xác 100%
        return False
    fi = _sub_index(forecast_sub)
    oi = _sub_index(sub_of_hour(obs_hour))   # nhúng ánh xạ giờ -> buổi
    if fi is None or oi is None:
        return None
    n = len(spec["sub_buckets"])
    d = abs(fi - oi)
    if spec.get("sub_circular"):
        d = min(d, n - d)                    # (hiện tắt: kẹp mép)
    return d <= spec.get("sub_tolerance", 1)
