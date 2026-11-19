# Task List — V1

Kế hoạch: [tasks/plan.md](plan.md). Mỗi task `Tnn` ↔ Jira `HMA-nn` ↔ nhánh `feature/HMA-nn-<mo-ta>` ↔ PR vào `develop`.
Cỡ: **S** = 1–2 file chính · **M** = 3–5 file chính (chưa tính test/migration). Lane: BE / WEB / APP / AI / LEAD.

Lệnh kiểm tra dùng trong cột Verify:
- BE: `cd backend-api && uv run ruff check . && uv run pytest -q <path>`
- AI: `cd ai-service && uv run ruff check . && uv run pytest -q <path>`
- WEB: `cd admin-web && npm run lint && npm run typecheck && npm test -- <pattern> && npm run build`
- APP: `cd mobile-app && flutter analyze && flutter test <path>`

---

## Phase 1 — Foundation (D01) · spec: SPEC-foundation

- [x] **T01 · Monorepo skeleton** · D01 · LEAD · S · Deps: —
  - Accept: `docker-compose.yml` (postgres:16), `.gitignore` (env, service-account, google-services), `README.md` (setup + branch protection), `.github/pull_request_template.md`
  - Verify: `docker compose up -d db` chạy; `git check-ignore backend-api/.env` khớp
  - Files: `docker-compose.yml`, `.gitignore`, `README.md`, `.github/pull_request_template.md`

- [x] **T02 · backend-api skeleton** · D01 · BE · M · Deps: T01
  - Accept: `create_app` + `Settings` (thiếu biến → không start); envelope lỗi + 422→400 + `X-Request-ID`; log JSON redact; `/health` 200/503; Alembic revision nền (`pgcrypto`, `citext`, `unaccent`, `hotel_settings`)
  - Verify: BE `tests/` (SC 2–6 của foundation), coverage ≥ 70%
  - Files: `app/main.py`, `app/core/{config,errors,logging,request_id,db}.py`, `app/api/health.py`, `migrations/`, `tests/`

- [ ] **T03 · ai-service skeleton** · D01 · AI · M · Deps: T01
  - Accept: app + config + envelope lỗi; `LLMClient` base + `FakeLLMClient` + chọn adapter theo `LLM_PROVIDER`; `/health`
  - Verify: AI `tests/`
  - Files: `app/main.py`, `app/core/`, `app/llm/{base,fake}.py`, `tests/`

- [ ] **T04 · admin-web skeleton** · D01 · WEB · M · Deps: T01
  - Accept: Next.js 15 strict TS, Tailwind, next-intl vi/en; `api-client` parse envelope lỗi; `/[locale]/health` hiện trạng thái backend
  - Verify: WEB `api-client|i18n`
  - Files: `src/app/[locale]/`, `src/lib/api-client.ts`, `src/i18n/`, `messages/{vi,en}.json`, `tests/`

- [ ] **T05 · mobile-app skeleton** · D01 · APP · M · Deps: T01
  - Accept: Riverpod, go_router, dio `ApiClient` map lỗi → `AppException`, ARB vi/en, màn chào gọi `/health`, `env/*.example.json`
  - Verify: APP `test/`; `flutter run --dart-define-from-file=env/dev.json` lên emulator
  - Files: `lib/main.dart`, `lib/app/`, `lib/core/{api_client,config,errors}.dart`, `lib/l10n/`, `test/`

- [ ] **T06 · CI workflows** · D01 · AI · M · Deps: T02–T05
  - Accept: 4 workflow theo path filter (lệnh khớp `CLAUDE.md`) + `security.yml` gitleaks; backend dùng service postgres
  - Verify: PR chỉ đổi `admin-web/**` → chỉ `admin-web` + `security` chạy; PR có chuỗi giống API key → đỏ
  - Files: `.github/workflows/{backend-api,ai-service,admin-web,mobile-app,security}.yml`

### Checkpoint CP-A (cuối D01)
- [ ] CI xanh trên `develop`; 4 package chạy local theo README ≤ 15 phút
- [ ] Tech Lead bật branch protection `main`/`develop`

---

