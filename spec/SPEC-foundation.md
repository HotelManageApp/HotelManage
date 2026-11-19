# Spec: foundation — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: uv, Jira key `HMA`, Riverpod; tên repo chốt khi tạo GitHub
Module id: `foundation` · Phụ thuộc: — · Mức: MVP · Sprint 1 (D01) · Map: [capability-map.md](capability-map.md)

## Objective

Dựng bộ khung chạy được, kiểm thử được cho cả 4 package, để mọi module sau chỉ việc thêm tính năng
mà không phải bàn lại cấu trúc, quy ước lỗi, cấu hình hay CI.

**Người dùng của module này:** thành viên nhóm và Claude Code (không phải khách/nhân viên khách sạn).

**User stories**
- Là thành viên mới, tôi clone repo, làm theo README, chạy được cả 4 package local trong ≤ 15 phút.
- Là người mở PR, CI tự chạy lint + test đúng package bị đổi và chặn merge khi đỏ, khi coverage tụt dưới ngưỡng hoặc khi lộ secret.
- Là dev backend/web/app, tôi có sẵn: cấu hình qua biến môi trường, định dạng lỗi thống nhất, log JSON có request id,
  client HTTP và i18n vi/en — chỉ việc dùng.

**Không thuộc module này:** bảng nghiệp vụ (room, stay, order…), auth, màn hình nghiệp vụ — thuộc các module sau.

## Tech Stack

| Package | Stack (phiên bản tối thiểu) |
|---|---|
| backend-api | Python 3.12, FastAPI 0.115, Pydantic v2 + pydantic-settings, SQLAlchemy 2.0 (async, asyncpg), Alembic, structlog; quản lý deps bằng **uv** (`uv.lock`) |
| ai-service | Python 3.12, FastAPI 0.115, Pydantic v2, httpx; uv; lớp `LLMClient` (adapter Gemini/OpenAI) |
| admin-web | Node 20 LTS, Next.js 15 (App Router) + TypeScript strict, Tailwind CSS, next-intl (vi/en), Vitest + Testing Library |
| mobile-app | Flutter 3.24 stable (Dart 3.5), Riverpod, go_router, dio, flutter_secure_storage, intl/ARB (vi/en) |
| DB / hạ tầng | PostgreSQL 16 (docker compose local), GitHub Actions, gitleaks |

## Commands

```bash
# Hạ tầng local
docker compose up -d db                          # PostgreSQL 16 tại localhost:5432

# backend-api  (cd backend-api)
uv sync                                          # cài deps theo uv.lock
uv run alembic upgrade head                      # chạy migration
uv run uvicorn app.main:app --reload --port 8000
uv run ruff check . && uv run ruff format --check .
uv run pytest -q --cov=app --cov-fail-under=70

# ai-service  (cd ai-service)
uv sync
uv run uvicorn app.main:app --reload --port 8001
uv run ruff check . && uv run ruff format --check .
uv run pytest -q --cov=app --cov-fail-under=70

# admin-web  (cd admin-web)
npm ci
npm run dev                                      # http://localhost:3000
npm run lint && npm run typecheck
npm test                                         # vitest run
npm run build

# mobile-app  (cd mobile-app)
flutter pub get
flutter run --dart-define-from-file=env/dev.json
flutter analyze
flutter test
flutter build apk --release --dart-define-from-file=env/prod.json
```

> Khi spec được duyệt, bảng lệnh trong `CLAUDE.md` cập nhật thêm tiền tố `uv run` cho khớp.

## Project Structure

