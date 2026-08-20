# Đặc tả thiết kế lại — Solieu26 (Tkinter)

Tài liệu này mô tả các thay đổi so với đặc tả UI gốc, dựa trên mockup đã duyệt (`Redesign Solieu26.dc.html`). Chỉ liệt kê phần thay đổi/thêm mới; phần không nhắc tới giữ nguyên như đặc tả gốc.

## 1. Cửa sổ chính

- Ô "Máy chủ" trong panel "Thông tin truy vấn" đổi từ Entry sửa được thành Label chỉ-đọc như các dòng khác (kèm chú thích nhỏ "sửa trong Thiết lập"). Sửa host chỉ còn thực hiện được trong dialog Thiết lập.
- Thêm banner cảnh báo phía trên panel thông tin, chỉ hiện khi dialog "Tải số liệu" đang mở: "Tự động: Tạm dừng — đang mở 'Tải số liệu theo khoảng'" (chấm màu cam nhấp nháy nhẹ). Đây là hiển thị tường minh cho side-effect tạm dừng auto-query vốn đang ẩn.
- Thêm progress bar ngang (0–100%) cạnh text "Tải n/m" ở khu vực tiến trình, để phản hồi trực quan khi FTP chậm.
- Log (ScrolledText) giới hạn tối đa ~2000 dòng, tự xoá dòng cũ nhất khi vượt ngưỡng (hiện số dòng hiện tại/giới hạn ở góc dưới phải log).
- Cửa sổ chính cho phép resize (bỏ ràng buộc fixed-size sau khi dựng UI lần đầu); vẫn giữ `minsize` bằng kích thước tự nhiên ban đầu.
- Cột nút dọc bên phải thêm 1 nút mới: **"Xem chấm điểm"**, chèn giữa "Xem số liệu" và "Thiết lập...". Mở cửa sổ singleton mới (xem mục 6).

## 2. Dialog "Thiết lập"

- Bỏ cơ chế "auto-apply khi mất focus/Enter" riêng cho khối Tự động truy vấn. Toàn bộ field (Kết nối, Đường dẫn, Tự động truy vấn) dùng chung 1 nút **"Lưu thiết lập"** duy nhất để ghi vào config.ini và áp dụng.
- Khi có field chưa lưu, hiện chỉ báo nhỏ "● Có thay đổi chưa lưu" trong khối Tự động truy vấn (hoặc vị trí chung phù hợp).
- Sau khi bấm "Lưu thiết lập" thành công, hiện toast/banner ngắn "Đã lưu thiết lập lúc HH:MM" (tự ẩn sau vài giây) thay vì lưu im lặng.
- "Khôi phục mặc định" giữ nguyên hành vi hỏi xác nhận yes/no như bản gốc.

## 3. Dialog "Tải số liệu" (nâng cao)

- Thêm banner cảnh báo ngay khi mở dialog: "Mở dialog này sẽ tạm dừng tự động truy vấn cho tới khi đóng lại" — hiện trước khi người dùng thao tác tiếp, để hành vi tạm dừng auto-query không còn là side-effect ẩn.
- Hành vi còn lại (2 ô ngày, nút Bắt đầu/Về hiện tại, khoá nút khi có tác vụ khác chạy, tự đóng khi bắt đầu thành công) giữ nguyên như đặc tả gốc.

## 4. Cửa sổ "Xem số liệu" (HistoryViewer)

- Toolbar thêm 1 nút mới: **"Dự báo cho trạm/ngày này..."**, đặt cạnh nút "Hiển thị". Mở cửa sổ nhập bucket dự báo (mục 5), truyền sẵn trạm + ngày đang xem trong Viewer làm ngữ cảnh cố định.
- Dropdown Giờ: thêm dòng chú thích nhỏ ngay dưới thanh filter giải thích quy tắc khoá hiện có: "Vì đang xem tất cả trạm, phải chọn một giờ cụ thể để tránh bảng quá lớn" (chỉ hiện khi Trạm = "Tất cả các trạm").
- Nhóm cột ẩn: `lat`, `lon`, `station_code` chuyển từ "ẩn cứng" sang "mặc định ẩn nhưng bật lại được" trong dialog "Hiển thị". Chỉ còn `date`, `hour`, `source_file`, `cloud_layers` là ẩn cứng tuyệt đối (không xuất hiện trong dialog chọn cột).
- Các hành vi còn lại (toggle Xem raw/Xem số liệu, sort, zebra striping, dropdown Ngày = file picker...) giữ nguyên.

## 5. Cửa sổ mới: "Dự báo — trạm {station}, {ngày}" (nhập bucket dự báo viên)

Dựa theo khuôn mẫu `forecast_bucket_generator.py` tham khảo (RowEditorPanel + Bảng + Xuất CSV), có điều chỉnh:

