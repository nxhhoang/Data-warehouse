# Runbook — Vận hành hệ thống

Tài liệu này mô tả cách cài đặt và chạy toàn bộ hệ thống theo ba mức, từ mô phỏng cục bộ (không cần tài khoản GCP) tới chạy thật trên BigQuery. Mọi câu lệnh chạy từ thư mục gốc của repository.

## 1. Yêu cầu môi trường

| Thành phần | Mức 0 (mô phỏng) | Mức 1 (BigQuery Sandbox) | Mức 2 (Dataflow) |
|---|---|---|---|
| Python 3.11+ | cần | cần | cần |
| bash (git-bash trên Windows) | cần | cần | cần |
| Tài khoản Google | không | cần (miễn phí) | cần |
| `gcloud` CLI | không | cần | cần |
| Bật billing | không | không | cần |

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

## 4. Mức 1 — Chạy thật trên BigQuery Sandbox (miễn phí)

Dataset public `bigquery-public-data.ga4_obfuscated_sample_ecommerce` query được miễn phí (hạn mức 1 TiB/tháng). Sandbox cho phép tạo dataset 10 GiB và chạy CTAS, nhưng **không** hỗ trợ streaming inserts — nên pipeline mặc định ghi bằng `FILE_LOADS`.

```bash
# 4.1 Phát lại dữ liệu qua Pub/Sub (thử trước với giới hạn nhỏ!)
#     Sửa .env: EXTRACT_LIMIT=1000
python src/extract/publisher.py

# 4.2 Chạy pipeline ở chế độ streaming, DirectRunner, ghi vào dataset thô
python src/pipeline/dataflow_pipeline.py \
    --input_subscription=projects/$GCP_PROJECT_ID/subscriptions/ga4-events-sub \
    --raw_dataset=$RAW_DATASET \
    --project=$GCP_PROJECT_ID --region=asia-southeast1 \
    --runner=DirectRunner

# 4.3 Xây kho dữ liệu (dbt đọc bảng thô do pipeline ghi qua biến BQ_RAW_*)
#     Sửa .env: BQ_RAW_PROJECT=<GCP_PROJECT_ID>, BQ_RAW_DATASET=$RAW_DATASET
bash scripts/rebuild_warehouse.sh

# 4.4 Benchmark truy vấn (tiêu chí M5: dưới 3 giây)
python tests/benchmark_kpi.py
```

Khi đã ổn định, đổi `EXTRACT_LIMIT=0` trong `.env` để phát lại toàn bộ 92 ngày.

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
| `Syntax error: Expected ")" but got "*"` ở `stg_ga4_events` | Tên bảng wildcard `events_*` phải nằm trong backtick; giữ `quoting.identifier: true` trong `sources.yml` |
| Publisher báo 403 trên dead-letter policy | Thiếu IAM cho service account Pub/Sub trên topic DLQ (lệnh cấp quyền ở mục 5) |
| Dry-run sai số lượng sự kiện | Chạy `python scripts/verify_dry_run.py` để xem chi tiết dòng nào lệch; fixture kỳ vọng 4/2/4 như mục 3 |
| Test `assert_item_revenue_reconciliation` fail | Có thể là dữ liệu thật: khảo sát ghi nhận 2 purchase không có dòng item và ~2,8% dòng item thiếu giá/số lượng. Ghi vào nhật ký chất lượng, không sửa số liệu |

## 8. Bảo trì định kỳ

- Kiểm tra CI trên GitHub Actions sau mỗi push; job "Python tests & pipeline simulation" phải xanh trước khi merge.
- Sau mỗi lần chạy pipeline thật, xuất nhật ký chất lượng (mục 6) và lưu vào `data/quality_log/` làm bằng chứng nghiệm thu M3.
- Hạn mức Sandbox 10 GiB: nếu đầy, xóa dataset thô cũ rồi phát lại; các lệnh dbt đều dùng CTAS nên tái tạo an toàn.
