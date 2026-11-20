# Kiểm thử tải — T55 (2026-11-20)

Mục tiêu (`CONSTRAINTS.md` C6): 50 khách đồng thời không có lỗi 5xx; API p95 < 500 ms (không tính gọi LLM).

## Kịch bản (`loadtest/guest_flow.js`, k6)

50 khách ảo, mỗi khách một kỳ lưu trú thật (token khách thật), lặp liên tục:

1. Mở app: `GET /guest/me`
2. Xem menu: `GET /guest/menu` — nghỉ 1 s
3. Đặt 1 món ngẫu nhiên: `POST /guest/orders` (kèm `Idempotency-Key`); nếu tạo được → xem chi tiết `GET /guest/orders/{id}` — nghỉ 1 s
4. Theo dõi: `GET /guest/orders`, `GET /guest/housekeeping-requests` — nghỉ 2 s

`409 TOO_MANY_PENDING_ORDERS` (tối đa 5 đơn chờ mỗi stay, Bếp không xử lý trong lúc thử) là câu trả lời nghiệp vụ, được tính là
phản hồi hợp lệ. Ngưỡng: `http_req_failed = 0`, `server_errors_5xx = 0`, p95 < 500 ms cho mọi lời gọi và riêng `place_order`.

Token lấy từ CLI dev, không cần mật khẩu trong kịch bản:

```bash
docker exec <backend> python -m app.cli seed-dev-stays --count 50 > loadtest/tokens.json
k6 run -e BASE_URL=http://localhost:8010 -e TOKENS=loadtest/tokens.json -e DURATION=3m loadtest/guest_flow.js
docker exec <backend> python -m app.cli seed-dev-stays --close
```

Máy không có k6: `loadtest/guest_flow.py` chạy cùng kịch bản bằng Python (`uv run --with httpx python loadtest/guest_flow.py ...`).

## Môi trường

Bản gộp Phase 1–5 + T54, docker compose local trên một máy (16 CPU, 8 GB cho Docker): backend-api 1 tiến trình uvicorn
(kèm outbox worker), PostgreSQL 16, `APP_ENV=dev`, `FCM_SENDER=log`. k6 0.54.0 chạy trong container trên cùng máy
(`host.docker.internal:8010`). Chưa có staging/production (T56) nên đây là số liệu local.

## Kết quả (lần chạy 3 phút, 50 stay mới)

| Chỉ số | Kết quả | Ngưỡng |
|---|---|---|
| Số request | 11 495 (≈ 62,5 req/s), 2 249 vòng lặp | — |
| Lỗi 5xx | **0** | 0 |
| `http_req_failed` | **0 %** | 0 % |
| Check đạt | **100 %** (11 495 / 11 495) | > 99 % |
| p50 / p90 / **p95** / max (mọi API) | 8,3 / 15,8 / **26,3** / 518,9 ms | p95 < 500 ms |
| **p95** `POST /guest/orders` | **44,8 ms** (max 518,9 ms) | p95 < 500 ms |
| Đơn tạo thành công | 250 (mỗi stay tới giới hạn 5 đơn chờ), còn lại `409` đúng quy tắc | — |
| CPU / RAM sau khi chạy | backend 83 MB, db 47 MB; CPU nhàn rỗi trở lại ngay | — |

Hai lần chạy 2 phút trước đó: p95 51,8 ms và 24,3 ms, không 5xx. Lần đầu báo `http_req_failed` 16 % vì kịch bản lúc đó còn tính
`409` giới hạn nghiệp vụ là lỗi — đã sửa kịch bản (`http.expectedStatuses(200, 201, 409)`), không phải lỗi ứng dụng.

**Kết luận:** đạt C6 cho API khách với 50 khách đồng thời; còn dư nhiều (p95 ≈ 5 % ngưỡng). Max ~0,5 s xuất hiện vài lần ở
những giây đầu (kết nối DB đầu tiên của pool).

## Chưa đo trong T55

- Chatbot (p95 < 8 s) phụ thuộc nhà cung cấp LLM — đo khi chạy `/eval-bot` với LLM thật (`tests/eval`, ghi `p95_seconds`).
- FCM ≤ 5 s: cần Firebase thật (T23 đo bằng outbox).
- Chạy lại kịch bản trên staging sau T56 (mạng thật, HTTPS, Postgres managed) — dùng đúng lệnh ở trên với `BASE_URL` của staging.
