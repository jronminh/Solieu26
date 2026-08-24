# Changelog

Các thay đổi đáng chú ý của Solieu26, mới nhất lên đầu. Chi tiết từng commit
xem `git log`; việc đang mở/chưa quyết xem `TODO.md` (file local, không nằm
trong repo).

## v5.0 — 2026-08-16 → 2026-08-24

### Thiết kế lại UI theo mockup (`reference/Redesign Solieu26 (ban Tkinter thuc te).dc.html`)
- Thêm cửa sổ "Dự báo" (`forecast_editor.py`): dự báo viên nhập bucket cho 6
  trường theo trạm + khoảng giờ, 1 file/ngày nhiều trạm
  (`forecast_YYYYMMDD.csv`), luôn nạp lại toàn bộ file cũ trước khi ghi để
  không mất dự báo của trạm khác. Mở từ nút riêng ở cửa sổ chính (không còn
  ràng buộc "chỉ mở từ Viewer" như đặc tả ban đầu).
- Thêm cửa sổ "Xem chấm điểm dự báo" (`score_viewer.py`), đọc
  `score_YYYYMMDD.csv` (chỉ đọc, không tự chạy `export_forecast_score()`):
  có dropdown Trạm (đặc tả gốc định ẩn, nhưng `join_forecast_obs()` đã ghép
  đa trạm xong nên hiện luôn), tô màu dòng theo Đạt/Không đạt/Bỏ cặp, 2 chế
  độ xem 1 trường / cả 6 trường.
- "Tải số liệu theo khoảng" chuyển từ `AdvancedDialog` (Toplevel riêng) sang
  1 panel nhúng thẳng trong cửa sổ chính, luôn hiện; bỏ nút "Làm mới" (panel
  luôn có sẵn ngày mặc định = hôm nay nên nút "Bắt đầu" thay thế được). Auto-
  query tạm dừng theo "có đang chạy 1 lượt tải hay không"
  (`Runner._run_in_progress`) thay vì theo dialog có đang mở hay không.
- Cửa sổ chính thêm banner tạm dừng, progress bar %, log giới hạn 2000 dòng
  (tự xoá dòng cũ, hiện số dòng hiện tại/giới hạn).
- Dialog "Thiết lập": bỏ auto-apply riêng cho khối "Tự động truy vấn" khi mất
  focus/Enter, dùng chung 1 chỉ báo "có thay đổi chưa lưu" + nút "Lưu thiết
  lập" cho mọi field, thêm toast "Đã lưu lúc HH:MM".
- Viewer ("Xem số liệu"): bỏ nút "Làm mới"/"Mở bằng Excel", đổi tên "Hiển
  thị" thành "Thiết lập...", thêm chú thích khi lọc Trạm = "Tất cả các
  trạm", cột `station_code`/`lat`/`lon` chuyển từ ẩn cứng sang mặc định ẩn
  nhưng bật lại được qua "Thiết lập...".

### Chương trình chấm điểm dự báo (mới)
- Thêm chương trình con chấm điểm dự báo cho 6 trường (tổng lượng mây, độ
  cao màn mây, hiện tượng, hướng gió, tốc độ gió, tầm nhìn): tách bảng bucket
  thuần dữ liệu (`scoring/score_tables.py`) khỏi engine so dự báo/quan trắc
  (`scoring/scorer.py`).
- Thêm adapter quan trắc → dict `obs` cho scorer (`pipeline/obs.py`): quy đổi
  hướng gió độ sang 16 hướng, mã `ww` sang mega-nhóm hiện tượng theo mã gốc
  (không theo nhãn, tránh 2 mã trùng nhãn khác nhóm).
- Thêm matcher ghép dự báo↔quan trắc theo giờ + driver chấm điểm hàng loạt
  (`pipeline/match_score.py`, tên khi thêm là `pipeline_scoring.py`).
- Giải thêm nhóm mây dông Cb (storm: hướng/khoảng cách/xu thế) quanh trạm khi
  decode bulletin.
- Đổi `scorer.py` từ dispatch chung qua field `"kind"` sang mỗi trường 1 hàm
  `score_<field>()` tự đọc entry `BUCKETS` của mình.
