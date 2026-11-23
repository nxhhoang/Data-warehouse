# BỘ DỮ LIỆU GOOGLE ANALYTICS 4 SAMPLE ECOMMERCE

| Hạng mục | Nội dung |
|---|---|
| Bộ dữ liệu | `bigquery-public-data.ga4_obfuscated_sample_ecommerce` |
| Nguồn dữ liệu | Google Merchandise Store — phần xuất sự kiện Google Analytics 4 (GA4) đã ẩn danh |
| Giai đoạn dữ liệu | 2020-11-01 đến 2021-01-31 (92 ngày) |
| Ngày tra cứu tài liệu | 22/10/2026 |
| Ngày thực hiện khảo sát | 22/10/2026 |
| Phạm vi tài liệu | Mô tả bộ dữ liệu, kết quả khảo sát thực nghiệm, và hàm ý thiết kế đối với đồ án CO4031 |

---

## 1. Giới thiệu và phương pháp biên soạn

### 1.1. Mục đích

Tài liệu này trình bày: (i) mô tả cấu trúc và giới hạn của bộ dữ liệu dựa trên tài liệu chính thức của Google; (ii) kết quả khảo sát thực nghiệm nhằm kiểm chứng các giả định ban đầu; (iii) các quyết định thiết kế phát sinh từ kết quả khảo sát, phục vụ việc xây dựng hệ thống hỗ trợ ra quyết định marketing (Marketing Decision Support System — DSS) trong khuôn khổ môn học CO4031.

### 1.2. Phương pháp

Tài liệu được biên soạn từ hai nguồn:

1. **Tra cứu tài liệu chính thức** của Google về bộ dữ liệu mẫu, schema BigQuery export và hạn mức BigQuery Sandbox (liệt kê tại mục 16; toàn bộ truy cập ngày 22/10/2026).
2. **Khảo sát thực nghiệm** bằng chín nhóm truy vấn SQL thực thi trên BigQuery ngày 22/10/2026, tương ứng với chín nội dung kiểm chứng của Giai đoạn 0. Kết quả thô được lưu nguyên trạng dưới dạng chú thích trong các tệp `survey/01` đến `09`; tài liệu này chỉ trích số liệu từ các kết quả đó.

### 1.3. Quy ước thuật ngữ

| Thuật ngữ | Định nghĩa trong tài liệu này |
|---|---|
| Sự kiện (event) | Một bản ghi logic trong bảng `events_YYYYMMDD`; các dòng vật lý phát sinh từ cấu trúc lặp (`event_params`, `items`) thuộc cùng một sự kiện |
| Phiên (session) | Cặp (`user_pseudo_id`, `ga_session_id`), trong đó `ga_session_id` là tham số sự kiện |
| Giao dịch hợp lệ | Sự kiện `purchase` có `transaction_id` khác NULL và không thuộc `('(not set)', '<Other>', '(data deleted)', '')`, có `purchase_revenue_in_usd` > 0; khi cặp (`user_pseudo_id`, `transaction_id`) trùng, lấy sự kiện có `event_timestamp` nhỏ nhất (định nghĩa chốt tại mục 3.4 của báo cáo) |
| Nguồn cấp người dùng | Giá trị `traffic_source` tại sự kiện đầu tiên của một người dùng |
| Nguồn cấp phiên | Giá trị tham số `source`/`medium` tại sự kiện đầu tiên của phiên có mang tham số này |
| Người dùng | Định danh quan sát được `user_pseudo_id`; không tương ứng bắt buộc với một cá nhân ngoài đời thực |

Quy ước số liệu: dấu chấm phân cách hàng nghìn, dấu phẩy phân cách phần thập phân (ví dụ: 4.295.584; 84,4%). Đơn vị tiền tệ ghi bằng USD.

---

# PHẦN A. MÔ TẢ BỘ DỮ LIỆU THEO TÀI LIỆU CHÍNH THỨC

## 2. Tổng quan

Bộ dữ liệu chứa phần xuất sự kiện GA4 của Google Merchandise Store — một website bán lẻ sử dụng chuẩn triển khai thương mại điện tử web của Google Analytics cùng tính năng enhanced measurement. Dữ liệu đã được ẩn danh ("obfuscated") nhằm mô phỏng một bộ dữ liệu thực tế.

Cấu trúc lưu trữ: mỗi ngày một bảng `events_YYYYMMDD`; truy vấn nhiều ngày sử dụng ký tự đại diện `events_*` cùng cột giả `_TABLE_SUFFIX`. Khảo sát xác nhận đủ 92 bảng, không thiếu ngày nào (mục 6).

