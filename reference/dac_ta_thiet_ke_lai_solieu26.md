# Đặc tả thiết kế lại — Solieu26 (Tkinter)

Tài liệu này mô tả các thay đổi so với đặc tả UI gốc, dựa trên 2 mockup đã duyệt: `Redesign Solieu26.dc.html` (bản dựng ý tưởng, chỉ để tham khảo bố cục/nội dung — dùng nhiều hiệu ứng CSS mà Tkinter không làm được) và `Redesign Solieu26 (ban Tkinter thuc te).dc.html` (bản gần khả năng Tkinter thật — **dùng bản này làm chuẩn khi lập trình**, xem mục 8). Chỉ liệt kê phần thay đổi/thêm mới; phần không nhắc tới giữ nguyên như đặc tả gốc.

## 1. Cửa sổ chính

- Ô "Máy chủ" trong panel "Thông tin truy vấn" **giữ nguyên** là Label chỉ-đọc (đã đúng từ đặc tả gốc — chỉ thêm chú thích nhỏ "sửa trong Thiết lập").
- Banner cảnh báo phía trên panel thông tin, chỉ hiện khi đang chạy tác vụ "Tải số liệu theo khoảng": "Tự động: Tạm dừng — đang mở 'Tải số liệu theo khoảng'" (chấm nhấp nháy nhẹ).
- **"Tải số liệu theo khoảng" không còn là dialog Toplevel riêng** — gộp thành 1 khung (LabelFrame) riêng, tên "Tải số liệu theo khoảng", đặt ngay dưới panel "Thông tin truy vấn" trong cửa sổ chính (không lồng vào panel đó, để tránh lẫn với thông tin truy vấn hiện tại). Trong khung: dòng ghi chú nhỏ "● sẽ tạm dừng tự động truy vấn", 2 ô Từ ngày/Đến ngày, 2 nút Về hiện tại/Bắt đầu. Không cần nút mở riêng, không cần cửa sổ con — luôn hiện sẵn.
- Thêm progress bar ngang (0–100%) cạnh text "Tải n/m" ở khu vực tiến trình.
- Log (ScrolledText) giới hạn tối đa ~2000 dòng, tự xoá dòng cũ nhất khi vượt ngưỡng (hiện số dòng hiện tại/giới hạn ở góc dưới phải log).
- Cửa sổ chính cho phép resize (bỏ ràng buộc fixed-size sau khi dựng UI lần đầu); vẫn giữ `minsize` bằng kích thước tự nhiên ban đầu.
- Cột nút dọc bên phải, theo thứ tự: Xem số liệu, **"Dự báo"** (mới), **"Xem chấm điểm"** (mới), Thiết lập... ("Tải số liệu theo khoảng..." đã bỏ khỏi cột nút vì đã gộp inline ở trên).

## 2. Dialog "Thiết lập"

- Khối "Kết nối": 3 ô **Máy chủ / Người dùng / Mật khẩu** xếp **theo chiều dọc** (không còn lưới 2 cột) — bỏ hẳn ô "Cổng" (kết nối FTP, không cần khai cổng riêng).
- Khối "Đường dẫn": ô "Thư mục lưu số liệu" có thêm nút **"Mở thư mục"** ngay cạnh, cùng hàng (mở thư mục đó bằng file explorer của hệ điều hành).
- Bỏ cơ chế "auto-apply khi mất focus/Enter" riêng cho khối Tự động truy vấn. Toàn bộ field (Kết nối, Đường dẫn, Tự động truy vấn) dùng chung 1 nút **"Lưu thiết lập"** duy nhất để ghi vào config.ini và áp dụng.
- Khi có field chưa lưu, hiện chỉ báo nhỏ "● Có thay đổi chưa lưu" trong khối Tự động truy vấn.
- Sau khi bấm "Lưu thiết lập" thành công, hiện toast/banner ngắn "Đã lưu thiết lập lúc HH:MM" (tự ẩn sau vài giây) thay vì lưu im lặng.
- "Khôi phục mặc định" giữ nguyên hành vi hỏi xác nhận yes/no như bản gốc.

## 3. Cửa sổ "Xem số liệu" (HistoryViewer)

