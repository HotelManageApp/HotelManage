# Triển khai staging / production (T56)

Một máy chủ Linux có Docker (VPS 2 vCPU / 4 GB là đủ cho một khách sạn mini — xem `docs/load-test.md`) chạy
`docker-compose.prod.yml`: Caddy (HTTPS tự động), backend-api (kèm outbox worker gửi FCM), ai-service, admin-web.
PostgreSQL nên dùng dịch vụ managed (Neon, Supabase, RDS, Cloud SQL…); có sẵn container `db` cho staging nhỏ.

```
Internet ──443──▶ Caddy ── api.<domain>   /api/v1/chat ─▶ ai-service:8001 ─┐
                       │                  /api/v1/*    ─▶ backend-api:8000 ◀┘ (token khách)
                       └─ admin.<domain>  ─▶ admin-web:3000 ── /api/v1/* ─▶ backend-api:8000
backend-api ─▶ PostgreSQL (DATABASE_URL)        backend-api ─▶ FCM HTTP v1
ai-service  ─▶ Gemini / OpenAI
```

Chỉ Caddy mở cổng (80/443). App khách dùng **một** địa chỉ `https://api.<domain>` cho cả backend và chatbot
(`AI_BASE_URL` có thể bỏ trống — mặc định bằng `API_BASE_URL`).

## 1. Chuẩn bị (một lần)

1. **DNS:** bản ghi A/AAAA `api.<domain>` và `admin.<domain>` trỏ về IP máy chủ. Cổng 80 và 443 mở.
2. **PostgreSQL managed:** tạo database `hotel`, user riêng; lấy chuỗi kết nối dạng
   `postgresql+asyncpg://USER:PASSWORD@HOST:5432/hotel` (bật SSL theo nhà cung cấp: thêm `?ssl=require`).
