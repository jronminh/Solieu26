"""
scorer.py
====================
Bộ máy chấm điểm cho 6 trường dự báo: solve_ceiling (giải trần từ các lớp
mây, dùng khi giải quan trắc trước khi chấm) và 6 hàm score_<field> — mỗi
hàm ứng với đúng 1 trường, xem chi tiết ngay tại từng hàm.

Mô hình chung: dự báo viên chọn thẳng 1 bucket (không nhập số); quan trắc
truyền vào qua `obs` — 1 dict giá trị vô hướng đã giải, khóa theo tên 6
trường (`tong_luong_may`, `do_cao_man_may`, `hien_tuong`, `huong_gio`,
`toc_do_gio`, `tam_nhin`) cộng `"hour"` (giờ quan trắc, chỉ score_hien_tuong
cần). Mỗi hàm score_<field> tự đọc đúng entry BUCKETS["<field>"] của mình
và tự lấy trong `obs` những gì nó cần — kể cả từ trường khác, như
score_huong_gio cần obs["toc_do_gio"] để xét regime gió.

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
# HELPER DÙNG CHUNG — chỉ vì phép toán giống hệt nhau giữa 2 trường,      #
# tham số truyền tường minh (không dispatch theo field/kind).            #
# ====================================================================== #

def _linear_bucket(value, bounds, side="right"):
    """Số vô hướng -> chỉ số bucket theo bounds tăng dần (bisect)."""
    f = bisect_left if side == "left" else bisect_right
    return f(bounds, value)


def _window_hit(windows, forecast_idx, obs_value, tolerance):
    """Đúng khi obs rơi vào hợp của cửa dự báo và ±tolerance cửa kề (kẹp mép)."""
    lo_idx = max(0, forecast_idx - tolerance)
    hi_idx = min(len(windows) - 1, forecast_idx + tolerance)
    lo = windows[lo_idx][0]          # mép dưới cửa thấp nhất được chấp nhận
    hi = windows[hi_idx][1]          # mép trên cửa cao nhất được chấp nhận
    return lo <= obs_value <= hi


# ====================================================================== #
# TỔNG LƯỢNG MÂY — dự báo CHỌN 1 CỬA SỔ trong 9 cửa chồng nhau (idx 0=0-2 #
# ... idx 8=8-10); quan trắc là số nguyên 0-10, so trực tiếp (không       #
# bucket hóa). ±1 áp cho CỬA SỔ dự báo, không phải cho giá trị.           #
# ====================================================================== #

def score_tong_luong_may(forecast_idx, obs):
    """forecast_idx: cửa sổ dự báo viên chọn. obs["tong_luong_may"]: số quan trắc 0-10."""
    spec = BUCKETS["tong_luong_may"]
    obs_value = obs.get("tong_luong_may")
    if forecast_idx is None or obs_value is None or obs_value in spec["na"]:
        return None
    return _window_hit(spec["windows"], forecast_idx, obs_value, spec["tolerance"])


# ====================================================================== #
# ĐỘ CAO MÀN MÂY (trần) — quan trắc phải qua solve_ceiling() trước khi    #
# gọi hàm này (ra mét, hoặc NO_CEILING, hoặc None nếu thiếu dữ liệu).     #
# "Không màn" là BUCKET TRÊN CÙNG, kề bucket cao nhất — ±1 vẫn chạy qua   #
# giữa 2 trạng thái đó, không phải bỏ cặp.                                #
# ====================================================================== #

def score_do_cao_man_may(forecast_idx, obs):
    """forecast_idx: bucket dự báo viên chọn. obs["do_cao_man_may"]: mét/NO_CEILING/None."""
    spec = BUCKETS["do_cao_man_may"]
    obs_value = obs.get("do_cao_man_may")
    if forecast_idx is None or obs_value is None or obs_value in spec["na"]:
        return None
    if obs_value == spec["no_ceiling"]:
        obs_idx = len(spec["bounds"]) + 1
    else:
        obs_idx = _linear_bucket(obs_value, spec["bounds"], spec["side"])
    return abs(forecast_idx - obs_idx) <= spec["tolerance"]


# ====================================================================== #
# TẦM NHÌN — biến thẳng, quan trắc là 1 số km, bucket hóa rồi so ±1       #
# bucket với bucket dự báo.                                               #
# ====================================================================== #

def score_tam_nhin(forecast_idx, obs):
    """forecast_idx: bucket dự báo viên chọn. obs["tam_nhin"]: số km quan trắc."""
    spec = BUCKETS["tam_nhin"]
    obs_value = obs.get("tam_nhin")
    if forecast_idx is None or obs_value is None or obs_value in spec["na"]:
        return None
    obs_idx = _linear_bucket(obs_value, spec["bounds"], spec["side"])
    return abs(forecast_idx - obs_idx) <= spec["tolerance"]


# ====================================================================== #
# GIÓ (tốc độ + hướng) — regime theo TỐC ĐỘ QUAN TRẮC (xem TODO.md: cơ sở #
# này còn chờ xác nhận):                                                  #
#   - obs_speed <= 2 m/s : CHỈ chấm tốc độ, bỏ hướng                     #
#   - obs_speed > 15 m/s : CHỈ chấm hướng, bỏ tốc độ                     #
#   - 2 < obs_speed <= 15: chấm cả hai                                   #
# score_huong_gio() tự đọc obs["toc_do_gio"] để xét regime — không có 1  #
# hàm riêng "ghép cặp" đứng ngoài gọi cả hai.                             #
# ====================================================================== #

WIND_NO_DIR_MAX   = 2    # tốc độ <= 2 m/s -> không chấm HƯỚNG
WIND_NO_SPEED_MIN = 15   # tốc độ > 15 m/s -> không chấm TỐC ĐỘ


def score_toc_do_gio(forecast_idx, obs):
    """forecast_idx: cửa sổ tốc độ dự báo viên chọn. obs["toc_do_gio"]: tốc độ quan trắc (m/s)."""
    spec = BUCKETS["toc_do_gio"]
    obs_speed = obs.get("toc_do_gio")
    if obs_speed is None or obs_speed in spec["na"]:
        return None
    if obs_speed > WIND_NO_SPEED_MIN:
        return None
    if forecast_idx is None:
        return None
    return _window_hit(spec["windows"], forecast_idx, obs_speed, spec["tolerance"])


def score_huong_gio(forecast_idx, obs):
    """
    forecast_idx: hướng dự báo viên chọn (chỉ số 0..15 hoặc nhãn).
    obs["huong_gio"]: hướng quan trắc. obs["toc_do_gio"]: tốc độ quan trắc,
    dùng để xét regime — <= WIND_NO_DIR_MAX thì không chấm hướng.
    """
    spec = BUCKETS["huong_gio"]
    obs_speed = obs.get("toc_do_gio")
    if obs_speed is None or obs_speed <= WIND_NO_DIR_MAX:
        return None
    obs_dir = obs.get("huong_gio")
    if forecast_idx is None or obs_dir is None or obs_dir in spec["na"]:
        return None
    labels = spec.get("labels")
    obs_idx = labels.index(obs_dir) if isinstance(obs_dir, str) else int(obs_dir)
    d = abs(forecast_idx - obs_idx)
    d = min(d, spec["n"] - d)         # cuộn vòng
    return d <= spec["tolerance"]


# ====================================================================== #
# HIỆN TƯỢNG — 2 tầng: MEGA (loại, khớp chính xác) × SUB (buổi, ±1 kẹp   #
# mép). GIỜ quan trắc -> buổi bằng sub_of_hour() (ánh xạ trong config).   #
# Đúng khi MEGA khớp đúng VÀ buổi lệch <= 1.                              #
# ====================================================================== #

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


def score_hien_tuong(forecast_mega, forecast_sub, obs):
    """
    forecast_mega : nhãn mega-bucket dự báo viên chọn.
    forecast_sub  : buổi DỰ BÁO viên chọn ('toi'..'chieu' hoặc chỉ số 0..4).
    obs["hien_tuong"] : mega ĐÃ quy đổi sẵn từ mã ww gốc — adapter
        (pipeline_obs.py::ww_code_to_mega()) làm việc này trước khi gọi vào
        đây, không phải mã ww thô.
    obs["hour"]        : GIỜ quan trắc (0-23) — tự quy ra buổi bằng sub_of_hour().

    Đúng khi: MEGA khớp CHÍNH XÁC (tolerance 0) VÀ buổi lệch <= sub_tolerance
    (kẹp mép, KHÔNG cuộn vòng).
    Trả True/False, hoặc None nếu thiếu dữ liệu.
    """
    spec = BUCKETS["hien_tuong"]
    obs_mega = obs.get("hien_tuong")
    if forecast_mega is None or obs_mega is None:
        return None
    if forecast_mega != obs_mega:            # tầng mega: chính xác 100%
        return False
    fi = _sub_index(forecast_sub)
    oi = _sub_index(sub_of_hour(obs.get("hour")))   # nhúng ánh xạ giờ -> buổi
    if fi is None or oi is None:
        return None
    n = len(spec["sub_buckets"])
    d = abs(fi - oi)
    if spec.get("sub_circular"):
        d = min(d, n - d)                    # (hiện tắt: kẹp mép)
    return d <= spec.get("sub_tolerance", 1)
