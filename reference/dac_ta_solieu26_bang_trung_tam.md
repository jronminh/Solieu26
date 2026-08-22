# Đặc tả thiết kế lại — Solieu26 (Tkinter) — bản "bảng số liệu làm trung tâm"

Bản này **thay thế hoàn toàn** hướng thiết kế cũ (nhiều Toplevel độc lập, mô tả trong `dac_ta_thiet_ke_lai_solieu26.md`). Mockup chuẩn: `Redesign Solieu26 (bang trung tam).dc.html`. Kiến trúc: **1 cửa sổ chính duy nhất**, dùng `ttk.Notebook` (tab) bên trong để chuyển giữa các chức năng — không còn Toplevel/dialog rời cho các màn hình chính (trừ các hộp thoại phụ trợ nhỏ như "Cột hiển thị...", xác nhận "Khôi phục mặc định").

## 1. Kiến trúc tổng thể

- 1 `Tk()` root, `ttk.Notebook` với 6 tab theo đúng thứ tự: **Số liệu · Dự báo · Xem chấm điểm · Tải số liệu theo khoảng · Log · Thiết lập**.
- Không có nút mở cửa sổ con nào nữa — mọi chức năng là 1 tab. Chuyển tab bằng click vào tab, không cần nút "Đóng" quay lại.
- Toàn bộ tab chia sẻ cùng 1 vùng dữ liệu ứng dụng (config, station list, dữ liệu đang tải...) — không có state riêng theo cửa sổ như bản Toplevel cũ.

## 2. Tab "Số liệu" (bảng làm trung tâm — mặc định khi mở app)

- Khung "Hiển thị bảng": dropdown **Trạm** (Tất cả các trạm / từng trạm), dropdown **Ngày** (file picker), dropdown **Giờ** (07:00/08:00/.../Tất cả), checkbox **"Xem số liệu"** (toggle raw/số liệu đã xử lý), nút **"Thiết lập..."** mở dialog phụ chọn cột hiển thị (không phải tab Thiết lập ở mục 7).
  - Khi Trạm = "Tất cả các trạm": hiện chú thích nhỏ "Vì đang xem tất cả trạm, phải chọn một giờ cụ thể để tránh bảng quá lớn".
- Khung "Số liệu": bảng chính (Treeview), cột Giờ/Trạm/6 trường quan trắc, zebra striping, sort theo cột (click header).
- Thanh tiến trình tải (label "Tải n/m" + progress bar + %) nằm cuối tab, phản ánh tiến trình tải nền đang chạy (nếu có) — không phụ thuộc việc đang xem tab nào.

## 3. Tab "Dự báo" (nhập bucket dự báo viên)

- Thanh trên cùng: dropdown **Ngày** — tải/lọc bảng bucket đã lưu của ngày đó.
- Khung "Bảng bucket đã nhập": Treeview 3 cột (Thời gian, Trường dữ liệu, Bucket đã chọn), chọn đơn, **không có nút toolbar riêng** (đã bỏ "Thêm dòng" — thêm dòng làm qua RowEditorPanel). Click 1 dòng tự nạp vào RowEditorPanel bên phải.
- RowEditorPanel: dropdown **Trạm** (theo tên, để chọn/đổi trạm khi thêm/sửa 1 dòng), combobox Từ giờ/Đến giờ (00–23), combobox Trường dữ liệu (6 trường), vùng Bucket động theo 4 kiểu (window/linear/circular/phenomenon) rebuild theo trường đang chọn. Chỉ 2 nút: **"Lưu dòng"** và **"Xóa dòng"**.
- Khung "Xuất CSV": bảng lưới chỉ-đọc xem lại nội dung đã xuất (Giờ + 6 trường), cao ~150px, có thanh cuộn. 2 nút cạnh nhau: **"Xuất CSV..."** (ghi `forecast_YYYYMMDD.csv` qua `export_forecast_table()`) và **"Nhập CSV..."** (đọc lại 1 file có sẵn vào bảng).
- **Quy tắc lưu file nhiều trạm**: `forecast_YYYYMMDD.csv` là 1 file/ngày chứa nhiều trạm (mỗi dòng tự khai `station_code`). Khi lưu/thêm dòng hoặc xuất CSV, phải đọc file cũ trên đĩa, giữ nguyên dòng của trạm khác, chỉ thay/thêm dòng của trạm đang sửa.

## 4. Tab "Xem chấm điểm"

- Thanh trên cùng: dropdown **Trạm** ("Tất cả các trạm" + từng trạm), dropdown **Ngày** (file picker `score_YYYYMMDD.csv`, regex riêng không khớp `forecast_YYYYMMDD.csv`), dropdown **Trường** (1/6 trường hoặc "Tất cả 6 trường"), nút **"Thiết lập..."** (dialog chọn cột) ở cuối hàng bên phải.
- Thanh tóm tắt: tỷ lệ đạt theo filter đang bật, loại dòng "bỏ cặp" (score rỗng) khỏi mẫu số. Ví dụ: "Đạt 18/22 (81,8%) — bỏ cặp 2, trường tong_luong_may, buổi sáng, trạm 48-097".
- Bảng: cột Giờ/Buổi cố định; chế độ 1 trường thêm 3 cột DB/QT/Điểm; chế độ "Tất cả 6 trường" nhóm 3 cột/trường. Tô màu **cả dòng**: xanh nhạt = Đạt, đỏ nhạt = Không đạt, xám = bỏ cặp. Click header để sort.
- Trạng thái rỗng: chưa có `score_*.csv` → bảng rỗng + thông báo "Chưa có dữ liệu chấm điểm", toolbar vẫn bấm được.
- Chỉ đọc file trên đĩa, không tự chạy `export_forecast_score()`.

