# Spec: stay-access — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: mã 8 ký tự, ân hạn 6 giờ, tối đa 6 thiết bị, CSS in ưu tiên K80 (vẫn in được A6); duyệt dependency `qrcode.react`, `mobile_scanner`
Module id: `stay-access` · Phụ thuộc: `staff-auth` · Mức: MVP · Sprint 1 (D02–D05) · Map: [capability-map.md](capability-map.md)
Nguồn quy tắc: `CLAUDE.md` (Luật chống lộ mã phòng), `CONSTRAINTS.md` C4/C5.1/C5.2, `docs/domain-rules.md` §1–2.

## Objective

Khách đăng nhập app bằng **mã phiên ngẫu nhiên hoặc QR** do Lễ tân cấp khi check-in. Mã chỉ dùng được trong đúng kỳ lưu trú
và bị vô hiệu ngay khi check-out. Mọi module phía khách lấy `stay_id`/`room_id` từ một dependency duy nhất (`current_stay`),
không bao giờ từ request.

**Người dùng:** Lễ tân (check-in/out, cấp mã); khách lưu trú (đăng nhập app).

**User stories**
- Là Lễ tân, tôi chọn một phòng trống, nhập tên khách, ngày trả phòng dự kiến và tiền phòng, bấm Check-in rồi in hoặc đưa phiếu có mã + QR cho khách.
- Là khách, tôi quét QR hoặc gõ mã 8 ký tự là vào được app, không cần tạo tài khoản.
- Là khách đi cùng gia đình, mỗi người dùng điện thoại riêng với cùng một mã.
- Là Lễ tân, khi khách báo lộ mã, tôi bấm "Cấp lại mã": mã cũ và mọi thiết bị đang đăng nhập bị đăng xuất ngay.
- Là Lễ tân, khi khách trả phòng tại quầy, tôi bấm Check-out: app của khách mất quyền truy cập ngay và phòng chuyển sang chờ dọn.
- Là kẻ tấn công, tôi không thể dò mã (rate limit), không thể dùng mã của kỳ lưu trú đã kết thúc, và không thể đổi `room_id` trong request để truy cập phòng khác.

**Không thuộc module này:** trả phòng nhanh từ app và đối soát hóa đơn (`express-checkout`), đăng ký `fcm_token` (`notifications`),
hủy đơn khi stay đóng (`room-service`/`housekeeping` tự đăng ký hook).

## Tech Stack

Kế thừa `foundation` + `staff-auth`. Dependency mới (cần duyệt):

| Package | Dependency | Lý do |
|---|---|---|
| admin-web | `qrcode.react` | Vẽ QR trên phiếu check-in |
| mobile-app | `mobile_scanner` | Quét QR bằng camera |

Backend dùng `secrets` (stdlib), `hmac`, `pyjwt` (đã duyệt).

## Thiết kế

### Dữ liệu (migration Alembic)

```
room
  id            uuid PK
  number        text UNIQUE NOT NULL        -- "101"
  floor         smallint NULL
  room_type     text NULL                   -- "Deluxe Double"
  status        room_status NOT NULL DEFAULT 'VACANT'   -- VACANT | OCCUPIED | CLEANING
  is_active     boolean NOT NULL DEFAULT true           -- phòng ngừng kinh doanh
  created_at, updated_at

stay
  id                    uuid PK
  room_id               uuid FK → room NOT NULL
  guest_name            text NULL           -- tối thiểu dữ liệu cá nhân; không lưu CCCD/hộ chiếu
  guest_count           smallint NOT NULL DEFAULT 1
  checkin_at            timestamptz NOT NULL
  expected_checkout_at  timestamptz NOT NULL
  room_charge_vnd       bigint NOT NULL     -- tiền phòng nhập tay (giả định 9)
  note                  text NULL
  status                stay_status NOT NULL  -- ACTIVE | CHECKOUT_PENDING | CLOSED
  room_code_lookup      text NULL           -- HMAC-SHA256(code, ROOM_CODE_PEPPER), NULL khi CLOSED
  code_issued_at        timestamptz NOT NULL
  closed_at             timestamptz NULL
  checked_in_by         uuid FK → staff
  closed_by             uuid FK → staff NULL
  UNIQUE (room_code_lookup) WHERE room_code_lookup IS NOT NULL
  UNIQUE (room_id) WHERE status <> 'CLOSED'      -- một phòng chỉ có một stay đang mở

stay_session
  id            uuid PK                     -- = jti trong token
  stay_id       uuid FK → stay NOT NULL
  device_id     text NOT NULL               -- UUID app tự sinh, lưu trong secure storage
  lang          text NOT NULL DEFAULT 'vi'
  created_at, last_seen_at timestamptz
  revoked_at    timestamptz NULL
  revoke_reason text NULL                   -- CHECKOUT | REISSUE | LOGOUT | EXPIRED
```