Theo trang chính thức của bộ dữ liệu (cập nhật 19/08/2026), bộ dữ liệu "chứa dữ liệu đã ẩn danh mô phỏng một bộ dữ liệu thực tế từ một triển khai Google Analytics; một số trường chứa giá trị thay thế gồm `<Other>`, NULL và chuỗi rỗng; do ẩn danh, tính nhất quán nội bộ của bộ dữ liệu có thể bị giới hạn ở mức nhất định" (dịch từ nguyên văn). Bộ dữ liệu không thể so sánh với Google Analytics Demo Account của cùng website do dữ liệu khác nhau.

## 3. Cấu trúc dữ liệu (schema)

Bộ dữ liệu sử dụng schema BigQuery export thế hệ 2020–2021, không bao gồm các trường của schema hiện hành: `batch_page_id`, `batch_ordering_id`, `batch_event_index`, `collected_traffic_source`, `session_traffic_source_last_click`, `privacy_info`, `is_active_user`, `item_params`.

### 3.1. Nhóm trường sự kiện

| Trường | Kiểu dữ liệu | Ý nghĩa |
|---|---|---|
| `event_date` | STRING (`YYYYMMDD`) | Ngày phát sinh theo múi giờ đăng ký của property |
| `event_timestamp` | INTEGER (microgiây, UTC) | Thời điểm nhận sự kiện; các sự kiện cùng lô gửi có thể cùng giá trị |
| `event_name` | STRING | Loại sự kiện; khảo sát ghi nhận 17 loại (mục 7) |
| `event_bundle_sequence_id` | INTEGER | Thứ tự lô gửi; sử dụng để hỗ trợ sắp thứ tự và khử trùng lặp |
| `event_value_in_usd`, `event_previous_timestamp` | FLOAT / INTEGER | Ít dùng trong phạm vi đồ án |
| `event_params` | REPEATED RECORD | Cặp khóa–giá trị (`key`; `value.string_value`, `value.int_value`, `value.double_value`, `value.float_value`); truy xuất bằng `UNNEST` |

### 3.2. Nhóm trường người dùng

`user_pseudo_id` (định danh quan sát được), `user_id` (thường rỗng với website không cấu hình), `user_first_touch_timestamp`, `user_properties`, `user_ltv`.

### 3.3. Nhóm trường bối cảnh

- `traffic_source` (source, medium, name): thông tin quy kết nguồn thu hút người dùng lần đầu.
- `device` (category, operating_system, `web_info.browser`, ngôn ngữ) và `geo` (city, region, country, continent): bối cảnh thiết bị và địa lý.
- `ecommerce`: `transaction_id`, `purchase_revenue_in_usd`, `total_item_quantity`, `unique_items`, thuế, phí vận chuyển.
- `items` (mảng lặp): `item_id`, `item_name`, `item_brand`, `item_variant`, `item_category` đến `item_category5`, `price`, `price_in_usd`, `quantity`, `item_revenue`, cùng các trường danh sách hiển thị và khuyến mãi.

Về quy kết nguồn, tài liệu Google phân biệt ba lớp dữ liệu attribution trong BigQuery export: cấp người dùng, cấp phiên và cấp sự kiện. Bộ dữ liệu này không có trường quy kết cấp phiên của schema hiện hành; do đó nguồn cấp phiên phải được phục dựng từ tham số sự kiện (kết quả tại mục 9.3).

## 4. Môi trường thực hiện: hạn mức BigQuery Sandbox

Theo tài liệu BigQuery Sandbox (truy cập 22/10/2026):

| Hạn mức | Giá trị | Tác động thiết kế |
|---|---|---|
| Lưu trữ | 10 GiB (trọn vòng đời) | Đủ cho toàn bộ dữ liệu đã chuẩn hóa |
| Xử lý truy vấn | 1 TiB/tháng | Đủ cho toàn bộ khảo sát và vận hành ELT |
| Thời hạn bảng | 60 ngày cho mọi bảng, khung nhìn và phân vùng; không thể tắt trong Sandbox | Yêu cầu kịch bản tái tạo toàn bộ kho dữ liệu từ tập lệnh |
| DML (INSERT/UPDATE/DELETE/MERGE) | Không hỗ trợ | ELT phải dùng lệnh CTAS (`CREATE OR REPLACE TABLE ... AS SELECT`) |
| Streaming, Data Transfer Service | Không hỗ trợ | Ngoài phạm vi đồ án trong mọi trường hợp |

