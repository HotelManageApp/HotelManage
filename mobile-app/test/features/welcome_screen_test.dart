import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/config.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:material_ui/material_ui.dart';

Widget appWith(Future<BackendHealth> Function() health) {
  return ProviderScope(
    overrides: [
      appConfigProvider.overrideWithValue(
        const AppConfig(apiBaseUrl: 'http://backend.test', appEnv: 'test'),
      ),
      backendHealthProvider.overrideWith((ref) => health()),
    ],
    child: const HotelGuestApp(),
  );
}

void main() {
  testWidgets('starts in Vietnamese and shows the server is online', (
    tester,
  ) async {
    await tester.pumpWidget(
      appWith(
        () async => const BackendHealth(ok: true, dbOk: true, version: 'v1'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Chào mừng Quý khách'), findsOneWidget);
    expect(find.text('Đã kết nối máy chủ'), findsOneWidget);
  });

  testWidgets('switches to English', (tester) async {
    await tester.pumpWidget(
      appWith(
        () async => const BackendHealth(ok: true, dbOk: true, version: 'v1'),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();

    expect(find.text('Welcome'), findsOneWidget);
    expect(find.text('Connected to server'), findsOneWidget);
  });

  testWidgets('shows a degraded server', (tester) async {
    await tester.pumpWidget(
      appWith(
        () async => const BackendHealth(ok: false, dbOk: false, version: '?'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Máy chủ đang gặp sự cố'), findsOneWidget);
  });

  testWidgets('shows an unreachable server', (tester) async {
    await tester.pumpWidget(
      appWith(
        () async => throw const AppException(
          status: 0,
          code: 'NETWORK_ERROR',
          message: 'down',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Không kết nối được máy chủ'), findsOneWidget);
  });
}
