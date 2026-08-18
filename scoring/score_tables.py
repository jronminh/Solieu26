"""
score_tables.py
====================
Cấu hình bucket cho 6 trường dự báo được chấm điểm: tổng lượng mây, độ cao
màn mây (trần), hiện tượng, hướng gió, tốc độ gió, tầm nhìn.

Chỉ chứa dữ liệu (BUCKETS + hằng số NO_CEILING) — không có hàm chấm điểm ở
đây; mỗi trường có 1 hàm chấm riêng trong scorer.py, tự đọc đúng entry của
mình (không có field chung nào điều khiển cách đọc bảng).

Mô hình chung: dự báo viên chọn thẳng 1 bucket (không nhập số); quan trắc là
1 giá trị vô hướng, được quy về dạng so được rồi so lệch với bucket dự báo
trong phạm vi tolerance của trường đó.

Vài mốc nghiệp vụ (đơn vị gió/tầm nhìn, mép 6000m/10km) còn chờ xác nhận —
xem TODO.md.

Lược đồ mỗi trường (field nào có thì scorer.py mới cần, không phải trường
nào cũng có đủ):
  tolerance : số bucket lệch vẫn tính đúng. 1 = luật ±1; 0 = phải khớp đúng bucket.
  na        : các giá trị coi là "không chấm" -> scorer BỎ CẶP ở trường này
  bounds    : ngưỡng TRONG, tăng dần; n ngưỡng -> n+1 bucket (trường tuyến tính)
  side      : "right": [dưới, trên); "left": (dưới, trên]
  n, labels : số hướng, nhãn từng hướng (trường vòng). Giá trị là CHỈ SỐ hướng
              0..n-1 (hoặc nhãn), KHÔNG phải độ; ±1 cuộn vòng.
  windows   : [(lo,hi),...] cửa sổ chồng nhau (quan trắc so trực tiếp, không bucket hóa)

Quy đổi từ MÃ QUAN TRẮC THÔ (độ gió, mã ww...) sang từ vựng bucket ở đây
KHÔNG nằm trong module này - đó là việc của adapter (pipeline/obs.py), xem
vd wind_dd_to_huong_gio()/ww_code_to_mega() ở đó. Module này chỉ mô tả HÌNH
DẠNG bucket (dự báo viên chọn gì), không biết quan trắc thô ánh xạ vào đó
thế nào.
"""

# Sentinel cho trạng thái "không có trần" (trường do_cao_man_may) — là một
# BUCKET (trên cùng), không phải "thiếu số liệu".
NO_CEILING = "không màn"

