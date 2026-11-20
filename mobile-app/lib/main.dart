import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/config.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/notifications/firebase_push_service.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:material_ui/material_ui.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Fails fast, naming the missing key, when built without
  // --dart-define-from-file.
  final config = AppConfig.fromEnvironment();
  // Without google-services.json this is a no-op service and the app still
  // works; screens refresh on their own.
  final push = await FirebasePushService.start(const Locale('vi'));
  runApp(
    ProviderScope(
      overrides: [
        appConfigProvider.overrideWithValue(config),
        pushServiceProvider.overrideWithValue(push),
      ],
      child: const HotelGuestApp(),
    ),
  );
}