Việc bật thanh toán (kèm tín dụng dùng thử 300 USD) sẽ gỡ toàn bộ giới hạn nêu trên; đây là phương án dự phòng, không thuộc phương án chính.

## 5. Truy vấn tham khảo do Google cung cấp

Trang truy vấn mẫu chính thức sử dụng chính bộ dữ liệu này, gồm: đếm sự kiện theo ngày và tên sự kiện; đếm người dùng hoạt động, mới và quay lại dựa trên `first_visit`/`first_open`; trích giá trị tham số sự kiện; thống kê mặt hàng thêm giỏ theo người dùng; và hai hàm tạm `GetParamString`/`GetParamInt` phục vụ trích tham số. Các truy vấn này được nhóm tái sử dụng trong giai đoạn khảo sát và ELT.

---

# PHẦN B. KẾT QUẢ KHẢO SÁT THỰC NGHIỆM

## 6. Quy mô dữ liệu

Kết quả từ truy vấn số 1 và 2 (xem `survey/01`, `02`):

| Chỉ số | Giá trị |
|---|---|
| Số bảng ngày | 92 (2020-11-01 đến 2021-01-31; không thiếu ngày) |
| Tổng số sự kiện | 4.295.584 |
| Số người dùng phân biệt | 270.154 |
| Số người dùng có `first_visit` | 257.462 (95,3%) |
| Số phiên | 360.129 (bình quân 1,33 phiên/người dùng) |
| Số sự kiện mua hàng | 5.692 |
| Tổng giá trị mua hàng ghi nhận (chưa khử trùng lặp) | 362.165 USD |

Biến động theo ngày cho thấy tính mùa vụ rõ rệt: từ khoảng 31.000–52.000 sự kiện/ngày đầu tháng 11, tăng mạnh từ cuối tháng 11, đạt cực đại 92.199 sự kiện ngày 08/12/2020, tương ứng giai đoạn mua sắm cuối năm; các ngày cuối tuần có lưu lượng thấp hơn trung bình. Kết quả toàn bộ giai đoạn chỉ được diễn giải trong phạm vi 92 ngày và không khái quát cho cả năm.

## 7. Danh mục sự kiện và phễu chuyển đổi

### 7.1. Danh mục sự kiện

Khảo sát ghi nhận 17 loại sự kiện. Các loại liên quan trực tiếp đến phân tích phễu:

| Sự kiện | Số sự kiện | Số người dùng | Số ngày xuất hiện (trên 92) |
|---|---:|---:|---:|
| view_item | 386.068 | 61.252 | 92 |
| add_to_cart | 58.543 | 12.545 | **74** |
| begin_checkout | 38.757 | 9.715 | 92 |
| add_shipping_info | 19.722 | 9.714 | 92 |
| add_payment_info | 13.899 | 5.751 | 92 |
| purchase | 5.692 | 4.419 | 92 |

Các loại còn lại gồm page_view (1.350.428), user_engagement (1.058.721), scroll (493.072), session_start (354.970), first_visit (257.462), view_promotion (190.104), select_item (31.007), view_search_results (26.172), select_promotion (9.450), click (1.446) và view_item_list (71 sự kiện trên 33 ngày).

Ba kết luận rút ra:

1. Bốn bước phễu chính đều đủ dữ liệu; có thể mở rộng thành sáu bước bằng `add_shipping_info` và `add_payment_info` khi cần phân tích chi tiết quá trình thanh toán.
2. `view_item_list` gần như không tồn tại (71 sự kiện), do đó loại khỏi mô hình phân tích.
3. `add_to_cart` vắng mặt trong 18 trên 92 ngày. Nguyên nhân chưa được xác định; có khả năng liên quan đến cấu hình đo lường của website trong giai đoạn dữ liệu. Hệ quả thiết kế: biểu đồ phễu theo ngày không nội suy cho các ngày thiếu và phải đánh dấu các ngày này; ở cấp độ tổng kỳ, hiện tượng chỉ chiếm khoảng 20% số ngày nên vẫn sử dụng được với ghi chú tương ứng.

### 7.2. Phễu theo người dùng