## Phase 2 — Staff auth (D02–D03) · spec: SPEC-staff-auth

- [x] **T07 · Staff model, security, rate limiter** · D02 · BE · M · Deps: T02
  - Accept: migration `staff`, `staff_refresh_token`, `rate_limit_bucket`; `security.py` (argon2id, JWT encode/decode, `typ`, `ver`); `core/rate_limit.py`
  - Verify: BE `tests/unit/staff_auth tests/unit/core`
  - Files: `modules/staff_auth/{models,security}.py`, `core/rate_limit.py`, migration

- [x] **T08 · Staff auth endpoints** · D02 · BE · M · Deps: T07
  - Accept: login/refresh (xoay vòng, phát hiện dùng lại)/logout/me/password; cookie đủ cờ, kiểm `Origin`; sai 5 lần → `429` + `Retry-After`; cùng thông báo cho sai email/mật khẩu
  - Verify: BE `tests/integration/staff_auth`
  - Files: `modules/staff_auth/{schemas,service,repository,router}.py`

- [x] **T09 · RBAC dependencies + route guard** · D03 · BE · S · Deps: T08
  - Accept: `current_staff`, `require_roles`; test quét router (endpoint thiếu phân quyền → đỏ); ma trận 3×3 `200/403`, token `typ=stay` → `401`
  - Verify: BE `tests/integration/test_route_guards.py tests/integration/staff_auth/test_rbac.py`
  - Files: `modules/staff_auth/deps.py`, `tests/integration/test_route_guards.py`

- [ ] **T10 · Staff CLI** · D03 · BE · S · Deps: T07
  - Accept: `create-staff`, `set-active` (tăng `token_version`), `reset-password` (prompt ẩn), `seed-dev` chỉ khi `APP_ENV=dev`
  - Verify: BE `tests/unit/test_cli.py`; chạy `uv run python -m app.cli seed-dev`
  - Files: `app/cli.py`

- [ ] **T11 · Web login + role areas** · D02–D03 · WEB · M · Deps: T04 (mock), T08
  - Accept: trang login; `AuthProvider` (token trong bộ nhớ, refresh khi tải trang/trước hạn, `401` → refresh 1 lần); 3 vùng theo vai trò + trang `403`; layout chung
  - Verify: WEB `auth`; thủ công SC 1, 6, 7 của staff-auth
  - Files: `src/app/[locale]/login/`, `src/app/[locale]/(staff)/layout.tsx`, `src/lib/auth/`, `tests/auth/`

### Checkpoint CP-B (cuối D03)
- [ ] 3 tài khoản seed đăng nhập Web đúng vùng; API sai vai trò `403`; route-guard xanh; coverage `staff_auth` ≥ 85%

---

## Phase 3 — Stay access (D03–D05) · spec: SPEC-stay-access

- [ ] **T12 · Room/stay models, codes, tokens** · D03 · BE (AI hỗ trợ) · M · Deps: T07
  - Accept: migration `room`, `stay`, `stay_session` (+ unique có điều kiện); `codes.py` (bảng 31 ký tự, `normalize_code`, HMAC pepper); `tokens.py` (`typ=stay`, secret riêng)
  - Verify: BE `tests/unit/stay_access`
  - Files: `modules/stay_access/{models,codes,tokens}.py`, migration

- [ ] **T13 · Rooms + check-in API** · D04 · BE · M · Deps: T09, T12
  - Accept: CRUD `/rooms`, `POST /stays` (khóa hàng, phòng không `VACANT` → `409`, mã thô trả một lần), `GET/PATCH /stays`, CLI `seed-rooms`
  - Verify: BE `tests/integration/stay_access/test_checkin.py` (gồm check-in đồng thời)
  - Files: `modules/stay_access/{schemas,service,repository,router_staff}.py`, `seeds/rooms.example.csv`

- [ ] **T14 · close_stay, reissue, checkout, hook** · D04 · BE · M · Deps: T13
  - Accept: `close_stay()` dùng chung; `events.register_on_stay_closed`; `reissue-code`, `checkout`, `mark-vacant`; revoke trong cùng transaction
  - Verify: BE `tests/integration/stay_access/test_close_stay.py`
  - Files: `modules/stay_access/{service,events,router_staff}.py`

