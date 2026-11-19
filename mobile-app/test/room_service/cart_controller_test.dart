import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';
import 'package:hotel_guest/features/stay_access/token_claims.dart';

import '../stay_access/fakes.dart';
import 'fakes.dart';

const AppException network = networkError;

class Harness {
  new({String? storedToken, MemoryCartStore? cartStore, this.stays})
    : carts = cartStore ?? MemoryCartStore(),
      repo = FakeRoomServiceRepository() {
    container = ProviderContainer(
      overrides: [
        ...sessionOverrides(
          repo: stays ?? FakeStayRepository(),
          store: MemorySessionStore(token: storedToken),
        ),
        cartStoreProvider.overrideWithValue(carts),
        roomServiceRepositoryProvider.overrideWithValue(repo),
      ],
    );
    addTearDown(container.dispose);
    container.listen(cartProvider, (_, _) {});
  }

  final MemoryCartStore carts;
  final FakeRoomServiceRepository repo;
  final FakeStayRepository? stays;
  late final ProviderContainer container;

  CartController get cart => container.read(cartProvider.notifier);
  CartState get state => container.read(cartProvider);

  Future<void> signedIn() async {
    await container.read(sessionProvider.future);
    await pumpEventQueue();
  }
}

Map<String, dynamic> saved(String? raw) =>
    Map<String, dynamic>.from(jsonDecode(raw!) as Map);

