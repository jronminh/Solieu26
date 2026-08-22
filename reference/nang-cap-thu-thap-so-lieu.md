# Nâng cấp khối thu thập số liệu — định hướng phát triển

Tài liệu này mô tả các tính năng cần thêm cho khối thu thập số liệu (tải FTP →
decode CSV). Đọc kỹ phần **Bối cảnh** và **Giả định chưa xác nhận** trước khi
đụng vào code, vì phần lớn thiết kế dưới đây dựa trên đặc điểm của nguồn dữ liệu
chứ không phải chỉ dựa trên giao thức.

---

## Bối cảnh

Công cụ desktop tải số liệu quan trắc từ máy chủ Quan trắc qua FTP (IIS/Windows),
decode ra CSV. Kiến trúc hai khối tách biệt:

- **Khối 1 — fetch FTP:** kết nối, liệt kê, tải file về local.
- **Khối 2 — decode → CSV:** không phụ thuộc Khối 1; lỗi decode không ảnh hưởng
  kết quả tải đã xong.

Đã có sẵn (xem phần "Đã có — đừng làm lại"): hai chế độ tải (định kỳ + khoảng
ngày), ghi file nguyên tử `.part` + `os.replace`, retry tách `error_temp` /
`error_perm`, chống chồng lấn định kỳ vs khoảng ngày, chạy nền thread + queue,
UI poll 100ms.

**Đặc điểm nguồn dữ liệu — điểm mấu chốt của cả tài liệu:** file số liệu do
**người nhập qua công cụ tool-assist**, không phải máy tự sinh. Hệ quả:

- File của một giờ **đã qua** có thể bị nhập lại / đính chính / bổ sung trễ.
  Đây là chuyện bình thường với dữ liệu người nhập, không phải ngoại lệ.
- File xuất hiện theo nhịp người nhập, **có thể trễ** so với giờ quan trắc.
- "Đã có file local" **không** đồng nghĩa "đã có bản mới nhất".

---

## Nguyên tắc bao trùm

Mọi tính năng dưới đây phục vụ đúng hai mục tiêu:

- **Toàn vẹn** — file lấy về không cụt, không dở.
- **Cập nhật** — bản local luôn khớp bản mới nhất trên server.

Hai mục tiêu này **đối chọi nhau ở nhịp poll**: poll dày thì cập nhật kịp nhưng
dễ vồ đúng lúc người ta đang nhập dở (hại toàn vẹn); chờ file đứng yên thì toàn
vẹn chắc nhưng chậm cập nhật. Điểm dung hòa là **poll-size-hai-lần** (mục 4):
cho phép poll dày mà chỉ chốt khi file đã đứng yên.

---

## Giả định chưa xác nhận

Chưa xác định được **máy chủ có ghi đè / đính chính lại file của một giờ đã qua
hay không**, và **cơ chế ghi file phía server là ghi tại chỗ hay ghi tạm rồi
rename**.

Các tính năng dưới được thiết kế theo hướng **đề phòng** — phòng thủ được mà
không cần biết chắc cơ chế server. Đây là lựa chọn có chủ đích: rẻ hơn đi điều
tra máy chủ.

Nếu về sau xác nhận được server **rename nguyên tử và không bao giờ sửa file
cũ**, thì có thể lược bớt: `SIZE`-check (mục 2) và poll-size-hai-lần (mục 4) trở
nên thừa. Index mtime (mục 3) vẫn cần nếu file cũ có khả năng bị nhập lại.

---

## Đã có — đừng làm lại

Không viết lại, không thay thế những phần sau (chỉ mở rộng nếu tính năng mới yêu
cầu):

- Hai chế độ tải: định kỳ (auto query mỗi N phút/giờ) và theo khoảng ngày.
- Ghi file nguyên tử: `.part` + `os.replace` — đã chặn được file dở phía client.
- Retry tách `error_temp` (thử lại) / `error_perm` (bỏ qua, đưa vào danh sách
  thiếu).
- Chống chồng lấn: auto query bỏ qua nếu đang chạy, tạm dừng khi có tải khoảng
  ngày.
- Chạy nền thread + queue, UI poll 100ms.
- Hàng đợi liệt kê trước + cập nhật trạng thái từng dòng realtime.

---

## Cần thêm (theo thứ tự ưu tiên công-ít-lợi-nhiều)

### 1. Mốc catch-up sau downtime — ưu tiên cao nhất

**Mục đích:** vá lỗ "tool nghỉ một khoảng rồi bật lại thì khoảng hụt không ai
tải". Auto query hiện chỉ chạy pipeline "hiện tại".