- [ ] **T15 · Guest auth + current_stay** · D05 · BE · M · Deps: T14
  - Accept: `room-code`/`renew`/`logout`/`me`; `current_stay`, `current_active_stay`; rate limit IP/device; tối đa 6 session; **đủ test C5.1, C5.2**
  - Verify: BE `tests/integration/stay_access/test_guest_auth.py`; coverage `stay_access` ≥ 85%
  - Files: `modules/stay_access/{deps,router_guest}.py`

- [ ] **T16 · Web room board + check-in slip** · D04 · WEB · M · Deps: T11, T13
  - Accept: sơ đồ phòng theo màu/tầng; form check-in; phiếu mã + QR (`qrcode.react`) in K80/A6, đóng là mất mã
  - Verify: WEB `reception/checkin`
  - Files: `reception/rooms/`, `components/reception/{RoomBoard,CheckinForm,CheckinSlip}.tsx`

- [ ] **T17 · Web stay detail + room management** · D05 · WEB · M · Deps: T14, T16
  - Accept: gia hạn, sửa tiền phòng, cấp lại mã, check-out (hộp thoại xác nhận), đánh dấu đã dọn, thêm/sửa phòng
  - Verify: WEB `reception/stay`
  - Files: `reception/stays/[id]/`, `components/reception/`

- [ ] **T18 · App login (code/QR) + home** · D04–D05 · APP · M · Deps: T05, T15
  - Accept: nhập mã `XXXX-XXXX` + quét QR (`mobile_scanner`, đúng scheme); token + `device_id` trong secure storage; `401` → về màn chào; `429` hiện thời gian chờ; trang chủ
  - Verify: APP `test/stay_access`
  - Files: `lib/features/stay_access/`, `lib/features/home/home_screen.dart`

### Checkpoint CP-C = M1 (cuối D05)
- [ ] SC 1–7 của stay-access trên 2 điện thoại Android thật với backend staging/local
- [ ] Tech Lead review demo Sprint 1

---

## Phase 4 — MVP (D06–D14)

### notifications · spec: SPEC-notifications

- [ ] **T19 · Outbox + emit_status_changed** · D06 · AI→BE · M · Deps: T14
  - Accept: `notification_outbox`, cột `fcm_token`; `emit_status_changed` (outbox + `pg_notify`); worker `SKIP LOCKED`; `LogSender`/`FakePushSender`; mẫu vi/en; rollback → không có sự kiện
  - Verify: BE `tests/integration/notifications/test_outbox.py`
  - Files: `modules/notifications/{api,models,outbox_worker,senders}.py`, `templates/`, migration

- [ ] **T20 · FcmSender + fcm-token API** · D07 · AI→BE · M · Deps: T19
  - Accept: FCM HTTP v1 qua `google-auth`; xử lý `UNREGISTERED`/retry 2-10-30 s/`FAILED`; `PUT/DELETE /guest/me/fcm-token`; chụp token cho `STAY/CLOSED`
  - Verify: BE `tests/integration/notifications/test_fcm.py`
  - Files: `modules/notifications/{senders,router_guest}.py`, `stay_access/service.py` (chụp token)

- [ ] **T21 · SSE staff events + dev notify** · D07 · AI→BE · M · Deps: T19, T09
  - Accept: `/staff/events` lọc theo vai trò, ping 15 s, đóng khi token hết hạn; `/dev/notify-test` chỉ khi `APP_ENV=dev`; latency commit→SSE < 1 s
  - Verify: BE `tests/integration/notifications/test_sse.py`
  - Files: `modules/notifications/{sse,router_dev}.py`

- [ ] **T22 · Web realtime hook** · D06–D07 · WEB · M · Deps: T11 (T21 cho kiểm thử thật)
  - Accept: `useStaffEvents` (fetch stream, backoff, `onReconnect`); chấm kết nối; toast theo bộ phận; bật âm báo
  - Verify: WEB `realtime`
  - Files: `src/lib/realtime/`, `components/layout/{ConnectionIndicator,SoundToggle}.tsx`

