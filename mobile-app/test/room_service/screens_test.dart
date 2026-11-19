import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';
import 'package:material_ui/material_ui.dart';

import '../stay_access/fakes.dart';
import 'fakes.dart';

Future<FakeRoomServiceRepository> openMenu(
  WidgetTester tester, {
  FakeRoomServiceRepository? repo,
  GuestStay? stay,
}) async {
  final fake = repo ?? FakeRoomServiceRepository();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: FakeStayRepository(meResult: stay ?? stay101),
          store: MemorySessionStore(token: tokenFor('stay-A')),
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(fake),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('tile-order-food')));
  await tester.pumpAndSettle();
  return fake;
}

Finder addButton(String name) => find.byTooltip('Thêm $name');

void main() {
  testWidgets('shows the menu by category with sold-out dishes greyed out', (
    tester,
  ) async {
    await openMenu(tester);

    expect(find.text('Tất cả'), findsOneWidget);
    expect(find.text('Món chính'), findsOneWidget);
    expect(find.text('Phở bò'), findsOneWidget);
    expect(find.text('65.000 ₫ · Bò tái'), findsOneWidget);
    expect(find.text('Tạm hết'), findsOneWidget);
    expect(addButton('Bún chả'), findsNothing);

    await tester.tap(find.text('Đồ uống'));
    await tester.pumpAndSettle();
    expect(find.text('Cà phê sữa'), findsOneWidget);
    expect(find.text('Phở bò'), findsNothing);
  });

  testWidgets('searches dish names', (tester) async {
    await openMenu(tester);
    await tester.enterText(find.byKey(const Key('menu-search')), 'cà phê');
    await tester.pumpAndSettle();
    expect(find.text('Cà phê sữa'), findsOneWidget);
    expect(find.text('Phở bò'), findsNothing);
    await tester.enterText(find.byKey(const Key('menu-search')), 'pizza');
    await tester.pumpAndSettle();
    expect(find.text('Không có món phù hợp'), findsOneWidget);
  });

  testWidgets('outside service hours shows the hours and takes no orders', (
    tester,
  ) async {
    await openMenu(
      tester,
      repo: FakeRoomServiceRepository(menu: menuOf(open: false)),
    );
    expect(
      find.text('Bếp mở cửa 06:00–22:00. Hiện chưa nhận đơn.'),
      findsOneWidget,
    );
    expect(addButton('Phở bò'), findsNothing);
  });

  testWidgets('a stay waiting for check-out cannot order', (tester) async {
    await openMenu(
      tester,
      stay: GuestStay(
        roomNumber: '101',
        guestName: null,
        expectedCheckoutAt: DateTime.utc(2026, 11, 21, 5),
        status: 'CHECKOUT_PENDING',
      ),
    );
    expect(
      find.text('Quý khách đang chờ trả phòng nên không đặt thêm món được.'),
      findsOneWidget,
    );
    expect(addButton('Phở bò'), findsNothing);
  });

  testWidgets('orders from the cart and shows the total the server returned', (
    tester,
  ) async {
    final repo = await openMenu(tester);

    await tester.tap(addButton('Phở bò'));
    await tester.pumpAndSettle();
    await tester.tap(addButton('Phở bò'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('qty-item-pho')), findsOneWidget);
    expect(find.text('Giỏ hàng (2)'), findsOneWidget);

    await tester.tap(find.byKey(const Key('open-cart')));
    await tester.pumpAndSettle();
    expect(find.text('Tạm tính: 130.000 ₫'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('note-item-pho')), 'ít cay');
    await tester.tap(find.byKey(const Key('place-order')));
    await tester.pumpAndSettle();

    expect(repo.calls.single.items.single.note, 'ít cay');
    expect(
      tester.widget<Text>(find.byKey(const Key('placed-total'))).data,
      'Tổng cộng: 120.000 ₫',
    );
    await tester.tap(find.text('Đóng'));
    await tester.pumpAndSettle();
    // The new order's detail, with the server's total.
    expect(find.text('Chờ Bếp xác nhận'), findsWidgets);
    expect(
      tester.widget<Text>(find.byKey(const Key('order-total'))).data,
      'Tổng cộng: 120.000 ₫',
    );
  });

  testWidgets('dishes that sold out meanwhile are marked and block ordering', (
    tester,
  ) async {
    final repo = await openMenu(tester);
    await tester.tap(addButton('Phở bò'));
    await tester.tap(addButton('Cà phê sữa'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-cart')));
    await tester.pumpAndSettle();

    repo.failures.add(itemUnavailable(['item-coffee']));
    await tester.tap(find.byKey(const Key('place-order')));
    await tester.pumpAndSettle();

    expect(
      find.text('Một số món vừa hết, đã đánh dấu trong giỏ.'),
      findsOneWidget,
    );
    expect(
      find.text('Món này hiện không phục vụ, vui lòng bỏ khỏi giỏ'),
      findsOneWidget,
    );
    final place = tester.widget<FilledButton>(
      find.byKey(const Key('place-order')),
    );
    expect(place.onPressed, isNull);

    await tester.tap(find.byTooltip('Bỏ Cà phê sữa'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('place-order')))
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('a lost connection says the retry is safe', (tester) async {
    final repo = await openMenu(tester);
    await tester.tap(addButton('Phở bò'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-cart')));
    await tester.pumpAndSettle();

    repo.failures.add(networkError);
    await tester.tap(find.byKey(const Key('place-order')));
    await tester.pumpAndSettle();
    expect(find.textContaining('không bị gửi trùng'), findsOneWidget);
    expect(find.text('Phở bò'), findsOneWidget, reason: 'cart kept');
  });
}
