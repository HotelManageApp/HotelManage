import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../notifications/fakes.dart';
import '../room_service/fakes.dart';
import '../stay_access/fakes.dart';
import 'fakes.dart';

const idA = '6f1c2a3b-0000-4000-8000-0000000000c1';

class Setup {
  new(this.hk, this.stays, this.push);

  final FakeHousekeepingRepository hk;
  final FakeStayRepository stays;
  final FakePushService push;
}

Future<Setup> pumpApp(
  WidgetTester tester, {
  bool dnd = false,
  String status = 'ACTIVE',
  List<HkRequest> requests = const [],
}) async {
  final hk = FakeHousekeepingRepository()..requests.addAll(requests);
  final stays = FakeStayRepository(
    meResult: stayWith(dnd: dnd, status: status),
  );
  final push = FakePushService();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: stays,
          store: MemorySessionStore(token: tokenFor('stay-A')),
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(
          FakeRoomServiceRepository(),
        ),
        housekeepingRepositoryProvider.overrideWithValue(hk),
        pushServiceProvider.overrideWithValue(push),
        notificationsRepositoryProvider.overrideWithValue(
          FakeNotificationsRepository(),
        ),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  return Setup(hk, stays, push);
}

Future<Setup> openHousekeeping(
  WidgetTester tester, {
  bool dnd = false,
  String status = 'ACTIVE',
  List<HkRequest> requests = const [],
}) async {
  final setup = await pumpApp(
    tester,
    dnd: dnd,
    status: status,
    requests: requests,
  );
  await tester.tap(find.byKey(const Key('tile-housekeeping')));
  await tester.pumpAndSettle();
  return setup;
}

bool dndOn(WidgetTester tester) =>
    tester.widget<SwitchListTile>(find.byKey(const Key('dnd-switch'))).value;

bool enabled(WidgetTester tester, String key) =>
    tester.widget<FilledButton>(find.byKey(Key(key))).onPressed != null;

String statusText(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('hk-status'))).data!;

Future<void> scrollTo(WidgetTester tester, String key) =>
    tester.scrollUntilVisible(
      find.byKey(Key(key)),
      200,
      scrollable: find.byType(Scrollable).first,
    );