Trên 270.154 người dùng: xem sản phẩm 61.252 (22,7%); thêm giỏ 12.545 (4,6%); bắt đầu thanh toán 9.715 (3,6%); cung cấp thông tin giao hàng 9.714 (3,6%); cung cấp thông tin thanh toán 5.751 (2,1%); mua hàng 4.419 (1,64%). Suy giảm lớn nhất xảy ra tại bước xem sản phẩm sang thêm giỏ, với xấp xỉ 81% người dùng xem sản phẩm không thực hiện thêm giỏ trong kỳ. Số liệu này là đầu vào cho bộ chỉ số mạng lưới trong ứng dụng DSS.

## 8. Chất lượng dữ liệu mua hàng và quy tắc khử trùng lặp

Kết quả từ truy vấn số 4 (`survey/04`):

- 5.692 sự kiện purchase, trong đó 5.692 (100%) có `purchase_revenue_in_usd`; 5.669 (99,6%) có `transaction_id`; 5.242 (92,1%) có `total_item_quantity`; hai sự kiện không có dòng mặt hàng.
- Chỉ có 4.452 mã giao dịch phân biệt trên 5.692 sự kiện, cho thấy tồn tại trùng lặp.

Hai dạng trùng lặp được phân loại:

1. **Nhóm mã `(not set)`:** một người dùng phát sinh 3–14 sự kiện purchase trong khoảng vài chục phút (trường hợp nhiều nhất: 14 sự kiện trong 29 phút cùng ngày). Mẫu hình này có dấu hiệu lỗi triển khai tag đo lường; tuy nhiên, nguyên nhân chính xác không thể kết luận chỉ từ dữ liệu hiện có.
2. **Trùng lặp theo mã giao dịch:** cùng cặp (người dùng, mã giao dịch) xuất hiện 2–4 dòng; một bộ phận các cặp này có cùng `event_timestamp`, phù hợp với giả thuyết bản ghi trùng trong quá trình thu thập.

Quy tắc xử lý (chốt cho từ điển chỉ số):

- Giao dịch hợp lệ được định nghĩa như tại mục 1.3.
- Các chỉ số giao dịch và doanh thu chỉ tính trên giao dịch hợp lệ.
- Người mua hàng là người dùng có ít nhất một giao dịch hợp lệ.
- Các sự kiện purchase thuộc nhóm `(not set)` được hệ thống trình bày tại trang chất lượng dữ liệu như một điểm bất thường cần theo dõi; chúng không tham gia tính toán doanh thu.

## 9. Nguồn truy cập

### 9.1. Phân bố theo người dùng

| Nguồn / Phương thức | Số người dùng | Tỷ lệ |
|---|---:|---:|
| google / organic | 103.487 | 38,3% |
| (direct) / (none) | 75.951 | 28,1% |
| `<Other>` / `<Other>` | 51.037 | 18,9% |
| `<Other>` / referral | 32.880 | 12,2% |
| shop.googlemerchandisestore.com / referral | 26.065 | 9,6% |
| (data deleted) / (data deleted) | 17.948 | 6,6% |
| google / cpc | 15.527 | 5,7% |
| `<Other>` / organic | 10.095 | 3,7% |

Các giá trị `<Other>` và `(data deleted)` là giá trị thay thế do ẩn danh, chiếm khoảng 41% người dùng. Kết luận: dữ liệu nguồn đủ chất lượng để duy trì bài toán so sánh nguồn truy cập (bài toán B, mục 13), với điều kiện nhóm giá trị ẩn danh được xử lý như một lớp riêng và tỷ lệ này được nêu công khai trong báo cáo.

### 9.2. Tính ổn định của `traffic_source` theo người dùng

84,36% người dùng có đúng một cặp (source, medium) trong toàn kỳ; 15,64% có từ hai đến tám cặp (trong đó 10,75% có hai cặp). Kết quả này không phù hợp với giả định rằng `traffic_source` hoàn toàn bất biến theo người dùng trong bộ dữ liệu. Do đó, nguồn cấp người dùng được xác định theo giá trị tại sự kiện đầu tiên của người dùng (sắp theo `event_timestamp`, dùng `event_bundle_sequence_id` để phá thế hòa); cách xác định này là tất định và lặp lại được.

### 9.3. Nguồn cấp sự kiện và phiên

Danh mục tham số sự kiện (34 khóa, truy vấn số 7) cho thấy sự hiện diện của các tham số quy kết nguồn ở cấp sự kiện: `source` (1.428.080 lần), `medium` (1.439.214), `campaign` (1.439.167), `term` (338.704), `gclid` (118.481), `gclsrc`, `dclid` (15.701), xuất hiện trên khoảng 33% số sự kiện và 15 loại sự kiện. Kết quả này cho phép phục dựng nguồn cấp phiên theo quy ước tại mục 1.3. Tỷ lệ phiên có ít nhất một sự kiện mang tham số nguồn cần được đo bằng truy vấn bổ sung (mục 12) trước khi xác định độ phủ của chỉ tiêu này.

