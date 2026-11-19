# mobile-app — Guest app (Flutter, Android)

```bash
cp env/dev.example.json env/dev.json     # API_BASE_URL: 10.0.2.2 = host machine from the Android emulator
flutter pub get                          # also generates lib/l10n/generated
flutter analyze
flutter test
flutter run --dart-define-from-file=env/dev.json
flutter build apk --release --dart-define-from-file=env/prod.json
```

Structure: `lib/app` (app, router, theme) · `lib/core` (config, ApiClient, errors, providers) ·
`lib/features/<feature>` · `lib/l10n` (ARB files, vi is the template). See `spec/SPEC-foundation.md`.

## Push notifications (Firebase)

- `android/app/google-services.json` is **not committed** (`.gitignore`). Download it from the Firebase console
  (Android app `vn.hotelmanage.hotel_guest`) and drop it there; CI decodes it from the secret `GOOGLE_SERVICES_JSON_B64`.
- Without the file the app still builds and runs: push is disabled and screens refresh on their own.
- After sign-in the app asks for notification permission (Android 13+), registers with FCM and sends the
  Firebase Installation ID to `PUT /api/v1/guest/me/fcm-token`.
- Channel `requests` (high importance). Tapping a notification opens `/requests/<type>/<id>`, or home while that
  type has no detail screen.