void main() {
  group('cleaningSlots', () {
    test('every 30 minutes from at least 30 minutes away, for 24 hours', () {
      final now = DateTime(2026, 11, 19, 9, 10);
      final slots = cleaningSlots(now, DateTime(2026, 11, 25, 12));
      expect(slots.first, DateTime(2026, 11, 19, 10));
      expect(slots[1], DateTime(2026, 11, 19, 10, 30));
      expect(slots.last, DateTime(2026, 11, 20, 9));
    });

    test('never after check-out', () {
      final now = DateTime(2026, 11, 19, 9);
      final slots = cleaningSlots(now, DateTime(2026, 11, 19, 11, 15));
      expect(slots, [
        DateTime(2026, 11, 19, 9, 30),
        DateTime(2026, 11, 19, 10),
        DateTime(2026, 11, 19, 10, 30),
        DateTime(2026, 11, 19, 11),
      ]);
      expect(cleaningSlots(now, DateTime(2026, 11, 19, 9, 20)), isEmpty);
    });
  });

  testWidgets('the Do Not Disturb switch saves and reads back the server', (
    tester,
  ) async {
    final s = await openHousekeeping(tester);
    s.hk.onDnd = (on) => s.stays.meResult = stayWith(dnd: on);
    expect(dndOn(tester), isFalse);

    await tester.tap(find.byKey(const Key('dnd-switch')));
    await tester.pumpAndSettle();
    expect(s.hk.dndCalls, [true]);
    expect(dndOn(tester), isTrue);
  });

  testWidgets('requests cleaning now, which turns Do Not Disturb off', (
    tester,
  ) async {
    final s = await openHousekeeping(tester, dnd: true);
    s.hk.onCreated = (_) => s.stays.meResult = stayWith();
    expect(
      find.text('Gọi dọn phòng sẽ tắt chế độ Không làm phiền.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('cleaning-note')), 'Thay ga');
    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();

    final call = s.hk.creates.single;
    expect(call.type, 'CLEANING');
    expect(call.preferredTime, isNull, reason: 'ASAP');
    expect(call.note, 'Thay ga');
    expect(statusText(tester), 'Chờ nhân viên nhận', reason: 'detail opened');

    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(dndOn(tester), isFalse);
    expect(find.byKey(const Key('view-open-cleaning')), findsOneWidget);
    expect(find.byKey(const Key('send-cleaning')), findsNothing);
  });

  testWidgets('requests cleaning at a chosen time', (tester) async {
    final s = await openHousekeeping(tester);
    await tester.tap(find.text('Chọn giờ'));
    await tester.pumpAndSettle();
    expect(enabled(tester, 'send-cleaning'), isFalse, reason: 'pick a time');

    await tester.tap(find.byKey(const Key('cleaning-slot')));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownMenuItem<DateTime>).at(1).last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();

    final sent = s.hk.creates.single.preferredTime;
    expect(sent, isNotNull);
    expect(sent!.isAfter(DateTime.now()), isTrue);
    expect(sent.minute % 30, 0);
  });

  testWidgets('amenities count 1–5 and "Other" needs a note', (tester) async {
    final s = await openHousekeeping(tester);
    await scrollTo(tester, 'send-amenities');
    expect(enabled(tester, 'send-amenities'), isFalse);

    final plus = find.ancestor(
      of: find.byTooltip('+ Khăn tắm'),
      matching: find.byType(IconButton),
    );
    for (var i = 0; i < 6; i++) {
      await tester.tap(plus, warnIfMissed: false);
      await tester.pump();
    }
    expect(
      tester.widget<IconButton>(plus).onPressed,
      isNull,
      reason: 'at most 5',
    );
    expect(
      tester.widget<Text>(find.byKey(const Key('amenity-qty-TOWEL'))).data,
      '5',
    );
    await tester.tap(find.byTooltip('+ Khác'));
    await tester.pump();
    expect(find.text('Vui lòng ghi rõ đồ dùng cần thêm'), findsOneWidget);
    expect(enabled(tester, 'send-amenities'), isFalse);

    await tester.enterText(
      find.byKey(const Key('amenity-note')),
      'Bàn chải trẻ em',
    );
    await tester.pump();
    await scrollTo(tester, 'send-amenities');
    await tester.tap(find.byKey(const Key('send-amenities')));
    await tester.pumpAndSettle();

    final call = s.hk.creates.single;
    expect(call.type, 'AMENITY');
    expect(
      [for (final a in call.amenities) a.toJson()],
      [
        {'code': 'TOWEL', 'quantity': 5},
        {'code': 'OTHER', 'quantity': 1},
      ],
    );
    expect(call.note, 'Bàn chải trẻ em');
  });

  testWidgets('a lost connection retries with the same Idempotency-Key, an '
      'edited form gets a new one', (tester) async {
    final s = await openHousekeeping(tester);
    s.hk.createFailures.addAll([networkError, networkError]);

    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();
    expect(find.textContaining('không bị gửi trùng'), findsOneWidget);
    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('cleaning-note')), 'Sau 3h');
    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();

    final keys = [for (final c in s.hk.creates) c.key];
    expect(keys[1], keys[0]);
    expect(keys[2], isNot(keys[0]));
  });

  testWidgets('a second open cleaning request is explained', (tester) async {
    final s = await openHousekeeping(tester);
    s.hk.createFailures.add(apiError(409, 'CONFLICT'));
    await tester.tap(find.byKey(const Key('send-cleaning')));
    await tester.pumpAndSettle();
    expect(
      find.text('Quý khách đã có một yêu cầu dọn phòng đang xử lý.'),
      findsOneWidget,
    );
  });

  testWidgets('nothing can be requested while checking out', (tester) async {
    await openHousekeeping(tester, status: 'CHECKOUT_PENDING');
    expect(enabled(tester, 'send-cleaning'), isFalse);
    expect(
      tester
          .widget<SwitchListTile>(find.byKey(const Key('dnd-switch')))
          .onChanged,
      isNull,
    );
  });

  group('requests', () {
    testWidgets('home shows the open request and its detail can cancel it', (
      tester,
    ) async {
      final s = await pumpApp(tester, requests: [cleaning(idA)]);
      expect(find.text('1 yêu cầu buồng phòng đang xử lý'), findsOneWidget);
      await tester.tap(find.byKey(const Key('open-hk-card')));
      await tester.pumpAndSettle();
      expect(statusText(tester), 'Chờ nhân viên nhận');

      await tester.tap(find.byKey(const Key('cancel-hk')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-cancel-hk')));
      await tester.pumpAndSettle();
      expect(s.hk.cancels, [idA]);
      expect(statusText(tester), 'Đã hủy');
      expect(find.byKey(const Key('cancel-hk')), findsNothing);
    });

    testWidgets('a claimed request shows who is on it and cannot be '
        'cancelled', (tester) async {
      final claimed = withHkStatus(cleaning(idA), 'ASSIGNED', assignee: 'Lan');
      await pumpApp(tester, requests: [claimed]);
      await tester.tap(find.byKey(const Key('open-hk-card')));
      await tester.pumpAndSettle();
      expect(statusText(tester), 'Đã có nhân viên nhận');
      expect(find.text('Người phụ trách: Lan'), findsOneWidget);
      expect(find.byKey(const Key('cancel-hk')), findsNothing);
    });

    testWidgets('cancelling just after it was claimed explains why', (
      tester,
    ) async {
      final s = await pumpApp(tester, requests: [cleaning(idA)]);
      await tester.tap(find.byKey(const Key('open-hk-card')));
      await tester.pumpAndSettle();
      s.hk
        ..cancelFailure = apiError(409, 'INVALID_TRANSITION')
        ..requests[0] = withHkStatus(
          cleaning(idA),
          'ASSIGNED',
          assignee: 'Lan',
        );
      await tester.tap(find.byKey(const Key('cancel-hk')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-cancel-hk')));
      await tester.pumpAndSettle();
      expect(find.textContaining('không hủy được nữa'), findsOneWidget);
      expect(statusText(tester), 'Đã có nhân viên nhận');
    });

    testWidgets('a housekeeping push refreshes the detail; tapping one opens '
        'it', (tester) async {
      final s = await pumpApp(tester, requests: [cleaning(idA)]);
      const payload = PushPayload(
        type: 'HOUSEKEEPING',
        entityId: idA,
        status: 'IN_PROGRESS',
      );
      s.push.taps.add(payload);
      await tester.pumpAndSettle();
      expect(statusText(tester), 'Chờ nhân viên nhận');

      s.hk.requests[0] = withHkStatus(
        cleaning(idA),
        'IN_PROGRESS',
        assignee: 'Lan',
      );
      s.push.foreground.add(const IncomingPush(payload: payload));
      await tester.pumpAndSettle();
      expect(statusText(tester), 'Đang thực hiện');
    });

    testWidgets('the list shows every request with what and when', (
      tester,
    ) async {
      final amenity = HkRequest(
        id: '6f1c2a3b-0000-4000-8000-0000000000d2',
        type: 'AMENITY',
        status: 'DONE',
        createdAt: DateTime.now().toUtc(),
        amenities: const [AmenityLine(code: 'WATER', quantity: 2)],
      );
      await openHousekeeping(tester, requests: [amenity, cleaning(idA)]);
      await tester.tap(find.byKey(const Key('my-hk-requests')));
      await tester.pumpAndSettle();
      expect(find.text('Đã xong'), findsOneWidget);
      expect(find.textContaining('2× Nước suối'), findsOneWidget);
      expect(find.textContaining('Càng sớm càng tốt'), findsNWidgets(2));
    });
  });
}