BUCKETS = {

    # ------------------------------------------------------------------ #
    # 1. TỔNG LƯỢNG MÂY — chấm khác 5 trường kia. Đơn vị: phần bầu trời   #
    #    (0-10).                                                          #
    #                                                                    #
    #    Dự báo viên CHỌN 1 CỬA SỔ (không nhập số): 9 cửa sổ chồng nhau,  #
    #    mỗi cửa rộng 2, bước 1 (idx 0=0-2 ... idx 8=8-10). Quan trắc là  #
    #    một số nguyên 0-10 (không bucket hóa).                           #
    #                                                                    #
    #    ±1 áp cho CỬA SỔ dự báo, không phải cho giá trị: dự báo idx i -> #
    #    dải chấp nhận là hợp của cửa i-1, i, i+1 (kẹp mép ở idx 0 và 8).  #
    #    VD: dự báo "2-4" (idx 2) -> đúng nếu số thực rơi trong [1,5].     #
    #                                                                    #
    #    Chấm bằng score_tong_luong_may() — trường này không có bounds/side.#
    # ------------------------------------------------------------------ #
    "tong_luong_may": {
        # (lo, hi) mỗi cửa sổ, inclusive hai đầu. Index = lựa chọn dự báo viên.
        "windows": [(0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
                    (5, 7), (6, 8), (7, 9), (8, 10)],
        "tolerance": 1,          # ±1 CỬA SỔ dự báo (không phải ±1 giá trị)
        "na": ["/"],             # quan trắc che khuất -> bỏ cặp (thực tế hiếm)
    },

    # ------------------------------------------------------------------ #
    # 2. ĐỘ CAO MÀN MÂY (trần) — không lấy thẳng từ mã, cần giải qua      #
    #    solver riêng ra mét. 15 bucket theo thứ tự:                      #
    #    <50 | 50-100 | 100-150 | 150-200 | 200-300 | 300-400 | 400-500 |#
    #    500-600 | 600-1000 | 1000-1500 | 1500-2000 | 2000-2500 |        #
    #    2500-6000 | >6000 | KHÔNG MÀN                                    #
    #                                                                    #
    #    "Không màn" là BUCKET TRÊN CÙNG, kề ">6000" (không phải bỏ cặp)  #
    #    nên ±1 vẫn chạy giữa 2 trạng thái đó.                            #
    #                                                                    #
    #    side="right": giá trị bằng ngưỡng rơi vào bucket TRÊN (khớp      #
    #    "<50", và 6000 m vào ">6000"). Nhiều mốc trùng giá trị thật có   #
    #    thể gặp trong dữ liệu — side quyết định bucket của chúng.        #
    # ------------------------------------------------------------------ #
    "do_cao_man_may": {
        # 13 ngưỡng -> 14 bucket số (index 0..13); "không màn" = index 14 -> 15 lựa chọn.
        "bounds": [50, 100, 150, 200, 300, 400, 500, 600,
                   1000, 1500, 2000, 2500, 6000],
        "side": "right",
        "tolerance": 1,               # ±1 BUCKET (dù các bucket không chồng nhau)
        # "không màn" là 1 bucket (index cao nhất), không phải bỏ cặp — solver
        # trả sentinel này khi không lớp mây nào đạt ngưỡng trần, kể cả trời quang.
        "no_ceiling": NO_CEILING,
        "na": [None],                 # None = THIẾU số liệu thật (khác "không màn") -> bỏ cặp
        # Quan trắc: số mét, hoặc NO_CEILING nếu không có trần, hoặc None nếu thiếu.
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
    #    Chấm: MEGA khớp đúng VÀ buổi lệch <= 1 -> đúng.                  #
    # ------------------------------------------------------------------ #
    "hien_tuong": {
        # 2 tầng: mega (exact) × sub (±1 kẹp mép)
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
        # Quy đổi MÃ ww GỐC -> mega không còn ở đây - xem
        # pipeline/obs.py::ww_code_to_mega() (chuyển 2026-08-18, cùng lý do
        # wind_dd_to_huong_gio() không nằm ở BUCKETS["huong_gio"]).
        # --- TẦNG SUB: buổi trong ngày, ±1 kẹp mép ---
        "sub_buckets": ["toi", "dem", "sang", "trua", "chieu"],
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
    # 4. HƯỚNG GIÓ — biến vòng, 16 hướng = 16 bucket.                    #
    #    Index 0 = N, theo chiều kim đồng hồ (0=N,1=NNE,...,15=NNW).      #
    #    Dự báo lẫn quan trắc đều là HƯỚNG rời rạc (0..15 hoặc nhãn),     #
    #    không phải độ. ±1 hướng, cuộn vòng: N (0) kề NNW (15) và NNE(1).#
    #    Ghép cặp với tốc độ gió khi chấm: có/không chấm hướng phụ thuộc  #
    #    tốc độ (<=2 m/s thì bỏ hướng).                                   #
    # ------------------------------------------------------------------ #
    "huong_gio": {
        "n": 16,
        "labels": ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"],
        "tolerance": 1,               # ±1 hướng, cuộn vòng
        "na": [None],                 # VRB / lặng -> hướng không xác định -> bỏ cặp
        # Nếu đầu vào là nhãn ("N", "NNE"...) thì map qua "labels"; nếu là độ
        # thì phải quy về 1 trong 16 hướng trước khi vào đây.
    },

    # ------------------------------------------------------------------ #
    # 5. TỐC ĐỘ GIÓ — cửa sổ chồng nhau như tổng lượng mây. Đơn vị m/s.  #
    #    Cửa rộng 3, bước 1: 0-3,1-4,2-5,...,15-18, cửa cuối "16-21 và    #
    #    kéo dài thêm" -> coi là 16 trở lên. Quan trắc: số 0..16 m/s.     #
    #    Dự báo viên chọn 1 cửa.                                          #
    #                                                                    #
    #    Ghép cặp với hướng gió khi chấm: tốc độ >15 m/s thì bỏ chấm tốc  #
    #    độ; khi được chấm thì áp ±1 cửa (score_toc_do_gio).              #
    # ------------------------------------------------------------------ #
    "toc_do_gio": {
        # cửa rộng 3, bước 1 (lo=0..15) + cửa cuối 16 trở lên. Quan trắc tối
        # đa 16 nên mép trên vô hạn không ảnh hưởng điểm.
        "windows": [(i, i + 3) for i in range(16)] + [(16, float("inf"))],
        "tolerance": 1,          # ±1 cửa (áp khi tốc độ được chấm, xem score_toc_do_gio)
        "na": [None],
    },

    # ------------------------------------------------------------------ #
    # 6. TẦM NHÌN — biến thẳng, đơn vị km.                                #
    #    <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10           #
    #    Dự báo viên chọn 1 trong 8 bucket; quan trắc là 1 số km -> bucket #
    #    hóa -> so ±1 bucket với bucket dự báo.                          #
    #    side="right": giá trị bằng ngưỡng rơi vào bucket TRÊN (0.5 vào   #
    #    "0.5-1", không vào bucket dưới; 10.0 vào ">10").                #
    # ------------------------------------------------------------------ #
    "tam_nhin": {
        # 7 ngưỡng -> 8 bucket: <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10
        "bounds": [0.5, 1, 1.5, 2, 4, 6, 10],
        "side": "right",
        "tolerance": 1,
        "na": [None],
    },
}