- [ ] **T23 · App FCM** · D06–D08 · APP · M · Deps: T18, T20
  - Accept: Firebase init, xin quyền Android 13+, gửi token + `onTokenRefresh`; channel `requests`; foreground notification + làm mới provider; chạm → route `/requests/<type>/<id>`
  - Verify: APP `test/notifications`; thủ công SC 1–3 của notifications trên máy thật
  - Files: `lib/features/notifications/`, `android/` (cấu hình)

### room-service · spec: SPEC-room-service

- [ ] **T24 · Menu + status_history + settings** · D06 · BE · M · Deps: T15
  - Accept: migration menu, `status_history` dùng chung, cột `hotel_settings`; `GET /guest/menu` (shape = tool `get_available_menu`); CRUD menu `KITCHEN`; giờ phục vụ `RECEPTION`; `seed-menu`
  - Verify: BE `tests/integration/room_service/test_menu.py`
  - Files: `modules/room_service/{models,schemas,router_guest,router_staff}.py`, `modules/shared/status_history.py`, `seeds/menu.example.csv`

- [ ] **T25 · Create order (guest)** · D07 · BE · M · Deps: T24
  - Accept: `POST /guest/orders` đủ bảng quy tắc (chụp giá, `ITEM_UNAVAILABLE`, `KITCHEN_CLOSED`, 5 PENDING, `Idempotency-Key`, trường lạ `400`); list/detail/cancel của khách; `403` stay khác
  - Verify: BE `tests/integration/room_service/test_create_order.py`
  - Files: `modules/room_service/{service,repository,router_guest}.py`

- [ ] **T26 · Order state machine + kitchen API** · D07–D08 · BE · M · Deps: T25, T19
  - Accept: `state.py` + `transition`; `/orders/{id}/transition|cancel` có `version`; `emit_status_changed`; test bảng 36 cặp × 4 actor (C5.4)
  - Verify: BE `tests/unit/room_service tests/integration/room_service/test_transitions.py`
  - Files: `modules/room_service/{state,service,router_staff}.py`, `notifications/templates/`

- [ ] **T27 · Order hooks, overdue, food total** · D08 · BE · S · Deps: T26
  - Accept: `on_stay_closed` hủy `PENDING/CONFIRMED`; job mỗi phút nhắc quá 10 phút một lần; `get_stay_food_total`, `count_open_orders`
  - Verify: BE `tests/integration/room_service/test_hooks.py`; coverage `room_service` ≥ 80%
  - Files: `modules/room_service/{api,jobs}.py`, migration (`overdue_notified_at`)

- [ ] **T28 · Web kitchen board** · D07–D08 · WEB · M · Deps: T22, T26
  - Accept: cột trạng thái, nút một chạm, từ chối có lý do, chọn thời gian dự kiến, viền đỏ quá hạn, cập nhật SSE
  - Verify: WEB `kitchen`
  - Files: `kitchen/page.tsx`, `components/kitchen/{OrderBoard,OrderCard,RejectDialog}.tsx`

- [ ] **T29 · Web menu mgmt + reception orders** · D08–D09 · WEB · M · Deps: T24, T28
  - Accept: `/kitchen/menu` (công tắc còn món, sửa, lưu trữ, tạm ngưng); `/reception/orders` (lọc, chi tiết, hủy có lý do); `/reception/settings` giờ phục vụ
  - Verify: WEB `kitchen/menu|reception/orders`
  - Files: `kitchen/menu/`, `reception/orders/`, `reception/settings/`, `components/kitchen/MenuTable.tsx`

- [ ] **T30 · App menu + cart + place order** · D07–D08 · APP · M · Deps: T18, T25
  - Accept: tab nhóm + tìm kiếm, "Tạm hết", băng ngoài giờ; giỏ theo `stay_id`; `Idempotency-Key` một lần mỗi lần bấm; tổng từ response; xử lý `ITEM_UNAVAILABLE`
  - Verify: APP `test/room_service`
  - Files: `lib/features/room_service/{menu_screen,cart_controller,room_service_repository}.dart`

