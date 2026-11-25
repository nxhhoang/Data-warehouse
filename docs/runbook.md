# Runbook — Vận hành hệ thống

Tài liệu này mô tả cách cài đặt và chạy toàn bộ hệ thống theo ba mức, từ mô phỏng cục bộ (không cần tài khoản GCP) tới chạy thật trên BigQuery. Mọi câu lệnh chạy từ thư mục gốc của repository.

## 1. Yêu cầu môi trường

| Thành phần | Mức 0 (mô phỏng) | Mức 1a (chỉ Sandbox) | Mức 1b (+ Pub/Sub) | Mức 2 (Dataflow) |
|---|---|---|---|---|
| Python 3.11+ | cần | cần | cần | cần |
| bash (git-bash trên Windows) | cần | cần | cần | cần |
| Tài khoản Google | không | cần (miễn phí) | cần | cần |
| `gcloud` CLI | không | cần | cần | cần |
| Bật billing | không | **không** | cần (chi phí ~0 trong tầng miễn phí) | cần |

## 2. Cài đặt ban đầu

```bash
# 2.1 Môi trường ảo (mọi script đều tự dùng .venv nếu tồn tại)
bash scripts/setup_venv.sh

# 2.2 Cấu hình
cp .env.example .env          # sửa GCP_PROJECT_ID và các giá trị khác

# 2.3 dbt profile (chỉ cần cho mức 1 trở lên)
cp src/warehouse/profiles.yml.example src/warehouse/profiles.yml
gcloud auth application-default login
```

Trên Windows, dùng git-bash cho các lệnh `bash` ở trên, hoặc kích hoạt venv trong PowerShell (`.venv\Scripts\Activate.ps1`) rồi chạy lệnh python trực tiếp.

## 3. Mức 0 — Mô phỏng cục bộ (không cần GCP)

Một lệnh duy nhất chạy trọn chuỗi: sinh dữ liệu giả → chạy pipeline dry-run → đối chiếu kết quả → xuất nhật ký chất lượng ra CSV:

```bash
bash scripts/run_simulation.sh
```

Chuỗi tương đương từng bước:

```bash
python scripts/make_test_fixture.py --force      # 9 dòng dữ liệu giả phủ mọi nhánh pipeline
python src/pipeline/dataflow_pipeline.py \
    --input_file tests/fixtures/ga4_events_sample.jsonl \
    --output_dir build/pipeline_dry_run --runner=DirectRunner
python scripts/verify_dry_run.py                 # FAIL nếu kết quả lệch định tuyến kỳ vọng
python scripts/export_quality_log.py --from-jsonl build/pipeline_dry_run
```

Fixture gồm 9 dòng với kết quả kỳ vọng: 4 sự kiện hợp lệ, 2 purchase bị loại (thiếu mã giao dịch, doanh thu bằng 0), 1 bản trùng bị khử, 2 dòng dead-letter (JSON hỏng, thiếu ngày), 4 dòng nhật ký chất lượng. `verify_dry_run.py` đối chiếu từng con số này và exit khác 0 nếu lệch.

Chạy unit test (không cần Beam runner):

```bash
pytest tests/ -v
```

GitHub Actions cũng tự chạy toàn bộ mức này trên mọi branch (xem `.github/workflows/ci-tests.yml`) — artifact `pipeline-dry-run-*` chứa kết quả dry-run để tải về kiểm tra.

## 4. Mức 1 — Chạy thật trên BigQuery Sandbox

Dataset public `bigquery-public-data.ga4_obfuscated_sample_ecommerce` query được miễn phí (hạn mức 1 TiB/tháng, khảo sát mục 4 xác nhận dư tha cho toàn bộ ELT). Sandbox cho phép tạo dataset 10 GiB và chạy CTAS, nhưng **không** hỗ trợ streaming inserts — nên pipeline mặc định ghi bằng `FILE_LOADS`. Mức 1 có hai đường: 1a chỉ dùng Sandbox thuần, 1b thêm phần phát lại qua Pub/Sub.

### 4a. Chỉ BigQuery Sandbox (chưa bật billing)

Không Pub/Sub, không GCS, không publisher — dbt đọc thẳng dataset public bằng giá trị mặc định trong `.env.example` (`BQ_RAW_PROJECT=bigquery-public-data`, `BQ_RAW_DATASET=ga4_obfuscated_sample_ecommerce`, `BQ_RAW_TABLE=events_*`). Tầng streaming bị bỏ qua; phạm vi này khớp với tuyên bố "xử lý theo lô" của báo cáo.

