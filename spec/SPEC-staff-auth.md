# Spec: staff-auth — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: một tài khoản một vai trò, phiên 12 giờ, chưa có vai trò quản lý; duyệt dependency `argon2-cffi`, `pyjwt`
Module id: `staff-auth` · Phụ thuộc: `foundation` · Mức: MVP · Sprint 1 (D03–D05) · Map: [capability-map.md](capability-map.md)

## Objective

Nhân viên khách sạn đăng nhập Web quản trị và chỉ thấy, chỉ làm được việc của bộ phận mình.
Backend có một cơ chế phân quyền dùng chung (`current_staff`, `require_roles`) cho mọi module sau.

**Người dùng:** Lễ tân (`RECEPTION`), Bếp (`KITCHEN`), Buồng phòng (`HOUSEKEEPING`). Tech Lead/quản lý tạo tài khoản bằng CLI.

**User stories**
- Là nhân viên, tôi đăng nhập bằng email + mật khẩu và vào thẳng màn hình của bộ phận mình.
- Là nhân viên Bếp, tôi không mở được màn Lễ tân hay Buồng phòng, kể cả khi gõ URL hoặc gọi API trực tiếp (`403`).
- Là quản lý, tôi tạo, khóa tài khoản và đặt lại mật khẩu bằng một lệnh CLI. Tài khoản bị khóa mất quyền truy cập ngay.
- Là nhân viên, tôi tự đổi mật khẩu và đăng xuất. Phiên tự gia hạn trong ca làm việc mà không phải đăng nhập lại liên tục.

**Không thuộc module này:** check-in, cấp mã phòng, token của khách (`stay-access`), màn hình nghiệp vụ của từng bộ phận.

## Tech Stack

Kế thừa `foundation`. Thêm dependency (cần duyệt theo Boundaries của foundation):

| Package | Dependency mới | Lý do |
|---|---|---|
| backend-api | `argon2-cffi` | Băm mật khẩu bằng Argon2id |
| backend-api | `pyjwt` | Ký và xác thực JWT HS256 |

Không thêm dependency cho admin-web: dùng React context và `fetch` có sẵn.

## Thiết kế

### Dữ liệu (migration Alembic)

```
staff
  id               uuid PK
  email            citext UNIQUE NOT NULL
  full_name        text NOT NULL
  password_hash    text NOT NULL            -- argon2id
  role             staff_role NOT NULL      -- enum: RECEPTION | KITCHEN | HOUSEKEEPING
  is_active        boolean NOT NULL DEFAULT true
  token_version    integer NOT NULL DEFAULT 0   -- tăng lên → mọi access token cũ mất hiệu lực
  last_login_at    timestamptz NULL
  created_at, updated_at timestamptz NOT NULL

staff_refresh_token
  id               uuid PK
  staff_id         uuid FK → staff ON DELETE CASCADE
  token_hash       text UNIQUE NOT NULL     -- sha256 của refresh token, không lưu token thô
  family_id        uuid NOT NULL            -- chuỗi xoay vòng; phát hiện dùng lại → thu hồi cả chuỗi
  expires_at       timestamptz NOT NULL
  revoked_at       timestamptz NULL
  created_at       timestamptz NOT NULL

rate_limit_bucket                           -- dùng chung, stay-access tái sử dụng
  key              text PK                  -- VD "staff_login:email:<sha256>" , "staff_login:ip:<ip>"
  window_start     timestamptz NOT NULL
  count            integer NOT NULL
  locked_until     timestamptz NULL
```

- Mỗi tài khoản có **một vai trò** và gắn với một người. Không dùng tài khoản chung cho cả bộ phận, vì `housekeeping` cần gán việc theo từng nhân viên.

### Token