3. **Firebase:** service account có quyền FCM → file JSON, chép lên máy chủ (VD `/etc/hotelapp/fcm.json`, quyền 600).
4. **LLM:** khóa Gemini hoặc OpenAI.
5. **Tệp biến môi trường** ngoài repo, VD `/etc/hotelapp/prod.env` (quyền 600). Sinh secret bằng
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` — mỗi biến một giá trị khác nhau:

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `APP_VERSION` | nên có | tag image, VD `1.0.0` (hiện ở `/health`) |
| `DATABASE_URL` | ✅ | chuỗi kết nối asyncpg ở bước 2 |
| `STAFF_JWT_SECRET`, `STAY_JWT_SECRET`, `ROOM_CODE_PEPPER` | ✅ | ≥ 32 ký tự, ngẫu nhiên. Đổi `ROOM_CODE_PEPPER` làm mọi mã phòng đang dùng hết hiệu lực |
| `CONCIERGE_SIGNING_KEY` | ✅ | ≥ 32 ký tự (ký bản tóm tắt chờ xác nhận của chatbot) |
| `LLM_PROVIDER` + `GEMINI_API_KEY` hoặc `OPENAI_API_KEY` | ✅ | `fake` bị từ chối khi `APP_ENV=prod` |
| `API_DOMAIN`, `ADMIN_DOMAIN`, `ACME_EMAIL` | ✅ | tên miền và email nhận thông báo Let's Encrypt |
| `FCM_PROJECT_ID`, `FCM_CREDENTIALS_HOST_FILE` | ✅ (push) | `FCM_SENDER=log` để tạm tắt push |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | chỉ khi dùng container `db` | thay cho DB managed |
| `HOTEL_TIMEZONE`, `LOG_LEVEL`, `GEMINI_MODEL`, `OPENAI_MODEL` | tùy chọn | mặc định `Asia/Ho_Chi_Minh`, `INFO`, … |

Không đặt secret trong repo, trong `docker-compose.prod.yml` hay trong tên image. Trên nền tảng PaaS (Render, Railway,
Fly.io, Cloud Run…) khai báo cùng các biến này trong phần "Environment/Secrets" của dịch vụ thay cho tệp `prod.env`.

## 2. Triển khai

```bash
git clone <repo> /opt/hotelapp && cd /opt/hotelapp
git checkout v1.0.0                                   # đúng tag đã phát hành (T58)
docker compose -f docker-compose.prod.yml --env-file /etc/hotelapp/prod.env up -d --build
#   staging nhỏ không có DB managed: thêm  --profile local-db
```

Thứ tự khởi động do compose đảm bảo: (`db`) → `migrate` (`alembic upgrade head`, chạy xong thì thoát) → `backend-api`
→ `ai-service`, `admin-web` → `caddy` (tự xin chứng chỉ HTTPS lần đầu, mất ~30 s).

### Kiểm tra sau khi triển khai

```bash
curl -fsS https://api.<domain>/health          # {"status":"ok","db":"ok","version":"1.0.0"}
curl -fsSI https://admin.<domain>/vi/login     # 200, có Strict-Transport-Security và X-Frame-Options: DENY
docker compose -f docker-compose.prod.yml ps   # migrate "exited (0)", các dịch vụ khác "healthy"
```

`/docs` và `/openapi.json` tắt ở prod (trả `404`).

### Dữ liệu ban đầu

```bash
C="docker compose -f docker-compose.prod.yml --env-file /etc/hotelapp/prod.env exec backend-api"
$C python -m app.cli create-staff --email letan@<domain> --name "Lễ tân" --role RECEPTION   # hỏi mật khẩu, không nhận qua tham số
$C python -m app.cli create-staff --email bep@<domain> --name "Bếp" --role KITCHEN
$C python -m app.cli create-staff --email buongphong@<domain> --name "Buồng phòng" --role HOUSEKEEPING
docker compose -f docker-compose.prod.yml cp rooms.csv backend-api:/tmp/rooms.csv && $C python -m app.cli seed-rooms --from-file /tmp/rooms.csv
# tương tự seed-menu (menu.csv) và seed-kb (kb.yaml) — mẫu ở backend-api/seeds/
```

`seed-dev`, `seed-dev-stays` từ chối chạy ở prod.

## 3. Vận hành

- **Cập nhật phiên bản:** `git fetch --tags && git checkout vX.Y.Z` rồi chạy lại lệnh `up -d --build` (migrate tự chạy trước).
- **Quay lại bản trước:** checkout tag cũ và `up -d --build`. Migration không tự hạ cấp — chỉ quay lại khi bản mới không có
  migration phá vỡ tương thích (ghi trong `CHANGELOG.md`).
- **Sao lưu:** bật backup tự động của DB managed (giữ ≥ 7 ngày). Container `db`: `pg_dump` hằng đêm ra ngoài máy chủ.
- **Log:** `docker compose -f docker-compose.prod.yml logs -f backend-api ai-service` (JSON một dòng, có `request_id`;
  không chứa mã phòng, JWT, khóa API).
- **Thu hồi khẩn cấp:** đổi `STAY_JWT_SECRET` → mọi khách phải nhập lại mã; đổi `STAFF_JWT_SECRET` → mọi nhân viên đăng nhập lại.

## 4. Bảo mật khi triển khai (từ `docs/security-report.md`)

- **F3 — IP thật cho rate limit:** backend-api và ai-service chạy uvicorn `--proxy-headers` với `FORWARDED_ALLOW_IPS="*"`;
  điều này an toàn **chỉ vì** hai container không mở cổng ra ngoài (chỉ Caddy và admin-web gọi được). Nếu đưa backend lên
  nền tảng có load balancer riêng, đặt `FORWARDED_ALLOW_IPS` bằng dải IP của load balancer, không dùng `*`.
- HTTPS bắt buộc (Caddy chuyển 80 → 443, HSTS 1 năm). App Android bản release chỉ gọi `https://`.
- Sau khi triển khai staging: chạy lại `loadtest/guest_flow.js` và bộ thử bảo mật với `BASE_URL` của staging.

## 5. Đã kiểm chứng (2026-11-20, local)

`docker compose -f docker-compose.prod.yml --profile local-db up -d --build` với `API_DOMAIN=api.localhost`,
`ADMIN_DOMAIN=admin.localhost` (Caddy tự cấp chứng chỉ nội bộ cho `*.localhost`), `APP_ENV=prod`:

| Kiểm tra | Kết quả |
|---|---|
| Build 3 image (backend-api, ai-service, admin-web standalone Node 24) | Đạt |
| `migrate` chạy `alembic upgrade head` rồi thoát | `Exited (0)` |
| backend-api, ai-service, admin-web, db | `healthy` |
| `GET https://api.localhost/health` | `{"status":"ok","db":"ok","version":"t56-local"}` |
| `http://` → `https://` | `308` |
| `https://admin.localhost/vi/login` | `200`, có HSTS, `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'` |
| `/api/v1/chat` trên `api.localhost` đi tới ai-service; `/api/v1/*` qua `admin.localhost` tới backend | `401` đúng envelope của từng dịch vụ |
| `/docs` ở prod | `404` |
| Log backend không có JWT / traceback | Đạt |

Chưa triển khai lên máy chủ/cloud thật — cần tài khoản hạ tầng, tên miền, DB managed, Firebase và khóa LLM của đơn vị.
