# Phase 0 — Bộ script khảo sát dữ liệu GA4 Sample eCommerce

Bộ script mapping 1:1 với mục tiêu kiểm chứng trong `GA4 Sample Ecommerce.md` (mục 5) và Phần 5 của kế hoạch bài tập lớn.

## Cách chạy (không cần tải dữ liệu về máy)

1. Mở **https://console.cloud.google.com/bigquery**, đăng nhập bằng tài khoản Google (Sandbox miễn phí là đủ).
2. Trong khung **Explorer**, bấm **+ Add data → Star a project by name**, gõ `bigquery-public-data` → Add. Mở rộng `bigquery-public-data → ga4_obfuscated_sample_ecommerce` để thấy các bảng `events_YYYYMMDD`.
3. Mở tab **Editor**, dán nội dung một file `.sql` bên dưới → bấm **Run** (Ctrl+Enter).
   - File có **2 câu query ngăn cách bằng dấu `;`**: bôi đen từng câu rồi Run selection, hoặc chạy cả script (Console hiển thị kết quả từng câu trong khối "Multiple results").
4. **Dry-run trước khi chạy (mục #9)**: bấm biểu tượng **More** (ba chấm) cạnh nút Run → **Query settings** → bật **Dry run** → Run. Console hiển thị "This query will process X bytes" mà không tính phí, không chạy thật. Tắt Dry run để chạy thật.
   - Hoặc bằng CLI: `bq query --dry_run --use_legacy_sql=false < ten_file.sql`
5. Lưu kết quả: copy/dán hoặc chụp màn hình bảng kết quả vào **báo cáo khảo sát dữ liệu** (đầu ra của Bước 1 trong kế hoạch — dùng cho slide 7 Submission 1).

## Chi phí dự kiến

- File `01` chỉ đọc metadata (INFORMATION_SCHEMA) → **0 bytes, miễn phí**.
- Các file còn lại quét toàn bộ ~3 tháng dữ liệu (vài GB mỗi query). Cả bộ chạy vài lần vẫn < 5% hạn mức 1 TiB/tháng của Sandbox. Vẫn bật dry-run cho lần đầu.

## Danh sách file

| File | Kiểm chứng | Câu hỏi quyết định |
|---|---|---|
| `01_so_bang_va_ngay_thieu.sql` | #1a | Có bao nhiêu bảng, ngày nào thiếu |
| `02_quy_mo_du_lieu.sql` | #1b | Tổng số event, số user, khoảng thời gian |
| `03_danh_sach_event.sql` | #2 | Đủ 4 sự kiện phễu không, mỗi loại bao nhiêu |
| `04_chat_luong_purchase.sql` | #3 | Tỷ lệ purchase có giá trị/mã giao dịch; trùng lặp |
| `05_nguon_truy_cap.sql` | #4 | Phân bố traffic_source, tỷ lệ rỗng, quy kết cấp user |
| `06_phu_ga_session_id.sql` | #5 | Tỷ lệ event có session id đủ để dựng phiên |
| `07_danh_sach_event_params.sql` | #6 | Có key nguồn cấp phiên không (kỳ vọng: không) |
| `08_coverage_thuoc_tinh_item.sql` | #7 | item_category/brand/id đủ cho hierarchy dim_product |
| `09_phien_vat_nua_dem.sql` | #8 | Có bao nhiêu phiên trải qua 2 ngày trở lên |

## Sau khi chạy xong

Điền kết quả vào bảng mục 5 của `GA4 Sample Ecommerce.md` (cột trạng thái), rồi chốt các quyết định:
- Giữ hay thu hẹp Q3 (phụ thuộc file `05`).
- Định nghĩa phiên, quy ước gán ngày phiên (file `06`, `09`).
- Quy tắc dedup giao dịch và định nghĩa "người mua" (file `04`).
- Hierarchy `dim_product` (file `08`).