Bài toán so sánh nguồn truy cập được duy trì với hai tầng quy kết: nguồn cấp phiên và nguồn cấp người dùng. Tài liệu cuối cùng cần nêu rõ ranh giới diễn giải: bộ dữ liệu không chứa chi phí quảng cáo và không triển khai mô hình quy kết đầy đủ; do đó các kết quả về nguồn liên quan đến hành vi quan sát được, không cho phép kết luận về hiệu quả đầu tư quảng cáo.

## 10. Phiên và sản phẩm

### 10.1. Phiên

100% sự kiện có tham số `ga_session_id` (truy vấn số 6), do đó định nghĩa phiên tại mục 1.3 khả thi toàn bộ dữ liệu, sản sinh 360.129 phiên. Có 845 phiên (0,23%) phát sinh sự kiện trên hai ngày lịch trở lên. Quy ước gán ngày: phiên thuộc ngày của sự kiện đầu tiên; tỷ lệ ảnh hưởng nhỏ nên quy ước này không làm sai lệch đáng kể phân tích theo ngày.

Các tham số `engaged_session_event`, `session_engaged`, `engagement_time_msec` và `entrances` cho phép tính chỉ số phiên tương tác và thời lượng phiên theo cách định nghĩa của Google Analytics.

### 10.2. Sản phẩm

Số dòng mặt hàng sau `UNNEST(items)`:

| Sự kiện | Dòng mặt hàng | Bình quân mặt hàng/sự kiện | Có `price_in_usd` | Có `quantity` |
|---|---:|---:|---:|---:|
| view_item | 2.748.246 | 7,1 | 0% | 0,7% |
| add_to_cart | 667.426 | 11,4 | 0% | 5,6% |
| begin_checkout | 77.980 | 2,0 | 0% | 97,5% |
| purchase | 16.003 | 2,8 | 97,2% | 97,2% |

Độ phủ thuộc tính trên dòng mặt hàng: `item_id` 100%; `item_name` 100%; `item_brand` 99,7%; `item_category` 99,7%; `item_category2`, `item_category3` 100%; `item_variant` 77%. Khi không được thiết lập, `quantity` nhận giá trị mặc định 1 theo chuẩn GA4.

Số lượng phân biệt: 1.394 `item_id`; 431 `item_name`; 2.957 tổ hợp (`item_name`, `item_variant`). Việc số tổ hợp tên–biến thể vượt số mã sản phẩm cho thấy quan hệ giữa `item_id` và các thuộc tính tên/biến thể không là hàm một–một trong bộ dữ liệu đã ẩn danh; hiện tượng này phù hợp với cảnh báo về tính nhất quán nội bộ của Google (mục 2).

Quy tắc thiết kế đối với `dim_product`:

- Khóa tự nhiên: `item_id`.
- Thuộc tính tên, thương hiệu, biến thể, danh mục: lấy giá trị có tần suất xuất hiện lớn nhất theo `item_id`; được coi là thuộc tính mô tả, không dùng làm khóa.
- Hierarchy phân tích: `item_category` → `item_category2` → `item_category3`.
- Giá trị đơn hàng chỉ tồn tại tại dòng mặt hàng của sự kiện purchase; do đó các chỉ tiêu giá trị tiền tệ chỉ gắn với fact dòng mua, còn các bước xem và thêm giỏ chỉ đo được bằng số lượng.

Do một sự kiện view_item hoặc add_to_cart chứa nhiều dòng mặt hàng, cần phân biệt hai chỉ tiêu trong từ điển: "lượt xem mặt hàng" (đếm trên dòng mặt hàng sau `UNNEST`) và "lượt xem sản phẩm" (đếm trên sự kiện); công thức từng chỉ tiêu phải ghi rõ trong báo cáo.

## 11. Tổng hợp quyết định thiết kế