- **Không** thêm nút "Dự báo..." vào toolbar Viewer — chức năng này là nút độc lập ở cửa sổ chính (mục 1).
- Nút mở dialog chọn cột hiển thị đổi tên từ "Hiển thị..." thành **"Thiết lập..."** (chỉ đổi nhãn, chức năng không đổi — vẫn là dialog cấu hình cột hiển thị của bảng Viewer, không phải dialog Thiết lập kết nối ở mục 2).
- Ô "Xem số liệu" ở toolbar là 1 **checkbox đơn** (đại diện cho toggle Xem raw/Xem số liệu của đặc tả gốc — giữ nguyên dạng checkbox, không tách thành 2 nút riêng).
- Dropdown Giờ: thêm dòng chú thích nhỏ dưới thanh filter: "Vì đang xem tất cả trạm, phải chọn một giờ cụ thể để tránh bảng quá lớn" (chỉ hiện khi Trạm = "Tất cả các trạm").
- Nhóm cột ẩn: `lat`, `lon`, `station_code` chuyển từ "ẩn cứng" sang "mặc định ẩn nhưng bật lại được" trong dialog "Thiết lập..." (cột). Chỉ còn `date`, `hour`, `source_file`, `cloud_layers` là ẩn cứng tuyệt đối.
- Các hành vi còn lại (sort, zebra striping, dropdown Ngày = file picker...) giữ nguyên.

## 4. Cửa sổ mới: "Dự báo" (nhập bucket dự báo viên)

Dựa theo khuôn mẫu `forecast_bucket_generator.py` tham khảo (RowEditorPanel + Bảng + Xuất CSV), có điều chỉnh:

- **Mở từ đâu**: nút **"Dự báo"** độc lập ở cửa sổ chính (mục 1) — không phụ thuộc Viewer.
- **Tiêu đề cửa sổ**: cố định là "Dự báo".
- **Thanh trên cùng**: 1 ô **Ngày** — dùng để tải/lọc bảng bucket đã lưu của ngày đó (Trạm không chọn ở đây — chọn ngay trong RowEditorPanel, xem dưới).
- **Bảng bucket đã nhập**: toolbar chỉ còn **1 nút "Thêm dòng"**. Treeview 3 cột (Thời gian, Trường dữ liệu, Bucket đã chọn), chọn đơn. **Click chọn 1 dòng sẽ tự nạp dữ liệu dòng đó vào RowEditorPanel bên phải** — không cần double-click hay bấm nút "Sửa" riêng.
- **RowEditorPanel**: có **ô "Trạm" (chọn theo tên)** ở đầu panel — chọn/đổi trạm ngay khi thêm hoặc sửa 1 dòng, độc lập với ô Ngày ở thanh trên cùng. Còn lại: combobox Từ giờ/Đến giờ (00–23), combobox Trường dữ liệu (6 trường), vùng Bucket động theo 4 kiểu (window/linear/circular/phenomenon) rebuild theo trường đang chọn. **Nút trong panel chỉ còn 2: "Lưu dòng" và "Xóa dòng"**.
- **Khung Xuất CSV**: nút **"Xuất CSV..."** và nút **"Nhập CSV..."** đặt cạnh nhau, cùng hàng. "Xuất CSV..." chặn nếu bảng rỗng, ghi archive dải giờ/bucket ra `forecast_YYYYMMDD.csv` qua `export_forecast_table()` — file này là input cho `export_forecast_score()`'s `forecast_csv_path` (mục 5). "Nhập CSV..." đọc lại 1 file `forecast_YYYYMMDD.csv` có sẵn vào bảng bên trên để sửa tiếp.
  - **Quy tắc lưu khi file có nhiều trạm**: `forecast_YYYYMMDD.csv` là 1 file/ngày chứa nhiều trạm, mỗi dòng tự khai `station_code`. Khi lưu dòng (hoặc thêm dòng mới) qua RowEditorPanel, hoặc khi "Xuất CSV...", phải **đọc file cũ trên đĩa trước, giữ nguyên các dòng của trạm khác, chỉ thay/thêm dòng của trạm đang sửa** — tuyệt đối không ghi đè cả file chỉ với dữ liệu của 1 trạm.
- **Phần xem lại nội dung đã xuất**: bảng dạng lưới chỉ-đọc (cột: Giờ + 6 trường, mỗi ô hiển thị nhãn bucket đã tra), thanh cuộn dọc, cao ~150px.

## 5. Cửa sổ mới: "Xem điểm chấm dự báo"

Cửa sổ singleton, đọc file `score_YYYYMMDD.csv` (chỉ đọc, không tự chạy `export_forecast_score()`), theo khuôn mẫu HistoryViewer:

