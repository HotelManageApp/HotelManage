# HotelManage — Room Service & Housekeeping App + AI Concierge

App dịch vụ phòng cho khách lưu trú tại khách sạn mini, homestay, boutique: khách đăng nhập bằng mã phòng, đặt đồ ăn,
gọi dọn phòng, theo dõi trạng thái realtime và hỏi Chatbot AI; Lễ tân / Bếp / Buồng phòng xử lý trên Web quản trị.

- Quy tắc cho agent và lệnh thường dùng: [CLAUDE.md](CLAUDE.md)
- Ràng buộc chất lượng: [CONSTRAINTS.md](CONSTRAINTS.md)
- Spec từng module: [spec/](spec/) (bắt đầu từ [capability-map.md](spec/capability-map.md))
- Kế hoạch và task: [tasks/plan.md](tasks/plan.md), [tasks/todo.md](tasks/todo.md)
- Nghiệp vụ, chatbot, lộ trình: [docs/](docs/)

## Cấu trúc

```
backend-api/   FastAPI + PostgreSQL (T02)
ai-service/    FastAPI, AI Concierge (T03)
admin-web/     Next.js, Web Lễ tân / Bếp / Buồng phòng (T04)
mobile-app/    Flutter, app khách Android (T05)
infra/db/      Script khởi tạo PostgreSQL local
docs/ spec/ tasks/
```

## Yêu cầu máy

| Công cụ | Phiên bản |
|---|---|
| Docker Desktop (kèm Compose v2+) | mới nhất |
| Python + [uv](https://docs.astral.sh/uv/) | 3.12 |
| Node.js | 20 LTS |
| Flutter (Android SDK, emulator hoặc máy thật) | 3.24 stable |
| Git | 2.40+ |

## Chạy local

```bash
# 1. Database (PostgreSQL 16, tạo sẵn DB "hotel" và "hotel_test")
docker compose up -d db
docker compose ps            # db phải ở trạng thái healthy

# 2. Từng package — hướng dẫn chi tiết sẽ được bổ sung khi T02–T05 xong
#    backend-api : uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000
#    ai-service  : uv sync && uv run uvicorn app.main:app --reload --port 8001
#    admin-web   : npm ci && npm run dev
#    mobile-app  : flutter pub get && flutter run --dart-define-from-file=env/dev.json
```

Thông tin DB mặc định cho dev: `hotel` / `hotel_dev_only` tại `localhost:5432`. Đổi bằng biến `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_PORT` trong shell hoặc file `.env` ở thư mục gốc (đã nằm trong `.gitignore`).

Xóa sạch dữ liệu dev: `docker compose down -v`.

## Biến môi trường và secret

- Mỗi package có `.env.example` mô tả biến cần thiết; sao chép thành `.env` rồi điền. **Không commit `.env`.**
- Không commit: service-account Firebase, `google-services.json`, keystore Android, `env/dev.json`, `env/prod.json`.
- CI chạy gitleaks trên mọi PR (T06).

## Quy trình Git

```
feature/HMA-<n>-<mo-ta> ──PR──▶ develop ──▶ release/x.y.z ──PR (Tech Lead)──▶ main
```

1. `git switch develop && git pull`
2. `git switch -c feature/HMA-<n>-<mo-ta-ngan>` (số `n` = số task trong `tasks/todo.md` = số Jira)
3. Code + test, commit theo Conventional Commits kèm mã Jira: `feat(backend): HMA-12 cap stay_session_token`
4. Mở PR vào **`develop`**, điền template, chờ CI xanh + ≥ 1 review.

**Không ai ngoài Tech Lead commit, push hay merge vào `main`.** Không force-push.

## Thiết lập branch protection (Tech Lead, làm một lần trên GitHub)

Settings → Branches → Add branch ruleset (hoặc Branch protection rule):

**`main`**
- Require a pull request before merging, Require approvals: 1
- Require status checks to pass (chọn các job CI sau khi T06 chạy lần đầu)
- Restrict who can push / bypass: chỉ tài khoản Tech Lead
- Block force pushes, Restrict deletions

**`develop`**
- Require a pull request before merging, Require approvals: 1
- Require status checks to pass
- Block force pushes, Restrict deletions

`main` vẫn là default branch (production). Khi mở PR, nhớ đổi base sang `develop`.