- **Mở từ đâu**: chỉ mở được từ nút "Dự báo cho trạm/ngày này..." trong Viewer (mục 4) — không có entry point độc lập ở main window.
- **Tiêu đề cửa sổ**: hiển thị cố định `Dự báo — trạm {station}, {ngày}` lấy từ ngữ cảnh Viewer tại thời điểm mở. Không có ô chọn lại trạm/ngày trong cửa sổ này (vá lỗ hổng "ngầm định, không ô chọn" của bản tham khảo gốc).
- **Bố cục**: giữ nguyên 2 cột như spec gốc — trái: khung Bảng (trên) + khung Xuất CSV (dưới); phải: RowEditorPanel cố định (không phải dialog).
- **Khắc Bảng**: toolbar "Sửa dòng / Xóa dòng" (không còn "+ Thêm dòng" và "Nhập CSV..."), Treeview 3 cột (Thời gian, Trường dữ liệu, Bucket đã chọn), chọn đơn, double-click để sửa, iid = index thẳng trong data_base.
- **RowEditorPanel**: label chế độ (Thêm/Sửa), combobox Từ giờ/Đến giờ (00–23), combobox Trường dữ liệu (6 trường), vùng Bucket động theo 4 kiểu (window/linear/circular/phenomenon) rebuild theo trường đang chọn, nút Lưu dòng/Dòng mới — giữ nguyên như spec gốc.
- **Khung Xuất CSV**: nút "Xuất CSV..." (chặn nếu bảng rỗng, không còn nút "Chép tất cả"), label tóm tắt số dòng + khoảng giờ đã xuất. Nút này ghi archive dải giờ/bucket dự báo viên vừa nhập ra `forecast_YYYYMMDD.csv` qua `export_forecast_table()` (chưa ghép obs/chấm điểm) — đây chính là file mà `export_forecast_score()`'s tham số `forecast_csv_path` (mục 6) sẽ trỏ vào sau này.
- **Thay đổi so với bản tham khảo gốc**: phần xem lại nội dung đã xuất đổi từ Text monospace (dạng log/CSV thô) thành **bảng dạng lưới chỉ-đọc** (cột: Giờ + 6 trường, mỗi ô hiển thị nhãn bucket đã tra, không phải giá trị CSV thô), có thanh cuộn dọc, cao ~150px. Mục đích: dễ đọc/soát lại hơn cho dự báo viên so với việc đọc trực tiếp nội dung file CSV.

## 6. Cửa sổ mới: "Xem điểm chấm dự báo"

Cửa sổ singleton, đọc file `score_YYYYMMDD.csv` (chỉ đọc, không tự chạy `export_forecast_score()`), theo khuôn mẫu HistoryViewer:

- **Toolbar**: "Làm mới", "Mở bằng Excel", "Hiển thị..." (giữ như HistoryViewer, nhưng nhóm checkbox theo field thay vì liệt kê phẳng 18 dòng); dropdown **Ngày** (file picker qua `score_YYYYMMDD.csv`, cần regex riêng `FORECAST_CSV_RE` — khớp `score_YYYYMMDD.csv`, không khớp `forecast_YYYYMMDD.csv` (archive dự báo thô ở mục 5, chưa chấm điểm)); dropdown **Trường** (1 trong 6 trường, hoặc "Tất cả 6 trường").
- **Trạm**: không có dropdown lọc trạm — ẩn hẳn cho tới khi việc ghép đa trạm thật hoàn tất (hiện `station` chỉ là 1 trạm đại diện/giờ, lọc theo trạm chưa có ý nghĩa thật). Hiện dòng ghi chú nhỏ giải thích lý do ẩn.
- **Thanh tóm tắt** (mới, phía trên bảng): tỷ lệ đạt theo đúng filter đang bật (trường + buổi/giờ), loại các dòng "bỏ cặp" (score rỗng) khỏi mẫu số. Ví dụ: "Đạt 18/22 (81,8%) — bỏ cặp 2, trường tong_luong_may, buổi sáng". Tính lại mỗi khi đổi filter.
- **Bảng**:
  - Cột cố định: Giờ, Buổi.
  - Chế độ "1 trường": thêm 3 cột DB / QT / Điểm cho trường đang chọn. Tô màu **cả dòng** theo `score_<field>` của đúng trường đó: xanh nhạt = True (Đạt), đỏ nhạt = False (Không đạt), xám nhạt = rỗng (bỏ cặp).
  - Chế độ "Tất cả 6 trường": nhóm 3 cột/trường liền nhau, header dùng tiền tố tên cột kiểu `"tong_luong_may (DB)"` (Treeview không hỗ trợ header 2 tầng). Tô màu cả dòng theo quy tắc riêng cho chế độ này: có ≥1 `score_*` = False → tô đỏ nhạt cả dòng; toàn True/rỗng → tô xanh nhạt.
  - Click header để sort (giữ như HistoryViewer); `hour` sort dạng số.
- **Trạng thái rỗng**: nếu chưa có `score_*.csv` nào trên đĩa (pipeline scoring chưa nối vào `runner.py`), bảng hiển thị rỗng kèm thông báo rõ ràng "Chưa có dữ liệu chấm điểm" — nút toolbar vẫn bấm được, không lỗi im lặng.

## 7. Quyết định kiến trúc đã chốt (để Claude Code không phải đoán lại)

- 3 cửa sổ view/input (Xem số liệu, Dự báo cho trạm/ngày này, Xem chấm điểm) **không gộp chung** thành 1 cửa sổ/1 bộ filter — cấu trúc dữ liệu, bộ lọc và quy tắc hiển thị của mỗi loại khác nhau đủ nhiều để việc gộp làm phức tạp hơn thay vì đơn giản hơn.
- Cửa sổ "Xem chấm điểm" là view độc lập cấp cao (ngang hàng Xem số liệu ở main window) vì chỉ đọc, không cần ngữ cảnh từ nơi khác.
- Cửa sổ "Dự báo cho trạm/ngày này" là input tool phụ thuộc ngữ cảnh, nên chỉ mở được từ trong Viewer, không có entry point riêng ở main window.
- Cả 2 viewer mới (bucket input, scoring) đều chỉ đọc/ghi file trên đĩa qua các hàm logic đã có sẵn (`export_forecast_score()`, v.v.) — không tự động gọi pipeline ngầm, giữ đúng nguyên tắc "viewer không chạy pipeline" của HistoryViewer gốc.