### Mã phiên (room code)

- **Sinh:** 8 ký tự từ bảng 31 ký tự không nhập nhằng `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (bỏ `0 O 1 I L`) bằng `secrets.choice`
  → khoảng 8,5 × 10¹¹ khả năng. Hiển thị dạng `XXXX-XXXX`; khi nhập, bỏ dấu gạch/khoảng trắng và tự viết hoa.
- **Lưu trữ:** chỉ lưu `room_code_lookup = HMAC-SHA256(code_chuẩn_hóa, ROOM_CODE_PEPPER)` để tra cứu; **không lưu mã thô**.
  Mã thô chỉ trả về **một lần** trong response check-in/cấp lại mã.
- **QR:** nội dung `hotelapp://login?code=<CODE>`. App chỉ chấp nhận đúng scheme này; QR khác → báo "QR không hợp lệ".
- **Hiệu lực:** mã đăng nhập được khi `stay.status ∈ {ACTIVE, CHECKOUT_PENDING}` **và** `now ≤ expected_checkout_at + 6 giờ`.
  Hết hạn mà Lễ tân chưa check-out → đăng nhập trả `401`; Lễ tân gia hạn được.

### Token của khách

JWT HS256, secret `STAY_JWT_SECRET` (khác `STAFF_JWT_SECRET`):

```json
{ "typ": "stay", "jti": "<stay_session.id>", "stay_id": "...", "room_id": "...", "iat": 0, "exp": "<expected_checkout_at + 6h>" }
```

- Không có refresh token. App gọi `POST /guest/auth/renew` để lấy token mới khi stay được gia hạn hoặc khi token còn dưới 24 giờ.
- **Mỗi request** khách: kiểm tra chữ ký, `typ`="stay", `exp`; tra DB `stay_session` chưa revoke và `stay.status ≠ CLOSED`;
  cập nhật `last_seen_at` (tối đa một lần mỗi phút). Bất kỳ điều kiện nào sai → `401 UNAUTHORIZED`.
- Token lưu trong `flutter_secure_storage`, không lưu ở SharedPreferences.

### Dependency dùng chung

```python
# backend-api/app/modules/stay_access/deps.py
@dataclass(frozen=True)
class StayContext:
    stay_id: UUID
    room_id: UUID
    session_id: UUID
    status: StayStatus
    lang: str

async def current_stay(...) -> StayContext: ...          # đọc: cho phép ACTIVE và CHECKOUT_PENDING

async def current_active_stay(ctx: StayContext = Depends(current_stay)) -> StayContext:
    if ctx.status is not StayStatus.ACTIVE:
        raise Conflict("STAY_CHECKOUT_PENDING", "Yêu cầu trả phòng đang được xử lý")
    return ctx                                             # ghi: chỉ ACTIVE
```

- Schema request của mọi endpoint khách đặt `extra="forbid"`: body có `room_id`/`stay_id` → `400 VALIDATION_ERROR` (C4.1).
- Truy cập tài nguyên thuộc stay khác (ví dụ `GET /guest/orders/{id}` của người khác) → `403 FORBIDDEN`. Mọi repository phía khách lọc theo `ctx.stay_id`.

### Hook khi đóng stay

