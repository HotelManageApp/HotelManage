import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../stay_access/fakes.dart';

Future<FakeStayRepository> pumpApp(
  WidgetTester tester, {
  FakeStayRepository? repo,
  MemorySessionStore? store,
}) async {
  final fake = repo ?? FakeStayRepository();
  await tester.pumpWidget(
    ProviderScope(
      overrides: sessionOverrides(
        repo: fake,
        store: store ?? MemorySessionStore(),
      ),
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  return fake;
}

Future<void> enterCode(WidgetTester tester, String code) async {
  await tester.enterText(find.byKey(const Key('room-code-field')), code);
  await tester.tap(find.text('Đăng nhập'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('starts in Vietnamese on the sign-in screen', (tester) async {
    await pumpApp(tester);
    expect(find.text('Chào mừng Quý khách'), findsOneWidget);
    expect(find.text('Quét mã QR'), findsOneWidget);
  });

  testWidgets('switches to English', (tester) async {
    await pumpApp(tester);
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();
    expect(find.text('Welcome'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
  });

  testWidgets('signs in with a typed code and opens the home screen', (
    tester,
  ) async {
    final repo = await pumpApp(tester);
    await enterCode(tester, 'k7m29xpq');

    expect(repo.logins.single['code'], 'K7M29XPQ');
    expect(find.text('Phòng 101'), findsOneWidget);
    expect(find.text('Xin chào, Tran Thi B'), findsOneWidget);
  });

  testWidgets('an incomplete code is caught before calling the server', (
    tester,
  ) async {
    final repo = await pumpApp(tester);
    await enterCode(tester, 'K7M2');
    expect(repo.logins, isEmpty);
    expect(find.text('Mã phòng không hợp lệ hoặc đã hết hạn'), findsOneWidget);
  });

  final cases = <String, (AppException, String)>{
    'invalid code': (
      apiError(401, 'UNAUTHORIZED'),
      'Mã phòng không hợp lệ hoặc đã hết hạn',
    ),
    'too many devices': (
      apiError(409, 'TOO_MANY_DEVICES'),
      'Phòng đã đăng nhập trên quá nhiều thiết bị. Vui lòng liên hệ Lễ tân.',
    ),
    'rate limited': (
      apiError(429, 'RATE_LIMITED', retryAfter: 840),
      'Quý khách đã thử quá nhiều lần. Vui lòng thử lại sau 14 phút.',
    ),
    'offline': (
      const AppException(status: 0, code: 'NETWORK_ERROR', message: 'x'),
      'Không kết nối được máy chủ',
    ),
  };
  for (final MapEntry(key: name, value: (error, message)) in cases.entries) {
    testWidgets('shows a message when login fails: $name', (tester) async {
      await pumpApp(tester, repo: FakeStayRepository(loginResult: error));
      await enterCode(tester, 'K7M2-9XPQ');
      expect(find.text(message), findsOneWidget);
      expect(find.text('Phòng 101'), findsNothing);
    });
  }

  testWidgets('a stay that ended shows the thank-you notice', (tester) async {
    await pumpApp(
      tester,
      store: MemorySessionStore(token: 'old'),
      repo: FakeStayRepository(
        meResult: apiError(401, 'UNAUTHORIZED', reason: 'STAY_CLOSED'),
      ),
    );
    expect(find.byKey(const Key('session-notice')), findsOneWidget);
    expect(
      find.text('Cảm ơn Quý khách đã lưu trú. Hẹn gặp lại!'),
      findsOneWidget,
    );
  });

  testWidgets('a stored session goes straight home; logout comes back', (
    tester,
  ) async {
    final store = MemorySessionStore(token: 'stored');
    final repo = await pumpApp(tester, store: store);
    expect(find.text('Phòng 101'), findsOneWidget);

    await tester.tap(find.byTooltip('Đăng xuất'));
    await tester.pumpAndSettle();

    expect(repo.logouts, 1);
    expect(store.token, isNull);
    expect(find.text('Chào mừng Quý khách'), findsOneWidget);
  });
}
