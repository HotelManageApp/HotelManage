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