```python
# stay_access/events.py — module khác đăng ký, stay-access không import ngược module nghiệp vụ
register_on_stay_closed(handler: Callable[[AsyncSession, UUID], Awaitable[None]])
```

Đóng stay chạy trong **một transaction**: `stay.status = CLOSED`, xóa `room_code_lookup`, revoke mọi `stay_session`
(`revoke_reason = CHECKOUT`), `room.status = CLEANING`, gọi các handler đã đăng ký.

### Rate limit đăng nhập (C4.3)

Dùng `app/core/rate_limit.py` của `staff-auth`:

| Khóa | Ngưỡng | Hậu quả |
|---|---|---|
| IP | 5 request / phút (cả đúng lẫn sai) | `429 RATE_LIMITED` + `Retry-After` |
| IP | 10 lần sai / giờ | Khóa 15 phút |
| `device_id` | 10 lần sai / giờ | Khóa 15 phút |
| Toàn hệ thống | > 100 lần sai / giờ | Log cảnh báo `room_code_bruteforce_suspected` (không chặn) |

Sai mã, mã đã đóng hoặc hết hạn đều trả cùng `401` và cùng thông báo "Mã phòng không hợp lệ hoặc đã hết hạn".

### API

**Nhân viên** (`/api/v1`, tất cả yêu cầu `require_roles(RECEPTION)`):

| Method | Path | Mô tả |
|---|---|---|
| GET | `/rooms` | Danh sách phòng + trạng thái + stay đang mở (nếu có) |
| POST | `/rooms` · PATCH `/rooms/{id}` | Thêm/sửa phòng (số, tầng, loại, `is_active`) |
| POST | `/rooms/{id}/mark-vacant` | `CLEANING → VACANT` thủ công (Buồng phòng làm tự động khi có module `housekeeping`) |
| POST | `/stays` | Check-in `{room_id, guest_name?, guest_count, expected_checkout_at, room_charge_vnd, note?}` → `201 {stay, room_code, qr_payload}`. Phòng không `VACANT` → `409` |
| GET | `/stays?status=ACTIVE` · `/stays/{id}` | Xem stay (không bao giờ trả mã thô) |
| PATCH | `/stays/{id}` | Gia hạn `expected_checkout_at`, sửa `room_charge_vnd`, `guest_name`, `note` |
| POST | `/stays/{id}/reissue-code` | Sinh mã mới, revoke mọi session (`REISSUE`) → `200 {room_code, qr_payload}` |
| POST | `/stays/{id}/checkout` | Check-out tại quầy → đóng stay như trên → `200` |