- [ ] **T31 · App order list/detail** · D09 · APP · S · Deps: T30, T23
  - Accept: danh sách + chi tiết có thanh tiến trình, hủy khi `PENDING`; route push; tự làm mới 15 s; thẻ "Đang xử lý" ở trang chủ
  - Verify: APP `test/room_service`
  - Files: `lib/features/room_service/{order_list_screen,order_detail_screen}.dart`, `home_screen.dart`

### housekeeping · spec: SPEC-housekeeping

- [ ] **T32 · Housekeeping requests (guest) + DND** · D08 · BE · M · Deps: T24 (status_history), T15
  - Accept: migration; `POST/GET/cancel /guest/housekeeping-requests` đủ bảng quy tắc (1 CLEANING mở, 3 AMENITY, `TURNOVER` → `400`, idempotency); `PUT /guest/me/do-not-disturb`
  - Verify: BE `tests/integration/housekeeping/test_guest.py`
  - Files: `modules/housekeeping/{models,schemas,service,repository,router_guest}.py`, migration

- [ ] **T33 · Housekeeping state machine + staff API** · D09 · BE · M · Deps: T32, T19
  - Accept: `transition` với quy tắc "chỉ người được gán", trả lại việc, `version`; staff list (thứ tự ưu tiên)/detail/transition/cancel; emit + mẫu; nhắc quá 15 phút
  - Verify: BE `tests/unit/housekeeping tests/integration/housekeeping/test_staff.py`
  - Files: `modules/housekeeping/{state,router_staff,jobs}.py`, `notifications/templates/`

- [ ] **T34 · TURNOVER + domain-rules update** · D10 · BE · S · Deps: T33, T14
  - Accept: `on_stay_closed` hủy yêu cầu mở + tạo `TURNOVER`; `TURNOVER DONE` → phòng `VACANT`; `mark-vacant` hủy `TURNOVER`; **sửa `docs/domain-rules.md` §2, §4**
  - Verify: BE `tests/integration/housekeeping/test_turnover.py`; coverage `housekeeping` ≥ 80%
  - Files: `modules/housekeeping/hooks.py`, `stay_access/service.py`, `docs/domain-rules.md`

- [ ] **T35 · Web housekeeping board + reception view** · D09–D10 · WEB · M · Deps: T22, T33
  - Accept: tab "Việc chờ"/"Việc của tôi", nút theo trạng thái + người gán, nhãn DND, một cột ở 360px; `/reception/housekeeping` có cột người làm + hủy; biểu tượng DND/đang dọn trên sơ đồ phòng
  - Verify: WEB `housekeeping`
  - Files: `housekeeping/page.tsx`, `reception/housekeeping/`, `components/housekeeping/`, `RoomBoard.tsx`

- [ ] **T36 · App housekeeping** · D09–D10 · APP · M · Deps: T23, T32
  - Accept: nút dọn phòng (ASAP/khung giờ), bộ chọn đồ dùng 1–5 ("Khác" bắt buộc ghi chú), công tắc DND, danh sách/chi tiết, hủy khi `REQUESTED`
  - Verify: APP `test/housekeeping`
  - Files: `lib/features/housekeeping/`

### Checkpoint CP-D (cuối D10)
- [ ] SC của room-service (1–8) và housekeeping (1–7) chạy end-to-end với push thật + SSE
- [ ] Staging dựng được bằng docker compose (chuẩn bị cho T56)

### concierge-guide · spec: SPEC-concierge-guide

- [ ] **T37 · KB data + search + staff CRUD** · D07–D08 · AI (BE code) · M · Deps: T15, T09
  - Accept: migration `kb_entry`, `nearby_place` (tsvector unaccent); `GET /guest/kb/search` (shape tool §4.1, fallback theo topic); CRUD `RECEPTION`; `PATCH /settings/hotel`; `seed-kb`
  - Verify: BE `tests/integration/concierge_data/test_kb.py`
  - Files: `modules/concierge_data/{models,search,router_guest,router_staff}.py`, `seeds/kb.example.yaml`

