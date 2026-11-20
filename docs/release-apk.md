# APK release đã ký — T57

App khách (`mobile-app`) phát hành dạng APK cài trực tiếp (chưa lên Google Play). Mọi bản cài cho khách phải ký bằng
**một keystore release duy nhất** của đơn vị: Android chỉ cho cập nhật một app khi chữ ký giống hệt bản cũ.

## 1. Tạo keystore (một lần, người giữ: Tech Lead)

```bash
keytool -genkeypair -v -keystore hotel-guest-release.jks -alias hotel-guest \
  -keyalg RSA -keysize 4096 -validity 10000
```

- Đặt mật khẩu mạnh cho keystore và cho khóa; lưu vào trình quản lý mật khẩu của nhóm.
- Cất **2 bản sao** keystore ở nơi an toàn ngoài máy cá nhân. Mất keystore = không thể phát hành bản cập nhật cho các máy đã cài.
- **Không** commit keystore hay mật khẩu (`android/.gitignore` đã chặn `key.properties`, `*.jks`, `*.keystore`).

## 2. Build trên máy

`mobile-app/android/key.properties` (không commit):

```properties
storeFile=../hotel-guest-release.jks     # đường dẫn tính từ mobile-app/android/
storePassword=…
keyAlias=hotel-guest
keyPassword=…
```

`mobile-app/env/prod.json` (không commit, chép từ `env/prod.example.json`):

```json
{ "API_BASE_URL": "https://api.<domain>", "APP_ENV": "prod" }
```

```bash
cd mobile-app
flutter build apk --release --dart-define-from-file=env/prod.json
# → build/app/outputs/flutter-apk/app-release.apk
```

Bảo vệ có sẵn:

- Thiếu `key.properties` → build release **dừng** với thông báo rõ ràng (không ra APK ký bằng khóa debug).
  `HOTEL_ALLOW_DEBUG_SIGNING=1` chỉ dùng để thử build trên máy dev; APK đó không được đưa cho khách.
- `APP_ENV=prod` chỉ chấp nhận URL `https://` (app báo lỗi ngay khi khởi động nếu cấu hình sai).
- Bản release không cho HTTP thường (`usesCleartextTraffic` chỉ bật ở bản debug).
- Có `android/app/google-services.json` thì bật thông báo đẩy; không có thì app vẫn chạy, tự làm mới 15 s.

## 3. Build trên CI (khuyên dùng)

Workflow `.github/workflows/mobile-app.yml`, job **signed release APK**, chạy khi đẩy tag `v*` (VD `v1.0.0`, T58).
Khai báo trong *Settings → Secrets and variables → Actions* của repository:

| Secret | Nội dung |
|---|---|
| `ANDROID_KEYSTORE_B64` | `base64 -w0 hotel-guest-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | như `key.properties` |
| `PROD_API_BASE_URL` | `https://api.<domain>` |
| `GOOGLE_SERVICES_JSON_B64` | `base64 -w0 google-services.json` (tùy chọn) |

APK nằm ở mục *Artifacts* của lần chạy (`hotel-guest-v1.0.0`). Job xóa keystore khỏi máy CI sau khi build.

## 4. Kiểm tra trước khi phát cho khách (3 máy Android khác nhau)

| Bước | Máy 1 | Máy 2 | Máy 3 |
|---|---|---|---|
| Hãng / Android / RAM | | | |
| Cài APK (cho phép "nguồn không xác định") | | | |
| Quét QR / nhập mã phòng prod → vào màn chính | | | |
| Đặt món, thấy trạng thái đổi khi Bếp xử lý | | | |
| Nhận thông báo đẩy khi tắt app | | | |
| Chatbot trả lời, thẻ xác nhận đặt món | | | |
| Trả phòng nhanh → về màn chào kèm lời cảm ơn | | | |
| Cài bản mới đè bản cũ (cùng chữ ký) không mất dữ liệu đăng nhập | | | |

Kiểm tra chữ ký: `apksigner verify --print-certs app-release.apk` phải in đúng SHA-256 của keystore release.

## 5. Đã kiểm chứng (2026-11-20, máy dev)

- Không có `key.properties`: `flutter build apk --release` dừng với thông báo "Release signing key missing" — đúng.
- Với `HOTEL_ALLOW_DEBUG_SIGNING=1` và `env/prod.example.json`: build release thành công: `app-release.apk` 72,6 MB (một APK cho mọi kiến trúc CPU). Muốn APK nhỏ hơn cho từng máy: thêm `--split-per-abi` (thường dùng `app-arm64-v8a-release.apk`).
- `flutter analyze`, `flutter test` đạt (thêm test: prod chỉ nhận `https://`).
- Chưa làm: tạo keystore thật, build ký thật, cài trên 3 máy — cần keystore của đơn vị và môi trường prod (T56).