**Khách** (`/api/v1/guest`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| POST | `/auth/room-code` | public, có rate limit | `{code, device_id, lang}` → `200 {access_token, expires_at, stay:{room_number, guest_name, expected_checkout_at, status}}`. Tối đa 6 session đang hoạt động mỗi stay; vượt → `409 TOO_MANY_DEVICES` |
| POST | `/auth/renew` | `current_stay` | Token mới với `exp` theo `expected_checkout_at` hiện tại |
| POST | `/auth/logout` | `current_stay` | Revoke session hiện tại (`LOGOUT`) → `204` |
| GET | `/me` | `current_stay` | Thông tin stay của chính khách |

### admin-web (vùng `/[locale]/reception`)

- **Sơ đồ phòng:** lưới phòng tô màu theo trạng thái (`VACANT` / `OCCUPIED` / `CLEANING`), lọc theo tầng.
- **Check-in:** chọn phòng trống → form → hiện **phiếu check-in** (số phòng, tên khách, mã `XXXX-XXXX`, QR, hướng dẫn tải APK, ngày trả phòng).
  Có nút In (CSS in khổ A6/K80). Đóng phiếu thì không xem lại mã được nữa; muốn có mã mới thì dùng "Cấp lại mã".
- **Chi tiết stay:** gia hạn, sửa tiền phòng, cấp lại mã (có hộp thoại xác nhận nói rõ mọi thiết bị sẽ bị đăng xuất), check-out (có xác nhận).
- **Phòng chờ dọn:** nút "Đánh dấu đã dọn" (`mark-vacant`).
- **Quản lý phòng:** thêm/sửa phòng.

### mobile-app

- **Màn chào:** chọn ngôn ngữ vi/en, nút "Quét QR" và ô nhập mã có định dạng `XXXX-XXXX` (tự viết hoa, bỏ ký tự ngoài bảng).
- **Đăng nhập:** gọi `/guest/auth/room-code`, lưu token + `device_id` vào secure storage. Hiển thị lỗi `401`/`409`/`429` bằng chuỗi i18n,
  `429` hiện thời gian chờ từ `Retry-After`.
- **Khởi động app:** có token → gọi `/guest/me`; `401` → xóa token và quay về màn chào với thông báo
  "Phiên lưu trú đã kết thúc hoặc mã đã được cấp lại. Vui lòng liên hệ Lễ tân."
- **Trang chủ:** chào tên khách, số phòng, ngày trả phòng; nút đăng xuất. Các ô chức năng (đặt món, dọn phòng, chat) do module sau thêm vào.
- `ApiClient` gặp `401` ở bất kỳ request nào → xử lý như trên.

## Commands

Kế thừa `foundation`. Bổ sung:

```bash
cd backend-api
uv run python -m app.cli seed-rooms --from-file seeds/rooms.example.csv   # nạp danh sách phòng
uv run pytest -q tests/integration/stay_access
cd ../mobile-app && flutter test test/stay_access
```

## Project Structure

```
backend-api/app/modules/stay_access/
  models.py  schemas.py  service.py  repository.py  router_staff.py  router_guest.py
  deps.py  codes.py (sinh/chuẩn hóa/HMAC mã)  tokens.py  events.py
backend-api/migrations/versions/xxxx_stay_access.py
backend-api/seeds/rooms.example.csv
backend-api/tests/unit/stay_access/  tests/integration/stay_access/
admin-web/src/app/[locale]/(staff)/reception/rooms/  stays/[id]/
admin-web/src/components/reception/  CheckinForm.tsx  CheckinSlip.tsx  RoomBoard.tsx
mobile-app/lib/features/stay_access/  welcome_screen.dart  code_input.dart  qr_scan_screen.dart  stay_repository.dart  session_controller.dart
mobile-app/lib/features/home/home_screen.dart
mobile-app/test/stay_access/
```

## Code Style

Theo `foundation`. Riêng module này:
- Mọi so sánh mã/hash dùng `hmac.compare_digest`. Chuẩn hóa mã (`strip`, bỏ `-`/khoảng trắng, `upper`) ở **một** hàm `normalize_code`.
- Không bao giờ đưa mã thô vào log, exception message hay `status_history`.
- Thao tác đổi trạng thái stay/room chạy trong transaction và khóa hàng (`SELECT ... FOR UPDATE`) để tránh check-in hai lần cùng một phòng.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | `generate_code` chỉ dùng ký tự trong bảng, đủ 8 ký tự; `normalize_code` xử lý chữ thường/gạch/khoảng trắng; HMAC ổn định theo pepper; encode/decode token, sai `typ` → lỗi |
| Integration — **C5.1** | Mã không tồn tại (chưa check-in) → `401`; mã của stay đã check-out → `401`; mã sau khi hết `expected_checkout_at + 6h` → `401`; mã cũ sau khi cấp lại → `401` |
| Integration — **C5.1** | Token hợp lệ trước check-out → sau check-out `401` ngay ở request kế tiếp; tương tự sau cấp lại mã và sau logout |
| Integration — **C5.1** | Token stay A đọc tài nguyên của stay B → `403`; body chứa `room_id` → `400` |
| Integration — **C5.2** | 6 request/phút từ cùng IP → `429` có `Retry-After`; 10 lần sai/giờ theo `device_id` → khóa 15 phút |
| Integration | Check-in phòng không `VACANT` → `409`; hai check-in đồng thời cùng phòng → một `201`, một `409`; check-out chuyển phòng sang `CLEANING` và gọi hook đã đăng ký |
| Integration | Session thứ 7 → `409 TOO_MANY_DEVICES`; stay `CHECKOUT_PENDING` đăng nhập được, endpoint dùng `current_active_stay` trả `409` |
| Integration — RBAC | `KITCHEN`/`HOUSEKEEPING` gọi endpoint check-in/out → `403`; token khách gọi endpoint nhân viên → `401` |
| Integration | Không response nào của `GET /stays*` chứa mã thô; log của request đăng nhập không chứa mã |
| admin-web | Phiếu check-in hiển thị mã + QR đúng `qr_payload`; hộp thoại xác nhận cấp lại mã/check-out |
| mobile-app | Ô nhập mã chuẩn hóa đúng; QR sai scheme bị từ chối; `401` xóa token và về màn chào; `429` hiện thời gian chờ |

Coverage `app/modules/stay_access` ≥ 85%.

## Boundaries

- **Always:** lấy `stay_id`/`room_id` từ `current_stay`; `extra="forbid"` cho schema phía khách; mã thô chỉ trả một lần; revoke session trong cùng transaction với đóng stay.
- **Ask first:** đổi độ dài/bảng ký tự của mã, thời gian ân hạn 6 giờ, ngưỡng rate limit, số thiết bị tối đa; thêm trường dữ liệu cá nhân của khách.
- **Never:** dùng số phòng làm mã đăng nhập; lưu hoặc log mã thô; nhận `room_id` từ client cho thao tác của khách; để module nghiệp vụ tự giải mã token thay vì dùng `current_stay`.

## Success Criteria

1. Lễ tân check-in phòng 101 trên web → nhận phiếu có mã `XXXX-XXXX` + QR; phòng 101 chuyển `OCCUPIED`.
2. Hai điện thoại Android cùng đăng nhập bằng mã đó (một quét QR, một gõ tay) và thấy đúng tên khách, phòng 101, ngày trả phòng.
3. Lễ tân bấm "Cấp lại mã" → cả hai điện thoại bị đưa về màn chào ở thao tác tiếp theo; mã cũ trả `401`; mã mới đăng nhập được.
4. Lễ tân check-out → mọi thiết bị bị đăng xuất, mã trả `401`, phòng 101 chuyển `CLEANING`; "Đánh dấu đã dọn" → `VACANT`.
5. Script dò mã từ một IP bị chặn `429` từ request thứ 6 trong phút đầu.
6. Dùng token phòng 202 gọi API kèm `room_id` của phòng 101 → `400`; đọc tài nguyên của phòng 101 → `403`.
7. Trong DB, cột `room_code_lookup` không chứa mã thô; tìm mã thô trong log → không có kết quả.
8. Toàn bộ test trong Testing Strategy xanh; coverage `stay_access` ≥ 85%, toàn backend ≥ 70%.

## Out of Scope (Deferred)

- Đặt phòng trước, quản lý giá phòng, tích hợp PMS/OTA: ngoài phạm vi đồ án (giả định 9).
- Khai báo tạm trú, lưu CCCD/hộ chiếu: yêu cầu pháp lý riêng, không lưu dữ liệu nhạy cảm trong V1.
- Self check-in bằng app: khách sạn mini vẫn cần Lễ tân xác minh trực tiếp.
- Nhóm khách thuê nhiều phòng một mã: mỗi phòng một stay riêng.
- Tự động đóng stay quá hạn bằng job định kỳ: V1 chỉ chặn đăng nhập; Lễ tân check-out thủ công.

## Open Questions

1. Mã 8 ký tự `XXXX-XXXX` (đề xuất) hay 6 ký tự cho dễ gõ? 6 ký tự vẫn an toàn nhờ rate limit nhưng biên an toàn thấp hơn khoảng 1000 lần.
2. Thời gian ân hạn 6 giờ sau giờ trả phòng dự kiến có hợp lý với thói quen khách sạn mini (trả phòng trễ) không?
3. Tối đa 6 thiết bị mỗi phòng có đủ cho phòng gia đình không?
4. Phiếu check-in in bằng máy in nhiệt K80 hay giấy A6? Ảnh hưởng tới CSS in.
