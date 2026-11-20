import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';

import '../stay_access/fakes.dart';
import 'fakes.dart';

const stayPayload = PushPayload(
  type: 'STAY',
  entityId: '6f1c2a3b-0000-4000-8000-000000000002',
  status: 'ACTIVE',
);

Future<FakePushService> pumpSignedIn(
  WidgetTester tester, {
  String? storedToken = 'stored',
}) async {
  final push = FakePushService();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: FakeStayRepository(),
          store: MemorySessionStore(token: storedToken),
        ),
        pushServiceProvider.overrideWithValue(push),
        notificationsRepositoryProvider.overrideWithValue(
          FakeNotificationsRepository(),
        ),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  return push;
}

void main() {
  testWidgets('a tapped stay notification (welcome, thank-you) opens home', (
    tester,
  ) async {
    final push = await pumpSignedIn(tester);
    final container = ProviderScope.containerOf(
      tester.element(find.byType(HotelGuestApp)),
    );

    push.taps.add(stayPayload);
    await tester.pumpAndSettle();

    expect(find.text('Phòng 101'), findsOneWidget);
    expect(container.read(pendingRouteProvider), isNull, reason: 'consumed');
  });

  testWidgets('a tap while signed out still lands on the sign-in screen', (
    tester,
  ) async {
    final push = await pumpSignedIn(tester, storedToken: null);
    push.taps.add(orderPayload);
    await tester.pumpAndSettle();
    expect(find.text('Chào mừng Quý khách'), findsOneWidget);
  });
}