- UI đầu tiên cho dự báo viên chọn bucket (stage 2, đứng riêng, chưa nối vào
  `main.py`) viết rồi gãy khi `scorer.py` đổi chữ ký ở trên; module CRUD
  (`pipeline_forecast.py`) xoá hẳn, UI (`forecast_bucket_generator.py`)
  chuyển sang `reference/` làm tham khảo thiết kế, không còn chạy được —
  giai đoạn "Dự báo" của pipeline chấm điểm quay lại vạch xuất phát.
- Thêm `pipeline/forecast.py::export_forecast_table()` — ghi archive dự báo
  viên nhập (`forecast_YYYYMMDD.csv`) độc lập với quan trắc; đổi
  `export_forecast_score()` nhận đường dẫn file thay vì list, output đổi tên
  `score_YYYYMMDD.csv` để không đụng file archive.
- Ghép đúng theo TRẠM xuyên suốt pipeline dự báo/chấm điểm (trước đó mỗi giờ
  chỉ lấy 1 bản ghi đại diện, bỏ qua các trạm còn lại): `build_hourly_table()`
  (`pipeline/forecast.py`) và `build_scalar_history()` (`pipeline/obs.py`)
  giờ trả về theo từng `station_code` (mã trạm thật, từ
  `location.station_code`, không phải tên đã giải mã); `join_forecast_obs()`
  ghép theo `(station_code, hour)`, do quan trắc dẫn dắt (mọi trạm báo cáo
  đều ra 1 dòng, kể cả trạm chưa ai dự báo). `score_YYYYMMDD.csv` giờ nhiều
  trạm/file (cột `station_code`), giống quy ước `history_YYYYMMDD.csv`.
- Nối `export_forecast_score()` vào `runner.py` (2026-08-22): sau
  `export_history_by_date()` chạy xong, với mỗi ngày vừa tải quan trắc mà đã
  có sẵn `forecast_YYYYMMDD.csv`, tự gọi `export_forecast_score()` để sinh/
  cập nhật `score_YYYYMMDD.csv` — không cần thao tác thêm; trước đó chỉ có
  `score_viewer.py` đọc file, không ai từng ghi ra. `local_files` lọc xuống
  đúng 1 ngày trước khi gọi (mỗi ngày dùng đúng `forecast_YYYYMMDD.csv` của
  ngày đó) để 1 lần tải nhiều ngày không áp nhầm dự báo ngày A cho ngày B;
  lỗi chấm điểm chỉ log, không làm hỏng kết quả `export_history_by_date()`
  đã xong. Thêm `ScoreViewer.refresh_date_list()` (theo mẫu
  `HistoryViewer.refresh_date_list()`) để tab "Xem chấm điểm" tự thấy ngày
  mới mà không cần thao tác gì thêm.
- Tách "không báo cáo ww" khỏi "có báo cáo, không hiện tượng gì đáng kể"
  trong `pipeline/obs.py::ww_code_to_mega()` (2026-08-24, xác nhận nghiệp
  vụ): `ww_code is None` giờ trả `None` (bỏ cặp, thiếu dữ liệu thật) thay
  vì trả nhóm "không có hiện tượng" như trước — trước đây 2 trường hợp này
  bị gộp làm một, có thể chấm SAI khi thực ra chỉ là mất dữ liệu, không
  phải quan trắc viên xác nhận trời quang. Mega-bucket "N_0" (mã có báo cáo
  nhưng không có hiện tượng gì đáng kể) đổi tên thành `"khong"`, nhãn hiển
  thị rút gọn thành "Không" (`scoring/score_tables.py`).

### Tái cấu trúc module
- Tách `pipeline.py`/`core.py` cũ thành các khối độc lập không import lẫn
  nhau: `pipeline/fetch.py` (FTP) và `pipeline/decode.py` (giải mã + xuất
  CSV, sau đổi tên `pipeline/decode_files.py`).