- [ ] **T38 · Chat history + quota** · D09 · AI (BE code) · S · Deps: T37
  - Accept: `chat_message`; `GET/POST /guest/chat/messages`; `POST /guest/chat/quota` (10/phút, 100/ngày); `GET /guest/hotel-info`; hook xóa khi đóng stay
  - Verify: BE `tests/integration/concierge_data/test_chat.py`
  - Files: `modules/concierge_data/{models,router_guest,hooks}.py`

- [ ] **T39 · Backend client + LLM adapters** · D09–D10 · AI · M · Deps: T03
  - Accept: `backend_client` (token khách, timeout 3 s, map lỗi); adapter Gemini + OpenAI (tool calling + structured output) kiểm bằng payload mẫu
  - Verify: AI `tests/unit/llm tests/unit/backend_client`
  - Files: `app/core/backend_client.py`, `app/llm/{gemini,openai}.py`

- [ ] **T40 · /chat orchestrator + guide tool + grounding** · D11–D12 · AI · M · Deps: T38, T39
  - Accept: `POST /chat` (401/429/503/504, `client_message_id`, `debug` chỉ dev/test); tool `get_hotel_info_and_guide`; `suggested_actions`; grounding 3 bước
  - Verify: AI `tests/unit/concierge tests/integration`
  - Files: `app/api/chat.py`, `app/concierge/{orchestrator,grounding}.py`, `tools/guide.py`, `prompts/concierge.md`

- [ ] **T41 · Web knowledge management** · D11–D12 · WEB · M · Deps: T37
  - Accept: tab KB/địa điểm, form song ngữ, công tắc xuất bản, ô "Thử hỏi" (không gọi LLM); thông tin khách sạn + bật/tắt chatbot ở settings
  - Verify: WEB `knowledge`
  - Files: `reception/knowledge/`, `reception/settings/`

- [ ] **T42 · App chat screen** · D11–D13 · APP · M · Deps: T40 (mock trước)
  - Accept: bong bóng + markdown giới hạn, gợi ý nhanh, nút `suggested_actions`, link chỉ tên miền cho phép, `429/503/504` → câu dự phòng, retry cùng `client_message_id`
  - Verify: APP `test/concierge`
  - Files: `lib/features/concierge/{chat_screen,chat_controller,suggested_action_button}.dart`

- [ ] **T43 · Guide eval set** · D13 · AI · S · Deps: T40
  - Accept: `guide_cases.yaml` ≥ 20 câu (vi/en/ko, ngoài KB, câu dẫn bịa); ≥ 95% đúng, 0 bịa; p95 < 8 s
  - Verify: `uv run pytest -q -m live tests/eval/test_guide.py`; `/eval-bot` S1
  - Files: `tests/eval/{guide_cases.yaml,test_guide.py}`

### Checkpoint CP-E = M2 (D14)
- [ ] Kiểm thử tích hợp MVP cả nhóm: 6 chức năng MVP trên staging, push ≤ 5 s
- [ ] Coverage backend ≥ 70%, ai-service ≥ 70%; `/eval-bot` S1 PASS
- [ ] Tech Lead review demo Sprint 2

---

## Phase 5 — Mức Tốt (D15–D21)

### express-checkout · spec: SPEC-express-checkout

- [ ] **T44 · Checkout models + build_bill** · D15 · BE · M · Deps: T27, T34
  - Accept: migration `checkout_request`, `stay_charge`; `build_bill` (chỉ đơn COMPLETED, extras/discount, tổng âm → lỗi, `open_orders`); `GET /stays/{id}/bill`; charges API + `BILL_LOCKED`
  - Verify: BE `tests/unit/express_checkout tests/integration/express_checkout/test_bill.py`
  - Files: `modules/express_checkout/{models,billing,router_staff}.py`, migration

- [ ] **T45 · Checkout flow + domain-rules update** · D16 · BE · M · Deps: T44
  - Accept: guest preview/create/current; `transition` + verify/complete/reject (snapshot, `OPEN_ORDERS_EXIST`, `payment_method`); complete gọi `close_stay`; quầy `409 CHECKOUT_REQUEST_OPEN`; `401` body `STAY_CLOSED`; push/nhắc; **sửa `docs/domain-rules.md` §5**
  - Verify: BE `tests/integration/express_checkout/`; coverage ≥ 85%
  - Files: `modules/express_checkout/{state,service,router_guest,router_staff,jobs}.py`, `stay_access/deps.py`, `docs/domain-rules.md`