## 5. Tab "Tải số liệu theo khoảng"

- Banner: "Tác vụ này sẽ tạm dừng tự động truy vấn cho tới khi hoàn tất hoặc hủy" (chỉ hiện khi tác vụ đang chạy).
- Khung "Khoảng thời gian": Từ ngày/Đến ngày/Từ giờ/Đến giờ + 3 nút rút gọn "7 ngày trước" / "30 ngày trước" / "Về hiện tại".
- Khung "Hàng đợi (N file dự kiến)": bảng chỉ-đọc liệt kê từng file cần tải (Trạm/Ngày/Giờ/Trạng thái: Đã tải, Đang tải…, Timeout+retry, Chờ), cao ~150px, cuộn dọc.
- Thanh tiến trình + 2 nút cuối: **"Hủy"** / **"Bắt đầu"**.
- **Không** chứa cấu hình kết nối FTP hay tùy chọn tải nâng cao — các mục đó đã dời sang tab "Thiết lập" (mục 7) vì là thiết lập một lần, không phải hành động mỗi lần tải.

## 6. Tab "Log"

- Khung Log full-width: label "n/2000 dòng" (giới hạn dòng, tự xoá dòng cũ nhất khi vượt ngưỡng), vùng log monospace cao ~420px, cuộn dọc.

## 7. Tab "Thiết lập"

- Khung "Kết nối FTP": Máy chủ, Người dùng, Mật khẩu, **Đường dẫn trên máy chủ** (mặc định `/Quantrac`) — xếp dọc, không có nút chọn (đường dẫn máy chủ là chuỗi gõ tay, không phải file picker).
- Khung "Đường dẫn": **Thư mục lưu số liệu** (trên máy local) + nút **"Chọn..."** (mở file picker hệ điều hành để chọn thư mục).
- Khung "Tùy chọn tải" (chỉ báo "· ● Có thay đổi chưa lưu" khi có field chưa lưu):
  - Hàng 1: **Tự truy vấn (phút)**, **Số luồng song song**, **Timeout (giây)**, **Số lần retry**.
  - Hàng 2 (checkbox): **Bật tự động truy vấn**, **Ghi đè file đã có**, **Chỉ tải file còn thiếu**.
- Toast "Đã lưu thiết lập lúc HH:MM" hiện sau khi bấm **"Lưu thiết lập"** (tự ẩn sau vài giây).
- **"Khôi phục mặc định"**: hỏi xác nhận yes/no trước khi áp lại mặc định.
- Toàn bộ field trong tab dùng chung 1 nút **"Lưu thiết lập"** để ghi vào config.ini — không có cơ chế auto-apply khi mất focus/Enter.

## 8. Quyết định kiến trúc đã chốt

- Đây là hướng thiết kế **được chọn thay cho** bản nhiều-Toplevel trước đó — không triển khai song song 2 hướng.
- Kết nối FTP + tùy chọn tải nâng cao chỉ nằm ở tab Thiết lập, tab "Tải số liệu theo khoảng" chỉ giữ phần hành động (khoảng thời gian, hàng đợi, tiến trình, Bắt đầu/Hủy) để tránh lộn xộn UX (gộp thiết lập một-lần với hành động mỗi-lần).
- Cửa sổ Dự báo không phụ thuộc ngữ cảnh tab Số liệu — có ô chọn Ngày riêng ở đầu tab và ô chọn Trạm riêng trong RowEditorPanel.
- Khi lưu/thêm dòng trong tab Dự báo, phải đọc file `forecast_YYYYMMDD.csv` cũ, giữ nguyên dòng của các trạm khác, chỉ thay/thêm dòng đang sửa.
- Tab Dự báo và Xem chấm điểm chỉ đọc/ghi file trên đĩa qua các hàm logic đã có sẵn (`export_forecast_table()`, `export_forecast_score()`, v.v.) — không tự động gọi pipeline ngầm.

## 9. Ghi chú về khả năng hiển thị thật của Tkinter

Mockup dùng font hệ thống (Segoe UI/Tahoma), khung nhóm dạng `ttk.LabelFrame` (viền + label nổi trên viền), bảng phẳng kiểu `ttk.Treeview`, tab dạng `ttk.Notebook` — không dấu góc, không đổ bóng, không hiệu ứng CSS. Đây là chuẩn tham chiếu khi lập trình; nếu mockup và mô tả text mâu thuẫn, ưu tiên theo mockup.