| Loại | Nơi lưu ở client | Thời hạn | Nội dung |
|---|---|---|---|
| Access token (JWT HS256, secret `STAFF_JWT_SECRET`) | Bộ nhớ JS, không dùng localStorage | 15 phút | `sub`=staff_id, `role`, `typ`="staff", `ver`=token_version, `iat`, `exp`, `jti` |
| Refresh token (chuỗi ngẫu nhiên 256 bit) | Cookie `staff_refresh`: `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/staff/auth` | 12 giờ (một ca) | Lưu hash trong `staff_refresh_token` |

- **Tách biệt với token của khách:** token khách (`stay-access`) dùng secret khác (`STAY_JWT_SECRET`) và `typ`="stay". Gửi token khách tới endpoint nhân viên → `401`, và ngược lại.
- **Mỗi request** kiểm tra `typ`, chữ ký, `exp`, rồi tra DB: `staff.is_active = true` và `ver = staff.token_version`. Không khớp → `401`.
- **Xoay vòng refresh token:** mỗi lần refresh cấp token mới và thu hồi token cũ. Nếu một refresh token đã thu hồi bị dùng lại → thu hồi cả `family_id` và trả `401`.
- `/refresh` và `/logout` kiểm tra header `Origin` nằm trong `ADMIN_WEB_ORIGINS`, cộng với `SameSite=Strict` để chống CSRF.

### API (`/api/v1/staff`)

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| POST | `/auth/login` | public, có rate limit | `{email, password}` → `200 {access_token, expires_in, staff:{id,email,full_name,role}}` + set cookie refresh |
| POST | `/auth/refresh` | cookie refresh | → access token mới + cookie mới |
| POST | `/auth/logout` | cookie refresh | Thu hồi refresh token hiện tại, xóa cookie → `204` |
| GET | `/me` | mọi staff | Thông tin tài khoản hiện tại |
| POST | `/me/password` | mọi staff | `{current_password, new_password}` → `204`; tăng `token_version`, thu hồi mọi refresh token khác |

**Quy tắc đăng nhập**
- Sai email hoặc sai mật khẩu đều trả `401 UNAUTHORIZED` với cùng một thông báo, và vẫn chạy hàm băm khi email không tồn tại (chống dò tài khoản qua thời gian phản hồi).
- Tài khoản bị khóa → `401` với cùng thông báo trên.
- **Rate limit:** sai 5 lần trong 15 phút theo email, hoặc 20 lần trong 15 phút theo IP → khóa 15 phút, trả `429 RATE_LIMITED` kèm header `Retry-After`. Đăng nhập thành công thì xóa bộ đếm theo email.
- Mật khẩu: tối thiểu 10 ký tự, không trùng email. Không có quy tắc phức tạp hơn.

### Phân quyền dùng chung (cho các module sau)

```python
# backend-api/app/modules/staff_auth/deps.py
async def current_staff(token: str = Depends(bearer), db: AsyncSession = Depends(get_db)) -> Staff: ...

def require_roles(*roles: StaffRole) -> Callable[..., Awaitable[Staff]]:
    async def dependency(staff: Staff = Depends(current_staff)) -> Staff:
        if staff.role not in roles:
            raise Forbidden("Bạn không có quyền thực hiện thao tác này")
        return staff
    return dependency

# Dùng trong module khác:
@router.post("/orders/{order_id}/confirm")
async def confirm_order(order_id: UUID, staff: Staff = Depends(require_roles(StaffRole.KITCHEN))): ...
```

- Mọi endpoint nhân viên **bắt buộc** khai báo `require_roles(...)`. Có test quét toàn bộ router `/api/v1` để phát hiện endpoint không khai báo phân quyền: endpoint chỉ được hợp lệ khi thuộc danh sách public, hoặc có `current_staff`, hoặc có `current_stay`.

### CLI quản trị (`uv run python -m app.cli ...`)

| Lệnh | Mô tả |
|---|---|
| `create-staff --email --name --role` | Nhập mật khẩu qua prompt ẩn (`getpass`), không nhận mật khẩu qua tham số dòng lệnh |
| `set-active --email --active/--inactive` | Khóa hoặc mở khóa; khóa thì tăng `token_version` và thu hồi mọi refresh token |
| `reset-password --email` | Đặt mật khẩu mới qua prompt; tăng `token_version` |
| `seed-dev` | Chỉ chạy khi `APP_ENV=dev`: tạo 3 tài khoản mẫu (`reception@`, `kitchen@`, `housekeeping@dev.local`) với mật khẩu lấy từ `DEV_STAFF_PASSWORD` |