- [ ] **T46 · Web checkout desk** · D16–D17 · WEB · M · Deps: T45
  - Accept: hàng đợi, bảng đối soát (phụ phí/giảm giá, sửa tiền phòng), chốt khóa khi còn đơn mở, in K80, chọn thanh toán, hoàn tất/từ chối; nút "Xem hóa đơn" ở stay detail
  - Verify: WEB `checkout`
  - Files: `reception/checkout/`, `components/checkout/{BillTable,ChargeForm,PrintableBill}.tsx`

- [ ] **T47 · App express checkout** · D16–D17 · APP · M · Deps: T45
  - Accept: màn tạm tính + sao + xác nhận; màn theo dõi + hóa đơn snapshot + lý do từ chối; khóa đặt món/dọn phòng khi `CHECKOUT_PENDING`; `401 STAY_CLOSED` → lời cảm ơn
  - Verify: APP `test/express_checkout`
  - Files: `lib/features/express_checkout/`, `home_screen.dart`, `core/api_client.dart`

### concierge-actions · spec: SPEC-concierge-actions

- [ ] **T48 · Order preview + dev stays seed** · D15 · BE · S · Deps: T25
  - Accept: `POST /guest/orders/preview` dùng chung hàm kiểm tra, không ghi DB, tổng = tạo thật; CLI `seed-dev-stays` trả token stay A/B (chỉ dev)
  - Verify: BE `tests/integration/room_service/test_preview.py`
  - Files: `modules/room_service/router_guest.py`, `app/cli.py`

- [ ] **T49 · Read tools + tool flags** · D15–D17 · AI · M · Deps: T40, T48
  - Accept: `get_available_menu`, `get_my_requests`; cờ `write`/`requires_confirmation`; lọc tool khi `CHECKOUT_PENDING`; tham số lạ → `VALIDATION_ERROR` không gọi backend; map lỗi backend
  - Verify: AI `tests/unit/concierge_actions tests/integration/concierge_actions/test_read_tools.py`
  - Files: `concierge/tools/{menu,my_requests}.py`, `concierge/orchestrator.py`

- [ ] **T50 · Confirmation gate + write tools** · D17–D19 · AI · M · Deps: T49, T45, T33
  - Accept: `pending_action` ký HMAC, hash payload, hết hạn 10 phút, phân loại xác nhận, `confirm_action_id`; `create_room_service_order`, `request_express_checkout` qua cổng; `request_housekeeping` trực tiếp; `Idempotency-Key = pending_action.id`
  - Verify: AI `tests/integration/concierge_actions/test_confirmation.py`; coverage `confirmation.py` ≥ 95%
  - Files: `concierge/confirmation.py`, `tools/{order,checkout,housekeeping}.py`, `summary_templates/`, `api/chat.py`

- [ ] **T51 · Guards + full prompt** · D19 · AI · S · Deps: T50
  - Accept: system prompt đầy đủ; canary + chặn trùng prompt; giới hạn 4 lượt tool / 1 tool ghi; grounding mở rộng nguồn
  - Verify: AI `tests/unit/concierge_actions/test_guards.py`; coverage `guards.py` ≥ 95%
  - Files: `concierge/guards.py`, `prompts/concierge.md`, `concierge/grounding.py`

- [ ] **T52 · App confirmation card** · D18–D19 · APP · S · Deps: T42, T50
  - Accept: thẻ tóm tắt với "Xác nhận"/"Sửa lại", hết hạn → khóa; "Xem đơn"/"Xem yêu cầu"; ghi chú khi `CHECKOUT_PENDING`
  - Verify: APP `test/concierge`
  - Files: `lib/features/concierge/confirmation_card.dart`, `chat_screen.dart`