- **Toolbar** (thứ tự trái→phải, các ô sát nhau): dropdown **Trạm** (mới — "Tất cả các trạm" + từng trạm, vì `join_forecast_obs()` ghép đa trạm đã xong, `station_code` là trạm thật), dropdown **Ngày** (file picker qua `score_YYYYMMDD.csv`, regex riêng `FORECAST_CSV_RE` — không khớp `forecast_YYYYMMDD.csv`), dropdown **Trường** (1 trong 6 trường, hoặc "Tất cả 6 trường"), rồi nút **"Thiết lập..."** (dialog chọn cột, nhóm checkbox theo field) ở cuối cùng bên phải. Đã bỏ nút "Làm mới" và "Mở bằng Excel".
- **Thanh tóm tắt** (phía trên bảng): tỷ lệ đạt theo đúng filter đang bật (trường + buổi/giờ + trạm), loại các dòng "bỏ cặp" (score rỗng) khỏi mẫu số. Ví dụ: "Đạt 18/22 (81,8%) — bỏ cặp 2, trường tong_luong_may, buổi sáng, trạm 48-097". Tính lại mỗi khi đổi filter.
- **Bảng**:
  - Cột cố định: Giờ, Buổi.
  - Chế độ "1 trường": thêm 3 cột DB / QT / Điểm cho trường đang chọn. Tô màu **cả dòng** theo `score_<field>`: xanh nhạt = True (Đạt), đỏ nhạt = False (Không đạt), xám nhạt = rỗng (bỏ cặp).
  - Chế độ "Tất cả 6 trường": nhóm 3 cột/trường liền nhau, header dùng tiền tố kiểu `"tong_luong_may (DB)"`. Tô màu cả dòng: có ≥1 `score_*` = False → đỏ nhạt cả dòng; toàn True/rỗng → xanh nhạt.
  - Click header để sort; `hour` sort dạng số.
- **Trạng thái rỗng**: nếu chưa có `score_*.csv` nào trên đĩa, bảng hiển thị rỗng kèm thông báo "Chưa có dữ liệu chấm điểm" — nút toolbar vẫn bấm được, không lỗi im lặng.

## 6. Quyết định kiến trúc đã chốt (để Claude Code không phải đoán lại)

- Không còn dialog Toplevel riêng cho "Tải số liệu theo khoảng" — nay là 1 khung (LabelFrame) luôn hiện trong cửa sổ chính, cạnh panel "Thông tin truy vấn" nhưng tách khung riêng có tên rõ ràng để không lẫn với thông tin truy vấn hiện tại. Việc "tạm dừng auto-query" giờ gắn với lúc tác vụ tải đang chạy (không phải lúc dialog mở, vì không còn dialog).
- 3 cửa sổ view/input còn lại (Xem số liệu, Dự báo, Xem chấm điểm) **không gộp chung** thành 1 cửa sổ/1 bộ filter — cấu trúc dữ liệu, bộ lọc và quy tắc hiển thị của mỗi loại khác nhau đủ nhiều để việc gộp làm phức tạp hơn thay vì đơn giản hơn.
- Cả 3 cửa sổ trên đều là entry point **độc lập, ngang hàng** ở cửa sổ chính — không cửa sổ nào phụ thuộc ngữ cảnh của cửa sổ khác để mở. Cửa sổ Dự báo tự có ô chọn Ngày ở trên cùng và ô chọn Trạm ngay trong RowEditorPanel.
- Khi lưu/thêm dòng trong cửa sổ Dự báo, phải đọc file `forecast_YYYYMMDD.csv` cũ, giữ nguyên dòng của các trạm khác, chỉ thay/thêm dòng đang sửa (mục 4).
- Cả 2 viewer mới (Dự báo, Xem điểm chấm) đều chỉ đọc/ghi file trên đĩa qua các hàm logic đã có sẵn (`export_forecast_table()`, `export_forecast_score()`, v.v.) — không tự động gọi pipeline ngầm, giữ đúng nguyên tắc "viewer không chạy pipeline" của HistoryViewer gốc.

## 7. Ghi chú về mockup và khả năng hiển thị thật của Tkinter

- File `Redesign Solieu26.dc.html` là bản dựng ý tưởng bằng CSS (font Barlow Condensed, dấu góc, đổ bóng, hover mượt...) — các chi tiết này **Tkinter/ttk không tái tạo được** hoặc phải tự vẽ Canvas tốn công, không đáng cho app nội bộ. Chỉ dùng để tham khảo bố cục/nội dung ban đầu, không phải chuẩn cuối.
- File `Redesign Solieu26 (ban Tkinter thuc te).dc.html` là bản đã rút gọn về đúng khả năng ttk thật: font hệ thống (Segoe UI/Tahoma), khung nhóm dạng LabelFrame viền groove, bảng phẳng kiểu Treeview, không dấu góc/đổ bóng — **dùng bản này làm chuẩn tham chiếu khi lập trình**. Đây cũng là bản phản ánh đúng nhất các quyết định mới nhất ở mục 1–6 (khung "Tải số liệu theo khoảng" gộp vào cửa sổ chính, toolbar Dự báo/Xem chấm điểm đã sắp lại, v.v.) — nếu có mâu thuẫn giữa mô tả text và mockup, **ưu tiên theo mockup**.