```
.
├── docker-compose.yml          db (postgres:16), backend-api, ai-service (profile "full")
├── .github/
│   ├── workflows/
│   │   ├── backend-api.yml     path filter backend-api/**  → ruff + pytest (service postgres) + coverage
│   │   ├── ai-service.yml      path filter ai-service/**   → ruff + pytest + coverage
│   │   ├── admin-web.yml       path filter admin-web/**    → lint + typecheck + vitest + build
│   │   ├── mobile-app.yml      path filter mobile-app/**   → analyze + test (+ build apk debug trên develop)
│   │   └── security.yml        mọi PR → gitleaks
│   └── pull_request_template.md   Jira key, link spec, checklist test/CONSTRAINTS
├── backend-api/
│   ├── app/
│   │   ├── main.py             create_app(): middleware, error handlers, routers
│   │   ├── core/               config.py (Settings), logging.py, errors.py, db.py, request_id.py
│   │   ├── api/                health.py (+ router của các module sau)
│   │   └── modules/            mỗi module nghiệp vụ một thư mục (rỗng ở foundation)
│   ├── migrations/             Alembic (revision nền: extension pgcrypto, bảng hotel_settings)
│   ├── tests/                  unit/, integration/ (conftest: DB test + httpx AsyncClient)
│   ├── pyproject.toml  uv.lock  .env.example  Dockerfile
├── ai-service/
│   ├── app/  main.py  core/ (config, logging, errors)  llm/ (base.py, gemini.py, openai.py, fake.py)
│   ├── tests/
│   ├── pyproject.toml  uv.lock  .env.example  Dockerfile
├── admin-web/
│   ├── src/app/[locale]/       layout + trang /health tạm (hiển thị trạng thái backend)
│   ├── src/lib/api-client.ts   fetch wrapper + parse lỗi chuẩn
│   ├── src/i18n/  messages/vi.json  messages/en.json
│   ├── tests/
│   ├── package.json  .env.example
├── mobile-app/
│   ├── lib/  main.dart  app/ (router, theme)  core/ (api_client.dart, config.dart, errors.dart)  l10n/
│   ├── test/
│   ├── env/dev.example.json  env/prod.example.json
│   └── pubspec.yaml
├── docs/  spec/  CLAUDE.md  CONSTRAINTS.md  README.md
```

## Quy ước dùng chung (contract cho mọi module sau)

### Định dạng lỗi API (backend-api & ai-service)

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Mô tả ngắn, an toàn để hiển thị", "details": [ { "field": "items[0].quantity", "issue": "must be >= 1" } ], "request_id": "01JD..." } }
```

| HTTP | `code` |
|---|---|
| 400 | `VALIDATION_ERROR`, `BAD_REQUEST` |
| 401 | `UNAUTHORIZED` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 409 | `CONFLICT`, `INVALID_TRANSITION` |
| 429 | `RATE_LIMITED` |
| 500 | `INTERNAL_ERROR` (không lộ stack trace) |

- Lỗi validation của FastAPI (422 mặc định) được map về **400 `VALIDATION_ERROR`**.
- Mọi response có header `X-Request-ID` (nhận từ client nếu hợp lệ, không thì sinh ULID).

### API

- Prefix `/api/v1`. JSON `snake_case`. Thời gian ISO-8601 UTC (`2026-11-19T07:30:00Z`); hiển thị theo `Asia/Ho_Chi_Minh` ở client.
- Tiền: số nguyên VND, trường hậu tố `_vnd`. ID: UUID v4.
- `GET /health` → `200 {"status":"ok","db":"ok","version":"<git sha>"}`; DB lỗi → `503`.

### Cấu hình & secrets

- Chỉ đọc qua `Settings` (pydantic-settings) / `--dart-define` / `process.env` có kiểm tra khi khởi động; thiếu biến bắt buộc → app không start, báo tên biến.
- `.env`, `env/dev.json`, `env/prod.json`, `*service-account*.json` nằm trong `.gitignore`; chỉ commit file `*.example`.

### Logging

- JSON một dòng: `timestamp`, `level`, `request_id`, `path`, `status`, `duration_ms`.
- Processor che giấu (redact) các khóa: `authorization`, `token`, `room_code`, `password`, `api_key`, `fcm_token` (C4.5).

## Code Style

**Python** — ruff (rules `E,F,I,B,UP,S,ASYNC`), line 100, type hints bắt buộc ở hàm public, async end-to-end.

```python
# backend-api/app/core/errors.py
class AppError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class InvalidTransition(AppError):
    status_code = 409
    code = "INVALID_TRANSITION"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message,
                           "details": exc.details, "request_id": request.state.request_id}},
    )