```bash
# Không cần sửa gì trong .env — mặc định đã trỏ sang dataset public
bash scripts/rebuild_warehouse.sh     # dbt run + test + KPI views, toàn bộ trong dataset của bạn
python tests/benchmark_kpi.py       # tiêu chí M5: dưới 3 giây
```

Hạn mức cần nhớ: 10 GiB storage (kho này dùng khoảng 1–2 GiB), 1 TiB query/tháng, bảng hết hạn sau 60 ngày — chạy lại script là tái tạo. Bằng chứng nghiệm thu ở đường này là kết quả `dbt test` (parity, reconciliation) và benchmark; nhật ký chất lượng cấp pipeline không có vì pipeline không chạy — khi cần, chạy mức 1b hoặc dùng export từ dry-run.

### 4b. Phát lại qua Pub/Sub (cần bật billing, chi phí gần 0)

Đường đầy đủ mô phỏng streaming. Pub/Sub và GCS chỉ hoạt động trên project đã bật billing, nhưng chi phí nằm gọn trong tầng miễn phí (Pub/Sub 10 GiB message/tháng cho replay ~4,3 GiB; GCS 5 GiB).

```bash
# B1. Phát lại dữ liệu qua Pub/Sub (thử trước với giới hạn nhỏ!)
#     Sửa .env: EXTRACT_LIMIT=1000
python src/extract/publisher.py

# B2. Chạy pipeline ở chế độ streaming, DirectRunner, ghi vào dataset thô
#     FILE_LOADS cần bucket GCS làm nơi chứa file tạm (tầng miễn phí của GCS là đủ)
python src/pipeline/dataflow_pipeline.py \
    --input_subscription=projects/$GCP_PROJECT_ID/subscriptions/ga4-events-sub \
    --raw_dataset=$RAW_DATASET \
    --temp_location=gs://$GCP_PROJECT_ID-df-temp/temp \
    --project=$GCP_PROJECT_ID --region=us-central1 \
    --runner=DirectRunner

# B3. Xây kho dữ liệu: trỏ dbt sang bảng thô do pipeline ghi
#     Sửa .env: BQ_RAW_PROJECT=<GCP_PROJECT_ID>, BQ_RAW_DATASET=$RAW_DATASET
bash scripts/rebuild_warehouse.sh

# B4. Benchmark truy vấn (tiêu chí M5: dưới 3 giây)
python tests/benchmark_kpi.py
```

Khi đã ổn định, đổi `EXTRACT_LIMIT=0` trong `.env` để phát lại toàn bộ 92 ngày. Lưu ý hạn mức: bảng thô `events_*` (~4–5 GiB) cộng kho (~1–2 GiB) nằm sát mốc 10 GiB của Sandbox — đã bật billing thì giới hạn này không còn áp dụng.

### 4c. Streaming local qua Pub/Sub Emulator (không billing, không cần tài khoản GCP)

Muốn chạy đủ tầng streaming (publisher → hàng đợi → pipeline) mà chưa có billing? Google phát hành **emulator chính thức** của Pub/Sub: một process Java chạy trên máy, nói đúng giao thức Pub/Sub. Thư viện client tự trỏ sang nó khi thấy biến `PUBSUB_EMULATOR_HOST` — publisher không cần sửa gì.

Chuẩn bị một lần: cài gcloud CLI + Java 8+, rồi `gcloud components install pubsub-emulator`. Sau đó:

```bash
bash scripts/run_emulator_chain.sh
```

Script tự làm trọn chuỗi: khởi động emulator → publish fixture 9 sự kiện (publisher chế độ `--from-file`, không cần tài khoản GCP) → chạy pipeline đọc subscription thật của emulator (DirectRunner, cửa sổ khử trùng 5 giây cho test nhanh) → đợi output hội tụ đúng định tuyến kỳ vọng (4/2/4) → verify và xuất quality log CSV.

Cần nạp kết quả vào kho thật: chạy thêm `scripts/load_raw_to_bigquery.py --from-jsonl build/emulator_run` — load job phía client (`load_table_from_file`) ghi vào `events_YYYYMMDD` của raw dataset mà **không cần bucket GCS**, nên chạy được trong Sandbox chưa bật billing. Sau đó trỏ `BQ_RAW_*` sang raw dataset và `rebuild_warehouse.sh` như 4b.

Giới hạn cần nhớ của emulator (so với Pub/Sub thật):

