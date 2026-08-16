"""
buckets.py
====================
CẤU HÌNH BUCKET CHÍNH THỨC cho 6 trường dự báo được chấm: tổng lượng mây, độ
cao màn mây (trần), hiện tượng, hướng gió, tốc độ gió, tầm nhìn.

BUCKETS là dữ liệu thuần (như tables.py). Cuối file là bộ máy chấm: bucket_of
(quy giá trị quan trắc về bucket cho linear/circular), is_hit_window (chấm
kind=forecast_window), solve_ceiling (giải trần từ các lớp mây), và 3 lối vào
chấm score_field / score_wind / score_phenomenon — mỗi lối ứng với một nhóm
kind, xem chi tiết ngay tại từng hàm.

MÔ HÌNH CHUNG: dự báo viên CHỌN THẲNG 1 bucket (không nhập số, không qua
bucket_of); quan trắc là 1 giá trị vô hướng, được quy về dạng so được tùy
kind rồi so lệch với bucket dự báo trong phạm vi tolerance của trường đó.

Một vài chi tiết còn đánh dấu "KIỂM:" ngay tại chỗ (đơn vị gió/tầm nhìn, mép
6000m/10km, bảng mega-nhóm hiện tượng theo mã ww còn để trống) — xử lý khi có
xác nhận, không cần đợi mới dùng phần còn lại của bảng.

Đơn vị mỗi trường phải KHỚP đầu ra của decode.py. Chú thích đơn vị ngay tại từng
trường; chỗ nào tôi phải đoán đơn vị thì có ghi "KIỂM:" — xác nhận lại.

Lược đồ mỗi trường:
  kind        : "linear" | "circular" | "categorical" | "forecast_window"
  unit        : đơn vị của giá trị đã giải (để khỏi lệch đơn vị)
  tolerance   : số bucket lệch vẫn tính đúng. 1 = luật ±1; 0 = phải khớp đúng bucket.
  na          : các giá trị coi là "không chấm" -> scorer BỎ CẶP ở trường này
  source_table: bảng trong tables.py mà giá trị này giải ra từ đó

  linear thêm : bounds (ngưỡng TRONG, tăng dần; n ngưỡng -> n+1 bucket)
                side ("right": [dưới, trên); "left": (dưới, trên])
  circular thêm: n (số hướng), labels (nhãn từng hướng). Giá trị là CHỈ SỐ hướng
                 0..n-1 (hoặc nhãn), KHÔNG phải độ; ±1 cuộn vòng.
  categorical thêm: groups (mã -> nhóm), ordered (False -> không có trục -> tolerance=0)
  forecast_window thêm: windows [(lo,hi),...] cửa sổ chồng nhau (quan trắc so trực tiếp)
"""

from bisect import bisect_left, bisect_right

# Sentinel cho trạng thái "không có trần" (trường do_cao_man_may). Là một BUCKET
# (trên cùng), không phải "thiếu số liệu". Solver và bên nhập dự báo đều dùng hằng
# này thay vì gõ chuỗi trực tiếp, tránh sai khác dấu.
NO_CEILING = "không màn"

