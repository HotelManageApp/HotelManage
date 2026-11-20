import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../housekeeping/fakes.dart';
import '../notifications/fakes.dart';
import '../room_service/fakes.dart';
import '../stay_access/fakes.dart';
import 'fakes.dart';

class Setup {
  new(this.checkout, this.stays, this.push, this.container);

  final FakeCheckoutRepository checkout;
  final FakeStayRepository stays;
  final FakePushService push;
  final ProviderContainer container;
}

Future<Setup> pumpApp(
  WidgetTester tester, {
  String status = 'ACTIVE',
  Object? current,
  Object? preview,
}) async {
  final checkout = FakeCheckoutRepository(
    currentResult: current,
    previewResult: preview,
  );
  final stays = FakeStayRepository(meResult: stayWith(status: status));
  final push = FakePushService();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: stays,
          store: MemorySessionStore(token: tokenFor('stay-A')),
          checkout: checkout,
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(
          FakeRoomServiceRepository(),
        ),
        housekeepingRepositoryProvider.overrideWithValue(
          FakeHousekeepingRepository(),
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
  final container = ProviderScope.containerOf(
    tester.element(find.byType(HotelGuestApp)),
  );
  return Setup(checkout, stays, push, container);
}

const checkoutPush = PushPayload(
  type: 'CHECKOUT',
  entityId: requestId,
  status: 'BILLING_VERIFIED',
);

Finder tileSubtitle(String key, String text) =>
    find.descendant(of: find.byKey(Key(key)), matching: find.text(text));

Future<void> scrollTo(WidgetTester tester, Finder finder) => tester
    .scrollUntilVisible(finder, 200, scrollable: find.byType(Scrollable).first);

void main() {
  testWidgets('the guest sees a labelled estimate, rates the stay and '
      'confirms; ordering and housekeeping then lock', (tester) async {
    final setup = await pumpApp(tester, preview: bill(openOrders: 1));
    setup.checkout.onCreated = () =>
        setup.stays.meResult = stayWith(status: 'CHECKOUT_PENDING');

    expect(find.byKey(const Key('checkout-status-card')), findsNothing);
    await scrollTo(tester, find.byKey(const Key('tile-express-checkout')));
    await tester.tap(find.byKey(const Key('tile-express-checkout')));
    await tester.pumpAndSettle();

    expect(find.text('Tạm tính — Lễ tân sẽ đối soát'), findsOneWidget);
    expect(find.text('Minibar'), findsOneWidget);
    expect(find.text('−50.000 ₫'), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('bill-total'))).data,
      '1.340.000 ₫',
    );
    expect(find.byKey(const Key('checkout-open-orders')), findsOneWidget);
    expect(setup.checkout.creates, isEmpty, reason: 'nothing sent yet');

    await tester.tap(find.byKey(const Key('star-4')));
    await tester.enterText(
      find.byKey(const Key('checkout-note')),
      '  Phòng sạch  ',
    );
    await scrollTo(tester, find.byKey(const Key('checkout-submit')));
    await tester.tap(find.byKey(const Key('checkout-submit')));
    await tester.pumpAndSettle();

    expect(setup.checkout.creates.single.rating, 4);
    expect(setup.checkout.creates.single.note, '  Phòng sạch  ');
    expect(find.text('Đang chờ Lễ tân đối soát'), findsOneWidget);
    expect(find.byKey(const Key('checkout-progress')), findsOneWidget);

    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('checkout-status-card')), findsOneWidget);
    expect(find.byKey(const Key('tile-express-checkout')), findsNothing);
    expect(
      tileSubtitle('tile-order-food', 'Tạm khóa trong khi chờ trả phòng'),
      findsOneWidget,
    );
    expect(
      tileSubtitle('tile-housekeeping', 'Tạm khóa trong khi chờ trả phòng'),
      findsOneWidget,
    );
  });

  testWidgets('tapping a star twice clears the rating', (tester) async {
    final setup = await pumpApp(tester);
    await scrollTo(tester, find.byKey(const Key('tile-express-checkout')));
    await tester.tap(find.byKey(const Key('tile-express-checkout')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('star-3')));
    await tester.pump();
    expect(find.byIcon(Icons.star), findsNWidgets(3));
    await tester.tap(find.byKey(const Key('star-3')));
    await tester.pump();
    expect(find.byIcon(Icons.star), findsNothing);
    await scrollTo(tester, find.byKey(const Key('checkout-submit')));
    await tester.tap(find.byKey(const Key('checkout-submit')));
    await tester.pumpAndSettle();
    expect(setup.checkout.creates.single.rating, isNull);
  });

  testWidgets('a request already sent elsewhere (409) opens that request', (
    tester,
  ) async {
    final setup = await pumpApp(tester);
    setup.checkout.createFailure = apiError(409, 'STAY_CHECKOUT_PENDING');
    await scrollTo(tester, find.byKey(const Key('tile-express-checkout')));
    await tester.tap(find.byKey(const Key('tile-express-checkout')));
    await tester.pumpAndSettle();
    setup.checkout.currentResult = checkoutRequest('CHECKOUT_REQUESTED');
    await scrollTo(tester, find.byKey(const Key('checkout-submit')));
    await tester.tap(find.byKey(const Key('checkout-submit')));
    await tester.pumpAndSettle();
    expect(find.text('Đang chờ Lễ tân đối soát'), findsOneWidget);
  });

  testWidgets('a failed send stays on the screen with a message', (
    tester,
  ) async {
    final setup = await pumpApp(tester);
    setup.checkout.createFailure = apiError(0, 'NETWORK_ERROR');
    await scrollTo(tester, find.byKey(const Key('tile-express-checkout')));
    await tester.tap(find.byKey(const Key('tile-express-checkout')));
    await tester.pumpAndSettle();
    await scrollTo(tester, find.byKey(const Key('checkout-submit')));
    await tester.tap(find.byKey(const Key('checkout-submit')));
    await tester.pumpAndSettle();
    expect(
      find.text('Không gửi được yêu cầu, vui lòng thử lại.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('checkout-submit')), findsOneWidget);
  });

  testWidgets('the verified bill notification opens the frozen bill', (
    tester,
  ) async {
    final setup = await pumpApp(
      tester,
      status: 'CHECKOUT_PENDING',
      current: checkoutRequest('CHECKOUT_REQUESTED'),
    );
    setup.checkout.currentResult = checkoutRequest(
      'BILLING_VERIFIED',
      frozen: bill(estimate: false),
    );
    setup.push.taps.add(checkoutPush);
    await tester.pumpAndSettle();

    expect(find.text('Hóa đơn đã sẵn sàng'), findsOneWidget);
    expect(find.text('Hóa đơn đã chốt'), findsOneWidget);
    expect(find.text('Tạm tính — Lễ tân sẽ đối soát'), findsNothing);
    expect(
      tester.widget<Text>(find.byKey(const Key('bill-total'))).data,
      '1.340.000 ₫',
    );
  });

  testWidgets('a rejected request shows the reason and unlocks the app', (
    tester,
  ) async {
    final setup = await pumpApp(
      tester,
      status: 'CHECKOUT_PENDING',
      current: checkoutRequest('CHECKOUT_REQUESTED'),
    );
    // Reception rejects it: the stay is ACTIVE again.
    setup.checkout.currentResult = checkoutRequest(
      'REJECTED',
      reason: 'Còn nợ minibar',
    );
    setup.stays.meResult = stayWith();
    setup.push.taps.add(
      const PushPayload(type: 'CHECKOUT', entityId: requestId, status: 'X'),
    );
    await tester.pumpAndSettle();

    expect(find.text('Yêu cầu chưa được duyệt'), findsOneWidget);
    expect(find.text('Lý do: Còn nợ minibar'), findsOneWidget);
    await tester.tap(find.byKey(const Key('checkout-back-home')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('checkout-status-card')), findsNothing);
    expect(
      find.text('Yêu cầu trước chưa được duyệt: Còn nợ minibar'),
      findsOneWidget,
    );
    expect(
      tileSubtitle('tile-order-food', 'Thực đơn phục vụ tại phòng'),
      findsOneWidget,
    );
  });

  testWidgets('after reception completes it, the next call gets 401 '
      'STAY_CLOSED and the guest sees the thank-you', (tester) async {
    final setup = await pumpApp(
      tester,
      status: 'CHECKOUT_PENDING',
      current: checkoutRequest(
        'BILLING_VERIFIED',
        frozen: bill(estimate: false),
      ),
    );
    expect(find.byKey(const Key('checkout-status-card')), findsOneWidget);

    final closed = apiError(401, 'UNAUTHORIZED', reason: 'STAY_CLOSED');
    setup.checkout
      ..currentResult = closed
      // What ApiClient does on any 401 of an authenticated call.
      ..beforeCurrent = (result) {
        if (result == closed) {
          setup.container.read(apiClientProvider).onUnauthorized!(closed);
        }
      };
    setup.push.foreground.add(
      const IncomingPush(
        payload: PushPayload(
          type: 'CHECKOUT',
          entityId: requestId,
          status: 'COMPLETED',
        ),
        title: 'x',
        body: 'y',
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text('Cảm ơn Quý khách đã lưu trú. Hẹn gặp lại!'),
      findsOneWidget,
    );
  });
}