- Tách `decode_wind()` thành `decode_total_cloud()` (tổng lượng mây) +
  `decode_wind()` (hướng/tốc độ gió) — token gộp cả 2 trường, tên `wind` cho
  cả 2 là bug cũ.
- Gom tiện ích/codec/chấm điểm vào package riêng: `utils/`, `bulletin/`,
  `scoring/`; đổi tên các module rời theo quy ước `pipeline_*` rồi gộp hẳn
  vào package `pipeline/`.
- Tách `gui.py` thành `main.py` (App) + `common.py` (hằng số/tiện ích UI
  dùng chung) + `runner.py` (worker thread chạy pipeline) + `auto_query.py`
  (timer tự động truy vấn) + `viewer.py` ("Xem số liệu") + `dialogs.py`
  (Thiết lập/Tải số liệu).
- Đổi tên `pipeline/scoring.py` → `pipeline/match_score.py` và
  `pipeline/decode.py` → `pipeline/decode_files.py` để hết trùng tên với
  package `scoring/` và `bulletin/decode.py`; chuyển
  `bulletin/bulletin_generator.py` → `tools/bulletin_generator.py` (tool Tk
  không thuộc lớp "thuần, không I/O ngoài đọc file" mà `bulletin/` tự nhận).

### Test & tài liệu
- Viết lại bộ test theo các đợt refactor decode/encode/scoring ở trên (168
  test hiện tại, `tests/`).
- Thêm README (tổng quan, cấu trúc mã nguồn, hướng dẫn chạy) và giấy phép
  MIT.
- `TODO.md` chuyển thành file theo dõi việc local-only, gỡ khỏi git.

## v4.0 — 2026-08-16

- Thêm `encode.py` (chiều ngược `decode.py`) và `bulletin_generator.py` —
  tool Tk độc lập sinh bản ghi điện báo mẫu để test mà không cần tải FTP
  thật; sau đó viết lại UI theo góp ý thành bảng theo khoảng thời gian, panel
  sửa dòng dock cố định bên phải (không phải popup).
- Tách bảng tra cứu mã `TABLES` ra khỏi `decode.py` để `encode.py` dùng
  chung mà không phải import cả module `decode.py`.
- Thêm bộ test pytest đầu tiên (74 test) cho decode/encode/pipeline/
  bulletin_generator.

## v3.0 — 2026-08-16

- Thêm `TODO_CLAUDE_CODE.md` làm roadmap/changelog sống (tiền thân của
  `TODO.md`/`CHANGELOG.md` hiện tại).
- Đổi tên `core.py` → `pipeline.py` — tên "core" không còn mô tả đúng vai
  trò sau khi tách module.

## v2.0 — 2026-08-12 → 2026-08-16

- Dọn UI: gộp menu Tùy chọn/Trợ giúp, khoá control nâng cao vào checkbox,
  luôn hiện nút xem thay vì ẩn trong menu, tự chạy truy vấn khi khởi động.
- Viewer: thêm lọc theo giờ/ngày, đổi tên nút thành "Xem số liệu"; bỏ xuất
  `latest.csv` gộp, chuyển sang 1 file `history_YYYYMMDD.csv`/ngày, viewer
  chọn file theo ngày.
- Chuyển nơi lưu số liệu sang thư mục home người dùng, đơn giản hoá quản lý
  `config.ini`.
- Tách `core.py`/`gui.py` thành các module riêng với class dialog độc lập
  (`SettingsDialog`, `AdvancedDialog`), rút gọn Settings dialog.

## v1.0 — 2026-08-11 → 2026-08-12

- Khởi tạo repo: lõi tải/giải mã số liệu quan trắc qua FTP + GUI Tkinter
  đầu tiên.
- Đơn giản hoá truy vấn về "cả ngày", chuyển filter trạm vào history viewer;
  thêm timer tự động truy vấn.
- Thêm chế độ truy vấn nâng cao theo khoảng ngày, rút ô truy vấn thành panel
  trạng thái chỉ đọc; dọn bớt cột CSV viewer.
- Đổi tên dự án thành Solieu26 (`core.py`/`gui.py`), bỏ credential FTP
  hardcode trong mã nguồn.