```

- Router mỏng → service (logic nghiệp vụ) → repository (SQLAlchemy). Không query DB trong router.
- Tên file/hàm `snake_case`, class `PascalCase`, hằng số `UPPER_SNAKE`.

**TypeScript** — ESLint (next/core-web-vitals + typescript-eslint strict), Prettier, `strict: true`, không `any`.
Component `PascalCase.tsx`, hook `useXxx.ts`, server component mặc định, `"use client"` chỉ khi cần.

**Dart** — `flutter_lints` + `very_good_analysis`, `dart format`. Widget `PascalCase`, file `snake_case.dart`.
State qua Riverpod provider; không gọi API trực tiếp trong widget.

**Commit:** Conventional Commits + Jira key — `feat(backend): HMA-3 add error envelope`.

## Testing Strategy

| Package | Framework | Vị trí | Mức kiểm thử ở foundation |
|---|---|---|---|
| backend-api | pytest, pytest-asyncio, httpx AsyncClient, pytest-cov | `tests/unit`, `tests/integration` | `/health` ok + DB down → 503; envelope lỗi cho 400/404/409/500; 422→400; `X-Request-ID`; redact log; thiếu env → fail start |
| ai-service | pytest, `FakeLLMClient` | `tests/` | `/health`; chọn adapter theo `LLM_PROVIDER`; envelope lỗi |
| admin-web | Vitest + Testing Library | `tests/` | `api-client` parse envelope lỗi; chuyển locale vi/en |
| mobile-app | flutter_test | `test/` | `ApiClient` map lỗi → `AppException`; app khởi động hiển thị chuỗi vi/en |

- Integration test backend dùng PostgreSQL thật (service container trong CI, docker compose local) — **không** dùng SQLite.
- Coverage ≥ 70% dòng cho backend-api và ai-service (C5.6), gate bằng `--cov-fail-under=70`.
- Không gọi LLM thật trong CI; test dùng `FakeLLMClient`. Test gọi LLM thật đánh dấu `@pytest.mark.live`, mặc định bỏ qua qua cấu hình marker (không dùng `skip`).

## Boundaries

- **Always:** chạy lint + test của package trước khi commit; làm trên `feature/HMA-<n>-*` từ `develop`; PR vào `develop`;
  cập nhật `.env.example` khi thêm biến; giữ CI khớp bảng lệnh ở trên và trong `CLAUDE.md`.
- **Ask first:** thêm dependency ngoài danh sách Tech Stack; đổi phiên bản major; sửa workflow CI hoặc ngưỡng coverage;
  thay đổi định dạng lỗi/quy ước API (ảnh hưởng mọi module).
- **Never:** commit `.env`/secret; push hoặc merge vào `main`; tắt/`skip` test hay hạ ngưỡng để CI xanh;
  thêm bảng nghiệp vụ hoặc auth vào module này.

## Success Criteria

1. Trên máy sạch có Docker, Python 3.12 + uv, Node 20, Flutter 3.24: làm theo `README.md` chạy được `db`, backend-api,
   ai-service, admin-web và app (emulator) trong ≤ 15 phút.
2. `GET :8000/health` và `GET :8001/health` trả `200` với `db: ok`; dừng container db → backend `/health` trả `503`.
3. Request gây lỗi validation trả `400` đúng envelope và có `request_id` trùng header `X-Request-ID`.
4. Log của request có header `Authorization` không chứa giá trị token (đã redact) — có test chứng minh.
5. Xóa một biến bắt buộc khỏi env → backend-api không khởi động và thông báo tên biến.
6. `uv run alembic upgrade head` rồi `downgrade base` chạy sạch trên DB rỗng.
7. Trang `/vi/health` và `/en/health` của admin-web hiển thị trạng thái backend bằng đúng ngôn ngữ.
8. App Flutter mở lên hiển thị màn chào vi/en và gọi được `/health` qua `ApiClient` (base URL từ `env/dev.json`).
9. Mở PR chỉ đổi `admin-web/**` → chỉ workflow `admin-web` + `security` chạy; PR chứa chuỗi giống API key → `security` đỏ.
10. Mọi lệnh lint/test/build trong mục Commands chạy xanh local và trong CI; coverage backend-api, ai-service ≥ 70%.
11. `README.md` có mục thiết lập branch protection cho `main`/`develop` (Tech Lead tự bật trên GitHub).

## Out of Scope (Deferred)

- Docker image production, deploy cloud, HTTPS, domain — Sprint 4 (roadmap D24).
- Playwright E2E cho admin-web — thêm khi có màn nghiệp vụ (sau `room-service`).
- Observability đầy đủ (Sentry, metrics, tracing) — chưa cần ở quy mô đồ án; cân nhắc trước khi chạy thử thực tế.
- Build iOS — ngoài phạm vi (giả định 6).
- Ký APK bằng key release — Sprint 4.

## Open Questions

1. **uv** cho Python (đề xuất) hay pip + `requirements.txt` quen thuộc hơn với nhóm?
2. Tên Jira project key thật là gì (đang giả định `HMA`)?
3. Repo GitHub đã tạo chưa, và tên chính xác (`HotelManage`?) — cần để cấu hình CI và branch protection.
4. Nhóm có ai đã quen Riverpod không? Nếu không, có thể dùng Provider/Bloc tùy kinh nghiệm.