### admin-web

- Trang `/[locale]/login`: form email + mật khẩu, hiển thị lỗi `401`/`429` bằng chuỗi i18n, không tiết lộ sai email hay sai mật khẩu.
- `AuthProvider`: giữ access token trong bộ nhớ; khi tải trang gọi `/auth/refresh` để khôi phục phiên; tự refresh trước khi hết hạn khoảng 1 phút; gặp `401` thì refresh một lần rồi mới chuyển về trang login.
- Vùng giao diện theo vai trò: `/[locale]/reception/*`, `/[locale]/kitchen/*`, `/[locale]/housekeeping/*`. Đăng nhập xong chuyển tới vùng của vai trò. Mở vùng khác → trang `403` có nút quay về vùng của mình.
- Layout chung: tên nhân viên, vai trò, menu theo vai trò, đổi mật khẩu, đăng xuất, chuyển ngôn ngữ vi/en.
- Mỗi vùng có trang tổng quan ở trạng thái trống ("Chưa có yêu cầu nào"). Nội dung nghiệp vụ do các module sau bổ sung.
- Chặn ở giao diện chỉ để trải nghiệm tốt hơn; **quyền thật luôn do backend kiểm tra**.

## Commands

Kế thừa `spec/SPEC-foundation.md`. Bổ sung:

```bash
cd backend-api
uv run alembic revision --autogenerate -m "staff auth"   # chỉ khi tạo migration
uv run python -m app.cli seed-dev
uv run python -m app.cli create-staff --email le.tan@hotel.vn --name "Nguyen Van A" --role RECEPTION
uv run pytest -q tests/integration/staff_auth
```

## Project Structure

```
backend-api/app/modules/staff_auth/
  models.py  schemas.py  service.py  repository.py  router.py  deps.py  security.py (argon2, jwt)
backend-api/app/core/rate_limit.py          # rate limiter dùng chung, lưu trên Postgres
backend-api/app/cli.py
backend-api/migrations/versions/xxxx_staff_auth.py
backend-api/tests/unit/staff_auth/  tests/integration/staff_auth/  tests/integration/test_route_guards.py
admin-web/src/app/[locale]/login/page.tsx
admin-web/src/app/[locale]/(staff)/layout.tsx  reception/  kitchen/  housekeeping/  forbidden/
admin-web/src/lib/auth/  AuthProvider.tsx  useAuth.ts  roles.ts
admin-web/tests/auth/
```

## Code Style

Theo `foundation`. Riêng module này:
- Hàm bảo mật (`hash_password`, `verify_password`, `encode_access_token`, `decode_access_token`) nằm gọn trong `security.py` và có unit test riêng.
- So sánh hash/token bằng `hmac.compare_digest`.
- Không log email đầy đủ khi đăng nhập thất bại; chỉ log hash email và IP.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | Băm và xác minh Argon2id; encode/decode JWT; token hết hạn, sai chữ ký, sai `typ` → lỗi; rate limiter đếm theo cửa sổ và khóa đúng hạn |
| Integration (Postgres thật) | Đăng nhập đúng → `200` + cookie đủ cờ `HttpOnly`/`Secure`/`SameSite=Strict`; sai mật khẩu / email không tồn tại / tài khoản khóa → `401` cùng thông báo; sai lần thứ 6 → `429` có `Retry-After` |
| Integration | Refresh xoay vòng token; dùng lại refresh token cũ → `401` và cả chuỗi bị thu hồi; logout → refresh `401`; `Origin` lạ → `403` |
| Integration | Khóa tài khoản hoặc đổi mật khẩu → access token cũ `401` ngay |
| Integration — RBAC (C5.3) | Router chỉ dùng cho test, mỗi vai trò một endpoint: ma trận 3 vai trò × 3 endpoint, đúng vai trò → `200`, sai → `403`; không token → `401`; **token khách (`typ`="stay") → `401`** |
| Integration — route guard | Quét router: mọi endpoint trong `/api/v1` thuộc danh sách public, hoặc có `current_staff`, hoặc có `current_stay` |
| admin-web (Vitest) | `AuthProvider` refresh khi tải trang; gặp `401` thì refresh một lần rồi chuyển về login; điều hướng theo vai trò; trang `403` khi vào sai vùng |