**Cách làm:** lưu một mốc "đã tải liền mạch tới giờ nào" (một timestamp duy nhất,
không cần index đầy đủ). Khi khởi động / khi auto query chạy lại, so mốc đó với
hiện tại; nếu hụt thì tự bù khoảng thiếu trước khi tiếp tục nhịp bình thường.

**Tích hợp:** cập nhật mốc sau mỗi chu kỳ tải thành công liền mạch. Việc bù dùng
lại đúng pipeline khoảng ngày đã có.

**Vì sao ưu tiên:** ít công nhất (chỉ một timestamp), giá trị cao.

### 2. `SIZE`-check khi chốt file — ưu tiên cao

**Mục đích:** `.part` + `os.replace` chỉ chặn đứt phía client, **không** chặn
file cụt phía server (vồ đúng lúc máy Quan trắc ghi dở → `replace` ra file "đủ
tên nhưng thiếu ruột" → lần sau skip vĩnh viễn vì đã tồn tại).

**Cách làm:** sau khi tải xong vào file tạm, gọi `SIZE` trên server đối chiếu với
size file local; **khớp mới** đổi sang tên thật. Không khớp thì coi như lỗi tạm,
đưa vào retry.

**Cạm bẫy:** `SIZE`-check **không** bắt được trường hợp người nhập lưu file
thiếu nội dung (file hoàn chỉnh về kỹ thuật, chỉ thiếu dòng). Cái đó là việc của
Khối 2 (xem phần cuối).

### 3. Index mtime (size phụ) — ưu tiên vừa, nhưng đáng giá nhất với dữ liệu người nhập

**Mục đích:** bắt **bản nhập lại / đính chính**. Hiện skip theo sự tồn tại file
local nên tool ôm mãi bản đầu tiên, kể cả khi nó là bản nhập vội sai.

**Cách làm:** duy trì một bảng trạng thái local ghi `mtime` (và `size`) của từng
file đã tải. Khi liệt kê, dùng `MLSD` lấy mtime/size chuẩn máy đọc từ server, so
với index; chỉ tải lại nếu mtime server mới hơn (hoặc size khác).

**Vì sao mtime là trục chính, size chỉ phụ:** với người nhập, sửa một con số
thường **không đổi độ dài file** (ví dụ `23` → `25`, size y hệt) — so size sẽ
trượt đúng cái cần bắt. So mtime bắt được vì ghi lại là mtime mới. Muốn chắc
tuyệt đối thì hash nội dung, nhưng với file nhỏ thế này mtime là đủ và rẻ.

**Lưu ý:** index này là nền tảng — mốc catch-up (mục 1) có thể coi là bản rút
gọn của nó. Nếu làm index đầy đủ thì mục 1 gần như miễn phí đi kèm.

### 4. Poll-size-hai-lần (chống vồ file đang ghi/đang nhập)

**Mục đích:** khi poll dày để cập nhật kịp, tránh vồ đúng file đang được nhập/ghi
dở. Cũng là cách xử lý cái "không biết cơ chế ghi server" mà không cần đi điều
tra.

**Cách làm:** trước khi tải một file, `SIZE` hai lần cách nhau một khoảng ngắn;
size đứng yên mới coi là ổn định để tải. Đây cũng chính là điểm dung hòa giữa
toàn vẹn và cập nhật (xem Nguyên tắc bao trùm).

**Cân nhắc bỏ:** nếu xác nhận server ghi tạm rồi rename (file chỉ xuất hiện khi
đã hoàn chỉnh) thì mục này thừa.

### 5. Tải song song giữa nhiều file

**Mục đích:** phục vụ tính năng sắp tới cần tải **lượng file lớn**. Hiện duyệt
tuần tự từng giờ. Song song **giữa các file**, không chẻ mảnh một file.

**Mô hình:** chuyển từ một thread tuần tự sang **pool N worker rút việc từ hàng
đợi file**. Producer vẫn là bước liệt kê hiện tại (quét ra toàn bộ file dự kiến,
đẩy vào `queue.Queue`). N worker cùng rút task, tải độc lập, báo kết quả về một
result queue chung. UI vẫn poll như cũ, chỉ gom event từ nhiều nguồn.

**Điểm kỹ thuật FTP — sai là hỏng:**

- **Mỗi worker một kết nối FTP riêng.** `ftplib.FTP` không thread-safe; tuyệt đối
  không share một object qua nhiều thread. N worker = N lần login độc lập. Điều
  kiện tiên quyết.
- **Giữ kết nối sống trong worker, đừng login lại mỗi file.** Với file nhỏ, chi
  phí login (và handshake TLS nếu FTPS) dễ ăn hết lợi ích song song. Worker login
  một lần, tải liên tiếp nhiều file trên cùng connection, chỉ đóng khi hết việc
  hoặc connection chết.
- **IIS FTP có trần kết nối đồng thời** (per user / per IP). Vượt trần ăn mã
  `421`. Để N nhỏ và cấu hình được (mặc định 3–4); bắt riêng lỗi `421` để backoff
  hoặc tự giảm N, đừng coi như lỗi tải thường.
- **Tối ưu `cwd` cũ mất tác dụng.** Hiện chỉ `cwd` lại khi năm/tháng đổi — chỉ
  đúng khi duyệt tuần tự theo thời gian. Song song thì worker bốc file lung tung,
  `cwd` loạn. Xử lý: (a) chia việc theo cụm thư mục (năm/tháng), giao trọn một
  cụm cho một worker → `cwd` một lần rồi tải cả cụm; hoặc (b) dùng đường dẫn tuyệt
  đối trong `RETR`, bỏ `cwd`. Nghiêng (a) vì vừa giảm `cwd` vừa gom I/O theo thư
  mục.

**Tích hợp với phần đã có:**

- **Toàn vẹn giữ per-worker:** mỗi worker vẫn `.part` + `os.replace` +
  `SIZE`-check của riêng nó. Tên file tạm phải gắn theo file đích (hoặc worker
  id), không dùng chung một tên `.part` kẻo hai worker giẫm lên nhau.
- **Retry theo từng task:** giữ `retry_temp` / `retry_wait`. Một task lỗi tạm
  thời tự retry / trả lại queue, không chặn cả pool.
- **UI và tiến trình:** thanh tổng `n/m` vẫn đúng, đếm hoàn thành qua biến có
  lock. Trạng thái từng dòng cập nhật theo task id, không dựa thứ tự — vì thứ tự
  hoàn thành sẽ loạn so với thứ tự liệt kê. Tách rõ "thứ tự hiển thị" (cố định
  lúc liệt kê) khỏi "thứ tự xong" (loạn).
- **Dừng giữa chừng:** một cờ dừng chung, worker kiểm cờ giữa các task, đóng
  connection gọn rồi thoát. Cancel phải sạch, không để connection treo.
- **Chống chồng lấn không đổi:** đợt song song vẫn tạm dừng auto query như cơ chế
  hiện tại.

**Tham số & hành vi:**

- `parallel_workers` (N), mặc định 3–4, cho chỉnh.
- Ngưỡng bật: dưới ngưỡng số file thì chạy tuần tự, từ ngưỡng trở lên mới bật
  pool — hoặc để N do người dùng đặt.
- **N=1 phải chạy đúng y đường tuần tự cũ.** Chốt chặn không hồi quy: giữ nhánh
  cũ nguyên vẹn làm trường hợp N=1, để bật/tắt song song không đụng cái đang chạy
  tốt.

**Cạm bẫy:** lợi ích song song bão hòa nhanh. Qua một mức, nghẽn chuyển sang ổ
đĩa/băng thông chứ không còn ở số luồng, mà connection thừa lại tăng rủi ro chạm
trần IIS. Đừng đặt N cao vì "cho chắc" — 3–4 thường là điểm ngọt cho loại file
này; muốn hơn thì đo rồi hẵng tăng.

---

## Việc của tầng decode (Khối 2), không phải của FTP

Một loại lỗi mà **không cơ chế FTP nào bắt được**: file đủ tên, kỹ thuật hoàn
chỉnh, nhưng **thiếu ruột** (người nhập lưu nửa chừng, thiếu trạm / thiếu yếu
tố). `SIZE`-check và poll-size-hai-lần đều mù với cái này vì file "ổn định" và
"đủ size của chính nó".

Chỉ tầng decode/validate của Khối 2 mới soi ra "giờ này thiếu trạm / thiếu yếu
tố". Đừng kỳ vọng lớp tải gánh phần này — cần một bước validate nội dung ở Khối
2, và cơ chế đánh dấu "giờ này có file nhưng nội dung không đủ" để tải lại khi
server cập nhật.

---

## Không làm (và vì sao)

Tránh làm mấy thứ sau — không bõ công cho bối cảnh file nhỏ do người nhập:

- **`REST` resume giữa file:** dành cho file lớn tải dở. File số liệu giờ nhỏ,
  tải lại từ đầu rẻ hơn quản lý resume.
- **Chẻ mảnh một file để tải song song:** resume FTP theo từng luồng, chia mảnh
  trong một file rất lằng nhằng. Song song **giữa** nhiều file là đủ.
- **Mirror đầy đủ toàn thư mục:** chỉ đáng nếu file cũ trên server thực sự hay bị
  sửa trên diện rộng. Index mtime có mục tiêu (mục 3) đã đủ bắt bản đính chính mà
  không cần quét toàn bộ.