| # | Nội dung | Kết quả | Quyết định |
|---|---|---|---|
| 1 | Độ phủ ngày | Đủ 92 ngày | Sử dụng toàn bộ giai đoạn dữ liệu |
| 2 | Sự kiện phễu | Đủ bốn bước, có thể mở rộng sáu; `view_item_list` không sử dụng; `add_to_cart` thiếu 18/92 ngày | Phễu sáu bước (thêm `add_shipping_info`, `add_payment_info`); đánh dấu ngày thiếu `add_to_cart` trên biểu đồ theo ngày |
| 3 | Chất lượng purchase | Tồn tại trùng lặp và nhóm `(not set)` | Khử trùng lặp theo giao dịch hợp lệ; loại nhóm `(not set)` khỏi chỉ tiêu doanh thu |
| 4 | Nguồn truy cập | Khoảng 59% người dùng có nguồn nhận diện được; ~41% ẩn danh | Duy trì bài toán nguồn; hai tầng quy kết; nhóm ẩn danh riêng |
| 5 | Phiên | `ga_session_id` phủ 100% | Phiên = (`user_pseudo_id`, `ga_session_id`) |
| 6 | Tham số sự kiện | Có tham số nguồn cấp sự kiện | Phục dựng nguồn cấp phiên |
| 7 | Sản phẩm | `item_id` và danh mục độ phủ xấp xỉ 100%; giá chỉ có ở purchase | `dim_product` khóa `item_id`; hierarchy ba cấp danh mục |
| 8 | Phiên vắt ngày | 0,23% | Gán phiên theo ngày sự kiện đầu tiên |
| 9 | Sandbox | Hạn mức dư tha; cấm DML; hạn 60 ngày | ELT bằng CTAS; kịch bản tái tạo kho bắt buộc |

## 12. Truy vấn bổ sung

| # | Nội dung | Mục đích |
|---|---|---|
| 1 | Đếm sự kiện purchase nhóm `(not set)` và tổng doanh thu sau khử trùng lặp | Đường cơ sở doanh thu cho từ điển chỉ số |
| 2 | Liệt kê các ngày thiếu `add_to_cart` | Dữ liệu đánh dấu cho biểu đồ theo ngày |
| 3 | Tỷ lệ phiên có sự kiện mang tham số `source` | Đánh giá độ phủ nguồn cấp phiên |
| 4 | Số `item_id` có nhiều hơn một tên hoặc danh mục | Lượng hóa mức độ bất ổn thuộc tính sản phẩm |
| 5 | Khảo sát 450 sự kiện purchase thiếu `total_item_quantity` | Chốt quy tắc xử lý nhóm sự kiện này |

## 13. Hàm ý ELT

1. Chuẩn hóa thời gian bằng `TIMESTAMP_MICROS(event_timestamp)`; partition theo ngày sự kiện.
2. Toàn bộ phép nạp dùng CTAS; kịch bản tái tạo kho từ dữ liệu thô là bắt buộc (hạn 60 ngày của Sandbox) và đồng thời là tiêu chí nghiệm thu Bước 6.
3. Nạp tăng dần thiết kế dạng CTAS trên phân vùng ngày mới; minh chứng bằng một lần chạy thử trên khoảng ngày bổ sung. Lệnh MERGE không khả thi trong Sandbox (mục 4).
4. Từ điển chỉ số cần hoàn thiện trước khi lập trình: giao dịch hợp lệ, người mua hàng, phiên tương tác, lượt xem mặt hàng, doanh thu sau khử trùng lặp, các cặp tử số–mẫu số của tỷ lệ chuyển tiếp (tỷ số thuộc dạng không cộng dồn được, lưu tử số và mẫu số riêng ở tầng dữ liệu).
5. Khám phá dữ liệu luôn thực hiện dry-run trước khi thực thi để bảo vệ hạn mức 1 TiB/tháng.

## 14. Tài liệu tham khảo

Tất cả địa chỉ được truy cập ngày 22/10/2026.

1. BigQuery sample dataset for Google Analytics ecommerce web implementation — https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset (cập nhật 19/08/2026; trang kế thừa các địa chỉ `sample-ecommerce-dataset` và `web-ecommerce-tutorial` đã ngừng xuất bản).
2. Traffic attribution data — https://developers.google.com/analytics/bigquery/traffic-attribution-data
3. Basic queries for Google Analytics event data export — https://developers.google.com/analytics/bigquery/basic-queries
4. BigQuery export for Google Analytics (tổng quan cấu trúc tài liệu mới) — https://developers.google.com/analytics/bigquery
5. BigQuery Export schema — https://support.google.com/analytics/answer/7029846
6. BigQuery Export — https://support.google.com/analytics/answer/9358801
7. BigQuery Sandbox — https://cloud.google.com/bigquery/docs/sandbox
8. Kết quả khảo sát thô: `phase0_survey/01` đến `09` (truy vấn và chú thích kết quả, ghi ngày 22/10/2026).