Coverage của `app/modules/staff_auth` ≥ 85% (cao hơn mức chung vì là module bảo mật).

## Boundaries

- **Always:** mọi endpoint nhân viên dùng `require_roles`; dùng chung một thông báo lỗi khi đăng nhập thất bại; băm mật khẩu bằng Argon2id; mật khẩu chỉ nhập qua prompt hoặc form.
- **Ask first:** đổi thời hạn token hoặc ngưỡng rate limit; thêm vai trò mới (ví dụ ADMIN/MANAGER); cho một tài khoản có nhiều vai trò; đổi nơi lưu refresh token.
- **Never:** lưu access token vào localStorage/sessionStorage; log mật khẩu, token hoặc hash; dùng chung secret JWT giữa nhân viên và khách; chỉ kiểm tra quyền ở frontend.

## Success Criteria

1. Chạy `seed-dev` → đăng nhập được 3 tài khoản mẫu. Mỗi tài khoản vào thẳng vùng của vai trò mình, gõ URL vùng khác → trang `403`.
2. Gọi API endpoint của Bếp bằng token Lễ tân → `403`; không có token → `401`; dùng token khách → `401`.
3. Sai mật khẩu 5 lần → lần thứ 6 trả `429` có `Retry-After`. Sau 15 phút đăng nhập lại được.
4. Thông báo và mã lỗi giống hệt nhau khi sai email và khi sai mật khẩu.
5. Khóa tài khoản bằng CLI khi nhân viên đang đăng nhập → request tiếp theo `401`, web chuyển về login.
6. Tải lại trang web trong vòng 12 giờ không phải đăng nhập lại; sau khi đăng xuất, tải lại trang thì phải đăng nhập.
7. DevTools cho thấy access token không nằm trong localStorage/sessionStorage/cookie đọc được bằng JS.
8. Test quét router chạy xanh. Thêm một endpoint không khai báo phân quyền thì test đỏ.
9. Toàn bộ test trong Testing Strategy xanh. Coverage `staff_auth` ≥ 85%, toàn backend vẫn ≥ 70%.

## Out of Scope (Deferred)

- Giao diện quản lý nhân viên trên web (tạo, khóa, phân vai trò): V1 dùng CLI, đủ cho quy mô khách sạn mini.
- Quên mật khẩu qua email: chưa cần hạ tầng gửi mail; quản lý đặt lại bằng CLI.
- 2FA / SSO: vượt nhu cầu đồ án.
- Một tài khoản nhiều vai trò, vai trò MANAGER: chờ phản hồi từ đơn vị thử nghiệm.
- Nhật ký kiểm toán (audit log) đầy đủ cho thao tác nhân viên: hiện chỉ có `status_history` trong từng module nghiệp vụ.

## Open Questions

1. **Khách sạn mini thường có một người kiêm nhiều việc** (ví dụ lễ tân ban đêm kiêm buồng phòng). V1 giữ một tài khoản một vai trò: người kiêm nhiệm dùng hai tài khoản. Nếu cần nhiều vai trò cho một tài khoản thì nên quyết ngay, vì nó thay đổi `role` thành mảng.
2. Phiên 12 giờ (một ca làm việc) có phù hợp không, hay cần 24 giờ?
3. Có cần vai trò quản lý (xem tất cả, chỉ đọc) ngay trong MVP để demo cho đơn vị thử nghiệm không?