void main() {
  test('reads stay_id from the token, and nothing from a non-JWT', () {
    expect(stayIdFromToken(tokenFor('stay-A')), 'stay-A');
    expect(stayIdFromToken('opaque'), isNull);
    expect(stayIdFromToken('a.!!!.c'), isNull);
    expect(stayIdFromToken(null), isNull);
  });

  group('editing', () {
    test('adding the same dish again merges into one line', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart
        ..add(pho)
        ..add(coffee)
        ..add(pho);
      expect(h.state.lines.map((l) => l.itemId), ['item-pho', 'item-coffee']);
      expect(h.state.quantityOf('item-pho'), 2);
      expect(h.state.itemCount, 3);
      expect(h.state.estimatedTotalVnd, 2 * 65000 + 35000);
    });

    test('quantities stop at 20 and reaching 0 removes the line', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart.add(pho);
      for (var i = 1; i < maxQuantity; i++) {
        expect(h.cart.increment('item-pho'), isTrue);
      }
      expect(h.cart.increment('item-pho'), isFalse);
      expect(h.state.quantityOf('item-pho'), maxQuantity);

      h.cart.add(coffee);
      h.cart.decrement('item-coffee');
      expect(h.state.quantityOf('item-coffee'), 0);
      expect(h.state.lines, hasLength(1));
    });

    test('notes are trimmed per dish and for the order', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart
        ..add(pho)
        ..setNote('item-pho', '  ít cay ')
        ..setOrderNote(' Gõ cửa nhẹ ');
      expect(h.state.lines.single.note, 'ít cay');
      expect(h.state.orderNote, 'Gõ cửa nhẹ');
    });
  });

  group('kept per stay', () {
    test('survives a restart of the same stay', () async {
      final store = MemoryCartStore();
      final first = Harness(storedToken: tokenFor('stay-A'), cartStore: store);
      await first.signedIn();
      first.cart
        ..add(pho)
        ..setNote('item-pho', 'ít cay');
      await pumpEventQueue();
      expect(saved(store.value)['stay_id'], 'stay-A');

      final again = Harness(storedToken: tokenFor('stay-A'), cartStore: store);
      await again.signedIn();
      expect(again.state.lines.single.note, 'ít cay');
    });

    test('a cart from another stay is dropped', () async {
      final store = MemoryCartStore();
      final first = Harness(storedToken: tokenFor('stay-A'), cartStore: store);
      await first.signedIn();
      first.cart.add(pho);
      await pumpEventQueue();

      final next = Harness(storedToken: tokenFor('stay-B'), cartStore: store);
      await next.signedIn();
      expect(next.state.isEmpty, isTrue);
      expect(store.value, isNull);
    });

    test('signing out empties the cart and the saved copy', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart.add(pho);
      await pumpEventQueue();
      await h.container.read(sessionProvider.notifier).logout();
      await pumpEventQueue();
      expect(h.state.isEmpty, isTrue);
      expect(h.carts.value, isNull);
    });

    test('a new login loads the cart of that stay', () async {
      final stays = FakeStayRepository(
        loginResult: GuestLogin(token: tokenFor('stay-C'), stay: stay101),
      );
      final store = MemoryCartStore(
        jsonEncode({
          'stay_id': 'stay-C',
          'lines': [
            {
              'item_id': 'item-pho',
              'name': 'Phở bò',
              'unit_price_vnd': 65000,
              'quantity': 2,
              'note': '',
            },
          ],
          'order_note': '',
        }),
      );
      final h = Harness(cartStore: store, stays: stays);
      await h.signedIn();
      await h.container
          .read(sessionProvider.notifier)
          .login('ABC234', lang: 'vi');
      await pumpEventQueue();
      expect(h.state.quantityOf('item-pho'), 2);
    });
  });

  group('placing', () {
    test('sends lines and notes but no prices, returns the server order and '
        'empties the cart', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart
        ..add(pho)
        ..add(pho)
        ..setNote('item-pho', 'ít cay')
        ..setOrderNote('Gõ cửa nhẹ');

      final order = await h.cart.placeOrder();

      final call = h.repo.calls.single;
      expect(call.items.single.toJson(), {
        'item_id': 'item-pho',
        'quantity': 2,
        'note': 'ít cay',
      });
      expect(call.orderNote, 'Gõ cửa nhẹ');
      expect(call.key, matches(RegExp(r'^[A-Za-z0-9_-]{8,64}$')));
      expect(order.totalVnd, 120000, reason: 'the server total, not 130000');
      expect(h.state.isEmpty, isTrue);
      await pumpEventQueue();
      expect(saved(h.carts.value)['lines'], isEmpty);
    });

    test(
      'a network failure is retried with the same Idempotency-Key',
      () async {
        final h = Harness(storedToken: tokenFor('stay-A'));
        await h.signedIn();
        h.cart.add(pho);
        h.repo.failures.add(network);

        await expectLater(h.cart.placeOrder(), throwsA(network));
        expect(h.state.placing, isFalse);
        expect(h.state.quantityOf('item-pho'), 1, reason: 'cart kept');
        await h.cart.placeOrder();

        expect(h.repo.calls, hasLength(2));
        expect(h.repo.calls[1].key, h.repo.calls[0].key);
      },
    );

    test('changing the cart or a server answer starts a new key', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.cart.add(pho);
      h.repo.failures
        ..add(network)
        ..add(apiError(409, 'KITCHEN_CLOSED'));

      await expectLater(h.cart.placeOrder(), throwsA(network));
      h.cart.add(coffee);
      await expectLater(
        h.cart.placeOrder(),
        throwsA(
          isA<AppException>().having((e) => e.code, 'code', 'KITCHEN_CLOSED'),
        ),
      );
      await h.cart.placeOrder();

      final keys = h.repo.calls.map((c) => c.key).toList();
      expect(keys.toSet(), hasLength(3));
    });

    test('ITEM_UNAVAILABLE marks the dishes and reloads the menu', () async {
      final h = Harness(storedToken: tokenFor('stay-A'));
      await h.signedIn();
      h.container.listen(menuProvider, (_, _) {});
      await h.container.read(menuProvider.future);
      final loads = h.repo.menuLoads;
      h.cart
        ..add(pho)
        ..add(coffee);
      h.repo.failures.add(itemUnavailable(['item-coffee']));

      await expectLater(h.cart.placeOrder(), throwsA(isA<AppException>()));
      expect(h.state.unavailable, {'item-coffee'});
      await h.container.read(menuProvider.future);
      expect(h.repo.menuLoads, greaterThan(loads));

      h.cart.remove('item-coffee');
      expect(h.state.unavailable, isEmpty);
    });
  });
}