- Không hỗ trợ dead-letter policy — publisher đã có nhánh dự phòng tự tạo subscription thường kèm cảnh báo.
- Tin nhắn nằm trong RAM, tắt emulator là mất — chỉ dùng để phát lại được, không phải nơi lưu trữ.
- Đừng benchmark độ trễ thật trên nó; và với replay toàn bộ 92 ngày, emulator chỉ ổn khi pipeline chạy cùng lúc (nó không đệm bền như hàng đợi thật).
- Một ẩn số đã được đánh dấu trong script: khả năng tương thích giữa `ReadFromPubSub` của Beam và emulator. Nếu chuỗi FAIL sau 120 giây, thử thêm `--direct_running_mode=in_memory`; nếu vẫn không được, lùi về file mode (mức 0) — chuỗi transform vẫn được kiểm chứng đầy đủ, chỉ thiếu đúng tầng hàng đợi.

## 5. Mức 2 — Dataflow production

Chỉ khi đã bật billing. Pipeline chuyển sang runner quản lý của GCP:

```bash
python src/pipeline/dataflow_pipeline.py \
    --input_subscription=projects/$GCP_PROJECT_ID/subscriptions/ga4-events-sub \
    --raw_dataset=$RAW_DATASET \
    --runner=DataflowRunner \
    --project=$GCP_PROJECT_ID --region=asia-southeast1 \
    --temp_location=gs://<bucket>/temp \
    --staging_location=gs://<bucket>/staging \
    --service_account_email=<sa>@<project>.iam.gserviceaccount.com
```

Với chế độ dead-letter của subscription, cần cấp quyền publish trên topic DLQ cho service account của Pub/Sub:

```bash
gcloud pubsub topics add-iam-policy-binding ga4-events-dlq \
    --member="serviceAccount:service-<project-number>@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/pubsub.publisher"
```

## 6. Xuất nhật ký chất lượng dữ liệu

Pipeline ghi các vi phạm vào bảng `<raw_dataset>.quality_log` (tương ứng `data/quality_log/` trong `config/quality_rules.yaml`). Xuất ra CSV để nộp kèm báo cáo:

```bash
# Từ bảng BigQuery, theo khoảng ngày
python scripts/export_quality_log.py --start-date 2020-11-01 --end-date 2021-01-31

# Từ kết quả dry-run cục bộ
python scripts/export_quality_log.py --from-jsonl build/pipeline_dry_run
```

## 7. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân và cách xử lý |
|---|---|
| `Missing GCP_PROJECT_ID (see .env.example)` | Chưa có `.env` hoặc chưa export; các script tự đọc `.env` từ thư mục gốc |
| `dbt debug` báo không tìm thấy profile | Chưa copy `profiles.yml.example` thành `profiles.yml` trong `src/warehouse/`, hoặc thiếu `--profiles-dir .` |
| BigQuery từ chối streaming inserts | Sandbox không hỗ trợ; giữ `--write_method=FILE_LOADS` (mặc định) |
| Bảng raw "biến mất" sau ~60 ngày | Sandbox xóa bảng sau 60 ngày; chạy lại `scripts/rebuild_warehouse.sh` (kịch bản tái tạo kho là sản phẩm bắt buộc, khảo sát mục 4) |
| Lỗi `_TABLE_SUFFIX` không hoạt động | Wildcard table bị quote; đã tắt quoting trong `sources.yml`, kiểm tra file chưa bị chỉnh lại |
| Publisher báo 403 trên dead-letter policy | Thiếu IAM cho service account Pub/Sub trên topic DLQ (lệnh cấp quyền ở mục 5) |
| Dry-run sai số lượng sự kiện | Chạy `python scripts/verify_dry_run.py` để xem chi tiết dòng nào lệch; fixture kỳ vọng 4/2/4 như mục 3 |
| Emulator chain FAIL sau 120 giây | Beam chưa nói chuyện được với emulator: thử `--direct_running_mode=in_memory`; không được thì lùi về file mode (mục 3); chi tiết ở mục 4c |
| `gcloud beta emulators pubsub start` báo lỗi Java | Emulator là process Java: cài JDK 8+ rồi chạy lại |
| Test `assert_item_revenue_reconciliation` fail | Có thể là dữ liệu thật: khảo sát ghi nhận 2 purchase không có dòng item và ~2,8% dòng item thiếu giá/số lượng. Ghi vào nhật ký chất lượng, không sửa số liệu |

## 8. Bảo trì định kỳ

- Kiểm tra CI trên GitHub Actions sau mỗi push; job "Python tests & pipeline simulation" phải xanh trước khi merge.
- Sau mỗi lần chạy pipeline thật, xuất nhật ký chất lượng (mục 6) và lưu vào `data/quality_log/` làm bằng chứng nghiệm thu M3.
- Hạn mức Sandbox 10 GiB: nếu đầy, xóa dataset thô cũ rồi phát lại; các lệnh dbt đều dùng CTAS nên tái tạo an toàn.
