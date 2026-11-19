# CLAUDE.md — Room Service & Housekeeping App + AI Concierge

App dịch vụ phòng cho khách lưu trú (khách sạn mini, homestay, boutique): khách gọi đồ ăn, gọi dọn phòng,
theo dõi trạng thái realtime, hỏi Chatbot AI; Lễ tân / Bếp / Buồng phòng xử lý trên Web quản trị.

## Kiến trúc thư mục (monorepo)

```
mobile-app/    Flutter (Android APK) — app khách: đăng nhập mã phòng, đặt món, dọn phòng, chat, nhận FCM
admin-web/     Next.js (React, TypeScript) — Web Lễ tân / Bếp / Buồng phòng (RBAC)
backend-api/   FastAPI (Python 3.12) + PostgreSQL — auth stay_session, orders, housekeeping, checkout, FCM
ai-service/    FastAPI (Python) — AI Concierge, Tool Calling (OpenAI/Gemini), Knowledge Base
docs/          Tài liệu nghiệp vụ, spec chatbot, roadmap
.github/workflows/  CI (lint + test cho từng package)
```

> Stack ở trên là giả định ban đầu — Tech Lead xác nhận/sửa trước khi chạy `/spec`.

## Lệnh thường dùng

| Package | Lint | Test | Build |
|---|---|---|---|
| backend-api | `uv run ruff check . && uv run ruff format --check .` | `uv run pytest -q --cov=app --cov-fail-under=70` | `docker build -t backend-api .` |
| ai-service | `uv run ruff check . && uv run ruff format --check .` | `uv run pytest -q --cov=app --cov-fail-under=70` | `docker build -t ai-service .` |
| admin-web | `npm run lint && npm run typecheck` | `npm test` | `npm run build` |
| mobile-app | `flutter analyze` | `flutter test` | `flutter build apk --release` |

Chạy local: `docker compose up -d db` → `uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000`
(backend-api; ai-service dùng port 8001) · `npm run dev` (admin-web) · `flutter run --dart-define-from-file=env/dev.json` (mobile-app).
Chi tiết: `spec/SPEC-foundation.md`.
Lệnh trong CI (`.github/workflows/`) phải trùng với bảng trên — đổi một chỗ thì cập nhật chỗ kia.

## Luật Git (BẮT BUỘC)

- Nhánh: `main` (production) · `develop` (integration) · `feature/*` · `release/*` · `hotfix/*`.
- **Cấm** commit, push, merge, rebase trực tiếp lên `main`. Chỉ Tech Lead merge vào `main` qua PR từ `release/*` hoặc `hotfix/*`.
- Mọi việc: `git switch develop && git pull` → `git switch -c feature/<JIRA-KEY>-<mo-ta-ngan>`
  (VD `feature/HMA-12-room-code-login`) → code + test → PR nhắm vào **`develop`**.
- Commit theo Conventional Commits, kèm mã Jira: `feat(backend): HMA-12 cap stay_session_token`.
- Không force-push. Không sửa lịch sử nhánh người khác.

## Luật chống lộ mã phòng (BẮT BUỘC)

1. **Không** dùng số phòng tĩnh làm mã đăng nhập.
2. Khi Lễ tân check-in trên Web → phòng chuyển `OCCUPIED`, hệ thống sinh **mã phiên ngẫu nhiên** (≥ 6 ký tự,
   CSPRNG, không đoán được) hoặc **QR**, gắn với một kỳ lưu trú (`stay`), lưu dạng hash.
3. App đổi mã phiên lấy `stay_session_token` (JWT, có `stay_id`, `room_id`, `jti`, `exp` ≤ ngày check-out).
4. Lễ tân duyệt Check-out → token bị **thu hồi ngay** (revoke theo `stay_id`/`jti`); mọi request sau đó trả `401`.
5. Mọi API và mọi Chatbot Tool **lấy `room_id`/`stay_id` từ token đã xác thực**. Cấm nhận `room_id` thô từ
   body/query/header của client hoặc từ nội dung câu chat. Nếu có tham số `room_id` trong input → bỏ qua/từ chối.
6. Endpoint đổi mã có rate limit + khóa tạm khi sai nhiều lần (chống dò mã).

## Nguyên tắc làm việc cho agent

- Đọc spec trước khi code; thay đổi nghiệp vụ phải cập nhật `docs/` trong cùng PR.
- Không đọc/ghi `.env`; dùng `.env.example` để mô tả biến môi trường.
- Không xóa, `.skip`, hay nới assertion của test để pass CI (xem `CONSTRAINTS.md`).
- Chatbot chỉ trả lời từ DB/Knowledge Base/kết quả Tool — không bịa.

## Tài liệu tham chiếu

- @CONSTRAINTS.md — ràng buộc chất lượng, bảo mật, RBAC, kiểm thử
- @docs/domain-rules.md — state machine, ma trận phân việc, quy tắc FCM
- @docs/chatbot-tools-spec.md — system prompt + schema 5 tools
- @docs/roadmap-d01-d27.md — lộ trình 27 ngày, sprint, luồng nhánh
