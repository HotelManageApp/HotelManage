import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/config.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  // Fails fast, naming the missing key, when built without
  // --dart-define-from-file.
  final config = AppConfig.fromEnvironment();
  runApp(
    ProviderScope(
      overrides: [appConfigProvider.overrideWithValue(config)],
      child: const HotelGuestApp(),
    ),
  );
}