- [ ] **T53 · Eval S1–S4 + eval-bot sync** · D19–D20 · AI · M · Deps: T50, T51
  - Accept: `tests/eval/s1..s4` marker `live`+`eval_bot`, fixture `seed-dev-stays`; sửa `.claude/commands/eval-bot.md` (lệnh marker, `/api/v1/guest/orders`, `debug.tool_calls`); S2–S4 100% × 3 lần
  - Verify: `uv run pytest -q -m "live and eval_bot" tests/eval`; `/eval-bot`
  - Files: `ai-service/tests/eval/`, `.claude/commands/eval-bot.md`

### Checkpoint CP-F = M3 (D21)
- [ ] SC của express-checkout và concierge-actions trên staging; `/eval-bot` PASS 4 kịch bản × 3 lần
- [ ] Rà soát vi/en toàn bộ UI; Tech Lead review demo Sprint 3

---

## Phase 6 — Release & field trial (D22–D27) · roadmap Sprint 4

- [ ] **T54 · Security test pass** · D22–D23 · BE + AI · M · Deps: CP-F
  - Accept: báo cáo `docs/security-report.md`: dò mã, IDOR, RBAC, JWT revoke, OWASP API Top 10, `pip-audit`/`npm audit`, gitleaks lịch sử; không còn lỗi High (sửa trên `release/*`)
  - Verify: báo cáo + test hồi quy cho mỗi lỗi tìm thấy
  - Files: `docs/security-report.md`, test liên quan

- [ ] **T55 · Load test** · D23 · WEB · S · Deps: CP-F
  - Accept: kịch bản k6 50 khách đồng thời (đăng nhập, menu, đặt món, theo dõi); không 5xx; p95 API < 500 ms
  - Verify: `k6 run loadtest/guest_flow.js` + kết quả lưu `docs/load-test.md`
  - Files: `loadtest/guest_flow.js`, `docs/load-test.md`

- [ ] **T56 · Production images + deploy** · D10 (staging) → D24 (prod) · BE · M · Deps: CP-D
  - Accept: Dockerfile prod cho backend/ai-service/web, HTTPS, Postgres managed, secrets qua biến môi trường của nền tảng, worker chạy cùng backend; hướng dẫn `docs/deploy.md`
  - Verify: `/health` prod 200; SC end-to-end trên prod với APK
  - Files: `*/Dockerfile`, `docker-compose.prod.yml` hoặc cấu hình nền tảng, `docs/deploy.md`

- [ ] **T57 · Signed release APK** · D24 · APP · S · Deps: CP-F
  - Accept: keystore release (không commit; CI dùng secret), `env/prod.json` trỏ prod, `flutter build apk --release` cài được trên 3 máy Android khác nhau
  - Verify: cài APK, đăng nhập bằng mã prod
  - Files: `android/app/build.gradle`, `.github/workflows/mobile-app.yml`

- [ ] **T58 · Release to main** · D22 → D24 · LEAD · S · Deps: T54–T57
  - Accept: `release/1.0.0` từ `develop` ở D22; PR `release/1.0.0 → main` **Tech Lead merge**; tag `v1.0.0`; merge ngược về `develop`
  - Verify: `main` = bản deploy; tag tồn tại
  - Files: `CHANGELOG.md`

- [ ] **T59 · Field trial setup** · D25–D26 · AI + cả nhóm · M · Deps: T58
  - Accept: nạp phòng/menu/KB thật của đơn vị; tạo tài khoản nhân viên; hướng dẫn sử dụng 1 trang cho mỗi vai trò; biên bản thử nghiệm + danh sách phản hồi
  - Verify: đơn vị xác nhận biên bản
  - Files: `docs/user-guide-{reception,kitchen,housekeeping,guest}.md`, `docs/field-trial-report.md`

- [ ] **T60 · Final docs & defense pack** · D27 · LEAD · S · Deps: T59
  - Accept: báo cáo tổng kết, video demo, slide bảo vệ; hotfix (nếu có) đã qua `hotfix/* → main`
  - Verify: Tech Lead duyệt hồ sơ
  - Files: `docs/final-report.md`

### Checkpoint CP-G = M4 (D27)
- [ ] APK + Web + Backend đã deploy, chạy thử tại đơn vị; `main` tag `v1.0.0`; hồ sơ đồ án hoàn chỉnh