BUCKETS = {

    # ------------------------------------------------------------------ #
    # 1. TỔNG LƯỢNG MÂY — CHẤM KHÁC 5 trường kia. BẢNG NGHIỆP VỤ THẬT.   #
    #    Đơn vị: phần bầu trời (0-10).                                    #
    #                                                                    #
    #    Dự báo viên CHỌN 1 CỬA SỔ (không nhập số): 9 cửa sổ chồng nhau,  #
    #    mỗi cửa rộng 2, bước 1:                                          #
    #      idx: 0=0-2  1=1-3  2=2-4  3=3-5  4=4-6  5=5-7  6=6-8  7=7-9    #
    #           8=8-10                                                    #
    #    Quan trắc là MỘT SỐ NGUYÊN 0-10 (KHÔNG bucket hóa). Xác nhận với  #
    #    anh Minh 2026-08-17 — khớp đúng decode.py._oktas_number() (int,   #
    #    hoặc '/' nếu che khuất, xem "na" bên dưới).                       #
    #                                                                    #
    #    ±1 áp cho CỬA SỔ DỰ BÁO, không phải cho giá trị. Đúng khi số     #
    #    quan trắc rơi vào HỢP của cửa dự báo và 2 cửa kề:               #
    #      dự báo idx i -> dải chấp nhận [windows[i-1].lo , windows[i+1].hi]
    #      (kẹp mép ở idx 0 và 8).                                        #
    #    VÍ DỤ: dự báo "2-4" (idx 2) -> hợp cửa 1-3, 2-4, 3-5 -> số thực  #
    #    rơi trong [1,5] thì ĐÚNG.                                        #
    #                                                                    #
    #    >>> KHÔNG dùng bucket_of / is_hit chung. Dùng is_hit_window()    #
    #        ở cuối file. Không có bounds/side ở trường này.              #
    # ------------------------------------------------------------------ #
    "tong_luong_may": {
        "kind": "forecast_window",
        "unit": "phần bầu trời (0-10)",
        "source_table": "N_oktas",
        # (lo, hi) mỗi cửa sổ, inclusive hai đầu. Index = lựa chọn dự báo viên.
        "windows": [(0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
                    (5, 7), (6, 8), (7, 9), (8, 10)],
        "tolerance": 1,          # ±1 CỬA SỔ dự báo (không phải ±1 giá trị)
        "value_range": (0, 10),
        "na": ["/"],             # quan trắc che khuất -> bỏ cặp (thực tế hiếm)
    },

    # ------------------------------------------------------------------ #
    # 2. ĐỘ CAO MÀN MÂY (trần) — KHÔNG lấy thẳng từ mã. Cần SOLVER.      #
    #    BẢNG NGHIỆP VỤ THẬT (đơn vị MÉT), 15 bucket, giữ đúng thứ tự:    #
    #    <50 | 50-100 | 100-150 | 150-200 | 200-300 | 300-400 | 400-500 |#
    #    500-600 | 600-1000 | 1000-1500 | 1500-2000 | 2000-2500 |        #
    #    2500-6000 | >6000 | KHÔNG MÀN                                    #
    #                                                                    #
    #    "Không màn" (không có trần) là BUCKET TRÊN CÙNG, KỀ ">6000" —   #
    #    KHÔNG phải bỏ cặp. Đặt cuối thang nên ±1 vẫn chạy: dự báo        #
    #    ">6000" mà thực tế "không màn" (hoặc ngược lại) lệch 1 -> đúng.  #
    #                                                                    #
    #    side="right": bằng ngưỡng rơi vào bucket TRÊN (khớp "<50").      #
    #    Nhiều mốc (50,100,200,300,600,1000,1500,2000,2500) trùng giá    #
    #    trị hshs có thật -> side quyết định bucket của chúng, để ý.      #
    #    >>> XÁC NHẬN: đúng 6000 m rơi vào ">6000" theo side="right";     #
    #        nếu quy định muốn 6000 thuộc "2500-6000" thì báo để đổi.     #
    # ------------------------------------------------------------------ #
    "do_cao_man_may": {
        "kind": "linear",
        "unit": "mét",
        "source_table": "hshs_special (qua solver)",
        "needs_solver": True,         # cờ cho scorer: chỉ nhánh quan trắc mới giải
        # 13 ngưỡng -> 14 bucket số (index 0..13); "không màn" = index 14 -> 15 lựa chọn.
        "bounds": [50, 100, 150, 200, 300, 400, 500, 600,
                   1000, 1500, 2000, 2500, 6000],
        "side": "right",
        "tolerance": 1,               # ±1 BUCKET (dù các bucket không chồng nhau)
        # "không màn" là BUCKET (index cao nhất = len(bounds)+1 = 14), KHÔNG bỏ cặp.
        # Solver trả sentinel này khi không lớp nào đạt ngưỡng trần — kể cả trời quang.
        "no_ceiling": NO_CEILING,     # xem hằng số ở đầu file
        "na": [None],                 # None = THIẾU số liệu thật (khác "không màn") -> bỏ cặp
        # MODEL CHUNG: dự báo viên chọn 1 trong 15 bucket (kể cả "không màn"); quan trắc
        # là 1 số mét (hoặc NO_CEILING) do solver ra -> bucket hóa -> so ±1 với bucket
        # dự báo. Quy ước: có trần -> số mét; không màn -> NO_CEILING; thiếu -> None.
    },

    # ------------------------------------------------------------------ #
    # 3. HIỆN TƯỢNG — 2 TẦNG: MEGA (loại) × SUB (buổi trong ngày).       #
    #                                                                    #
    #    TẦNG MEGA — loại hiện tượng, khớp CHÍNH XÁC 100% (tolerance 0):  #
    #      0 dông, mưa rào                                                #
    #      1 mưa thường, mưa phùn                                         #
    #      2 sương mù                                                     #
    #      3 mù, mù khô                                                   #
    #      4 N_0 (không có hiện tượng / không thuộc 4 nhóm trên)          #
    #                                                                    #
    #    TẦNG SUB — buổi trong ngày, GIỐNG NHAU trong mọi mega, ±1 KẸP   #
    #    MÉP (n=5): 0 tối, 1 đêm, 2 sáng, 3 trưa, 4 chiều. Dự báo cho     #
    #    24 giờ nên đây là DÃY THẲNG — tối và chiều là hai đầu, KHÔNG kề. #
    #                                                                    #
    #    Chấm: MEGA khớp đúng VÀ buổi lệch <= 1 -> đúng. Dùng            #
    #    score_phenomenon() (2 tầng), KHÔNG dùng score_field.            #
    #    "groups" (mã ww -> mega) CHƯA gán — chờ anh chỉ định.           #
    # ------------------------------------------------------------------ #
    "hien_tuong": {
        "kind": "phenomenon",           # 2 tầng: mega (exact) × sub (±1 vòng)
        "unit": "mega (loại) × sub (buổi)",
        "source_table": "ww + giờ",
        # --- TẦNG MEGA: khớp chính xác ---
        "mega_buckets": [               # 5 mega theo THỨ TỰ
            "dong_mua_rao",
            "mua_mua_phun",
            "suong_mu",
            "mu_mu_kho",
            "N_0",
        ],
        "mega_labels": {
            "dong_mua_rao": "Dông, mưa rào",
            "mua_mua_phun": "Mưa thường, mưa phùn",
            "suong_mu":     "Sương mù",
            "mu_mu_kho":    "Mù, mù khô",
            "N_0":          "Không có hiện tượng (hoặc không thuộc 4 nhóm trên)",
        },
        "mega_tolerance": 0,            # khớp chính xác 100%
        # mã ww (2 ký tự, KHỚP KHÓA tables.py["ww"]) -> mega. Đã gán theo xác
        # nhận với anh Minh 2026-08-16:
        #   - 13 (chớp không sấm), 18 (tố), 19 (vòi rồng): báo hiệu/đi kèm dông
        #     -> gộp dong_mua_rao.
        #   - 04 (khói), 06 (bụi lơ lửng): lithometeor giảm tầm nhìn như mù khô
        #     -> gộp mu_mu_kho.
        #   - 66,67 (mưa đông kết), 68,69 (mưa+tuyết), 83-86 (rào lẫn
        #     tuyết/tuyết rào): hiếm gặp VN -> N_0 hết, không tách riêng.
        #   - 20-29 (hiện tượng "giờ trước"): TÍNH NHƯ hiện tượng hiện tại,
        #     xếp theo loại (20,25,28,29 v.v.), không gộp hết vào N_0.
        #
        # >>> CẢNH BÁO KHỚP NHÃN: decode_weather() (decode.py:127) hiện chỉ trả
        #     NHÃN tiếng Việt của ww, KHÔNG giữ mã gốc. Mã 64/65 ("Mưa to" =
        #     mưa thường to -> mua_mua_phun) và mã 82 ("Mưa to" = mưa rào dữ
        #     dội -> dong_mua_rao) có CÙNG NHÃN "Mưa to" nhưng KHÁC mega-bucket.
        #     mega_of() ở đây dùng MÃ làm khóa nên tự nó đúng, nhưng nếu bên gọi
        #     (decode.py) chỉ còn giữ nhãn thì không phân biệt được 2 trường hợp
        #     này -> PHẢI sửa decode_weather() giữ lại mã gốc (vd trả thêm
        #     "ww_code": token[1:3]) trước khi nối buckets.py vào pipeline chấm điểm.
        "groups": {
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
            # --- N_0: phần còn lại (mây tan/hình thành/không đổi, mưa xa chưa
            #     tới trạm, tuyết/băng/mưa đông kết/hỗn hợp mưa-tuyết hiếm gặp
            #     VN, bụi/lốc bụi/bão bụi-cát/tuyết cuốn) ---
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
        },
        # --- TẦNG SUB: buổi trong ngày, ±1 kẹp mép ---
        "sub_buckets": ["toi", "dem", "sang", "trua", "chieu"],
        "sub_labels": {
            "toi": "Tối", "dem": "Đêm", "sang": "Sáng",
            "trua": "Trưa", "chieu": "Chiều",
        },
        # Ánh xạ GIỜ quan trắc -> buổi: [giờ bắt đầu, giờ kết thúc). Nghiệp vụ
        # tách rõ tối (19->24) và đêm (0->5) nên không khoảng nào cuộn qua nửa đêm.
        "sub_hours": {
            "toi":   (19, 24),
            "dem":   (0, 5),
            "sang":  (5, 10),
            "trua":  (10, 14),
            "chieu": (14, 19),
        },
        "sub_tolerance": 1,             # ±1 buổi
        "sub_circular": False,          # KHÔNG cuộn vòng: dự báo 24h, tối..chiều là
                                        # một dãy thẳng, tối và chiều là hai đầu, kẹp mép
        "na": [],
    },

    # ------------------------------------------------------------------ #
    # 4. HƯỚNG GIÓ — biến VÒNG, 16 hướng = 16 bucket. BẢNG NGHIỆP VỤ.    #
    #    index 0 = N, theo chiều kim đồng hồ (0=N,1=NNE,...,15=NNW).      #
    #    Cả DỰ BÁO lẫn QUAN TRẮC đều là HƯỚNG rời rạc (0..15 hoặc nhãn),  #
    #    KHÔNG phải độ -> không quy đổi độ, giá trị đã là chỉ số hướng.   #
    #    ±1 hướng, CUỘN VÒNG: N (0) kề NNW (15) và NNE (1).              #
    #    Coupling với tốc độ: CHẤM QUA score_wind() (không gọi lẻ), vì    #
    #    có/không chấm hướng phụ thuộc tốc độ (<=2 m/s thì bỏ hướng).     #
    # ------------------------------------------------------------------ #
    "huong_gio": {
        "kind": "circular",
        "unit": "hướng (16 hướng, 0=N, chiều kim đồng hồ)",
        "source_table": "(dd -> 16 hướng)",
        "n": 16,
        "labels": ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"],
        "tolerance": 1,               # ±1 hướng, cuộn vòng
        "na": [None],                 # VRB / lặng -> hướng không xác định -> bỏ cặp
        # obs & forecast đều là chỉ số hướng 0..15 (hoặc nhãn "N"/"NNE"...).
        # Nếu decode trả nhãn thì bucket_of tự map qua "labels"; nếu trả độ thì
        # phải quy về 1 trong 16 hướng TRƯỚC khi vào đây.
        # Quy tắc CÓ/KHÔNG chấm hướng (theo tốc độ) nằm ở score_wind().
    },

    # ------------------------------------------------------------------ #
    # 5. TỐC ĐỘ GIÓ — CỬA SỔ CHỒNG NHAU như tổng lượng mây. Đơn vị m/s.  #
    #    BẢNG NGHIỆP VỤ: cửa rộng 3, bước 1: 0-3,1-4,2-5,...,15-18, rồi   #
    #    cửa cuối "16-21 và kéo dài thêm" -> coi là 16 TRỞ LÊN.          #
    #    Quan trắc: số 0..16 m/s. Dự báo viên chọn 1 cửa.               #
    #                                                                    #
    #    CHẤM QUA score_wind() (không gọi lẻ): tốc độ >15 m/s thì bỏ     #
    #    chấm tốc độ. Khi được chấm thì dùng ±1 cửa (model chung).       #
    # ------------------------------------------------------------------ #
    "toc_do_gio": {
        "kind": "forecast_window",
        "unit": "m/s",
        "source_table": "(ff trong mã)",
        # cửa rộng 3, bước 1 (lo=0..15) + cửa cuối 16 trở lên. Nghiệp vụ ghi
        # "16-21 và kéo dài thêm"; quan trắc tối đa 16 nên mép trên vô hạn
        # không ảnh hưởng điểm.
        "windows": [(i, i + 3) for i in range(16)] + [(16, float("inf"))],
        "tolerance": 1,          # ±1 cửa (model chung; áp khi tốc độ được chấm)
        "value_range": (0, 16),
        "na": [None],
        # Quy tắc CÓ/KHÔNG chấm tốc độ (theo regime tốc độ) nằm ở score_wind().
    },

    # ------------------------------------------------------------------ #
    # 6. TẦM NHÌN — biến THẲNG. BẢNG NGHIỆP VỤ THẬT (đơn vị KM).         #
    #    <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10           #
    #    MODEL CHUNG: dự báo viên chọn 1 trong 8 bucket; quan trắc là 1   #
    #    số km -> bucket hóa -> so ±1 BUCKET với bucket dự báo (đúng khi  #
    #    lệch <= 1 bucket, dù các bucket không chồng nhau).               #
    #    side="right": giá trị bằng ngưỡng rơi vào bucket TRÊN.          #
    #      -> khớp "dưới 0.5" (0.5 vào "0.5-1", không vào bucket dưới),  #
    #         và 0.5/1/2/4 (là giá trị quan trắc có thật) vào bucket trên#
    #    >>> XÁC NHẬN: theo side="right", đúng 10.0 km rơi vào ">10".    #
    #        Nếu quy định muốn 10 thuộc "6-10" thì báo để xử lý mép trên.#
    # ------------------------------------------------------------------ #
    "tam_nhin": {
        "kind": "linear",
        "unit": "km",
        "source_table": "VV_special",
        # 7 ngưỡng -> 8 bucket: <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10
        "bounds": [0.5, 1, 1.5, 2, 4, 6, 10],
        "side": "right",
        "tolerance": 1,
        "na": [None],
    },
}


# ====================================================================== #
# SOLVER MÀN MÂY (nghiệp vụ)                                              #
# Đặt trong file này theo yêu cầu (dù về bản chất là logic, không phải    #
# data thuần như phần trên). Bên quan trắc gọi để ra 1 giá trị trần rồi   #
# mới bucket hóa; bên dự báo nhập thẳng nên KHÔNG gọi solver.             #
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
# Regime theo TỐC ĐỘ QUAN TRẮC:  [GIẢ ĐỊNH — xác nhận obs hay dự báo]    #
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


