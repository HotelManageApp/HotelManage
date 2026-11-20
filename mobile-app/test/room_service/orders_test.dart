import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../notifications/fakes.dart';
import '../stay_access/fakes.dart';
import 'fakes.dart';

const idA = '6f1c2a3b-0000-4000-8000-0000000000a1';
const idB = '6f1c2a3b-0000-4000-8000-0000000000b2';

FoodOrder placed(String id, {String status = 'PENDING', int minutesAgo = 5}) {
  final base = orderFrom(const [
    NewOrderLine(itemId: 'Phở bò', quantity: 2, note: 'ít cay'),
  ]);
  return FoodOrder(
    id: id,
    status: status,
    items: base.items,
    totalVnd: base.totalVnd,
    createdAt: DateTime.now().toUtc().subtract(Duration(minutes: minutesAgo)),
    version: 0,
    estimatedMinutes: status == 'PENDING' ? null : 25,
  );
}

PushPayload pushFor(String id, String status) =>
    PushPayload(type: 'FOOD_ORDER', entityId: id, status: status);

Future<(FakeRoomServiceRepository, FakePushService)> pumpHome(
  WidgetTester tester,
  List<FoodOrder> orders,
) async {
  final repo = FakeRoomServiceRepository()..orders.addAll(orders);
  final push = FakePushService();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: FakeStayRepository(),
          store: MemorySessionStore(token: tokenFor('stay-A')),
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(repo),
        pushServiceProvider.overrideWithValue(push),
        notificationsRepositoryProvider.overrideWithValue(
          FakeNotificationsRepository(),
        ),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  return (repo, push);
}

String statusText(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('order-status'))).data!;

Future<void> openOnlyOrder(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('open-orders-card')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('home shows open orders; one opens its detail directly', (
    tester,
  ) async {
    await pumpHome(tester, [
      placed(idA, status: 'PREPARING'),
      placed(idB, status: 'COMPLETED'),
    ]);
    expect(find.text('1 đơn đang xử lý'), findsOneWidget);
    expect(find.text('Đang nấu'), findsOneWidget);

    await openOnlyOrder(tester);
    expect(find.byKey(const Key('order-progress')), findsOneWidget);
    expect(statusText(tester), 'Đang nấu');
    expect(find.text('Dự kiến khoảng 25 phút'), findsOneWidget);
    expect(find.textContaining('ít cay'), findsOneWidget);
    expect(
      find.byKey(const Key('cancel-order')),
      findsNothing,
      reason: 'only PENDING orders can be cancelled by the guest',
    );
  });

  testWidgets('no card without open orders; the list shows every order', (
    tester,
  ) async {
    await pumpHome(tester, [
      placed(idA, status: 'COMPLETED'),
      placed(idB, status: 'CANCELLED', minutesAgo: 60),
    ]);
    expect(find.byKey(const Key('open-orders-card')), findsNothing);

    await tester.tap(find.byKey(const Key('tile-my-orders')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('order-$idA')), findsOneWidget);
    expect(find.byKey(const Key('order-$idB')), findsOneWidget);
    expect(find.text('Đã giao'), findsOneWidget);
    expect(find.text('Đã hủy'), findsOneWidget);
  });

  testWidgets('a pending order can be cancelled after confirming', (
    tester,
  ) async {
    final (repo, _) = await pumpHome(tester, [placed(idA)]);
    await openOnlyOrder(tester);

    await tester.tap(find.byKey(const Key('cancel-order')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Không'));
    await tester.pumpAndSettle();
    expect(repo.cancels, isEmpty);

    await tester.tap(find.byKey(const Key('cancel-order')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-cancel')));
    await tester.pumpAndSettle();

    expect(repo.cancels, [idA]);
    expect(find.text('Đã hủy đơn'), findsOneWidget);
    expect(statusText(tester), 'Đã hủy');
    expect(find.text('Lý do: Khách hủy'), findsOneWidget);
    expect(find.byKey(const Key('cancel-order')), findsNothing);
  });

  testWidgets('cancelling after the kitchen accepted explains why', (
    tester,
  ) async {
    final (repo, _) = await pumpHome(tester, [placed(idA)]);
    await openOnlyOrder(tester);
    repo
      ..cancelFailure = apiError(409, 'INVALID_TRANSITION')
      ..orders[0] = placed(idA, status: 'CONFIRMED');

    await tester.tap(find.byKey(const Key('cancel-order')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-cancel')));
    await tester.pumpAndSettle();

    expect(find.textContaining('không hủy được nữa'), findsOneWidget);
    expect(statusText(tester), 'Bếp đã nhận', reason: 'reloaded');
  });

  testWidgets('a food-order push refreshes the open detail', (tester) async {
    final (repo, push) = await pumpHome(tester, [placed(idA)]);
    await openOnlyOrder(tester);

    repo.orders[0] = placed(idA, status: 'DELIVERING');
    push.foreground.add(IncomingPush(payload: pushFor(idA, 'DELIVERING')));
    await tester.pumpAndSettle();
    expect(statusText(tester), 'Đang mang lên phòng');
  });

  testWidgets('the detail refreshes itself every 15 s', (tester) async {
    final (repo, _) = await pumpHome(tester, [placed(idA)]);
    await openOnlyOrder(tester);
    final before = repo.detailLoads.length;

    repo.orders[0] = placed(idA, status: 'CONFIRMED');
    await tester.pump(const Duration(seconds: 14));
    expect(repo.detailLoads.length, before);
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(repo.detailLoads.length, greaterThan(before));
    expect(statusText(tester), 'Bếp đã nhận');
  });

  testWidgets('tapping a food-order notification opens that order', (
    tester,
  ) async {
    final (_, push) = await pumpHome(tester, [
      placed(idA, status: 'PREPARING'),
    ]);
    push.taps.add(pushFor(idA, 'PREPARING'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('order-progress')), findsOneWidget);
    expect(statusText(tester), 'Đang nấu');
  });
}
