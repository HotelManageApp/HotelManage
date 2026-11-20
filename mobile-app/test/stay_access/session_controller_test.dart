import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';

import 'fakes.dart';

ProviderContainer containerWith(
  FakeStayRepository repo,
  MemorySessionStore store, {
  ApiClient? api,
}) {
  final container = ProviderContainer(
    overrides: sessionOverrides(repo: repo, store: store, api: api),
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  test('starts signed out without a stored token', () async {
    final container = containerWith(FakeStayRepository(), MemorySessionStore());
    final state = await container.read(sessionProvider.future);
    expect(state, isA<SignedOut>());
  });

  test('restores a stored session through /guest/me', () async {
    final api = ApiClient.create('http://backend.test');
    final container = containerWith(
      FakeStayRepository(),
      MemorySessionStore(token: 'stored'),
      api: api,
    );
    final state = await container.read(sessionProvider.future);
    expect(state, isA<SignedIn>());
    expect((state as SignedIn).stay.roomNumber, '101');
    expect(api.token, 'stored');
  });

  test('a stored token of a closed stay signs out with a thank-you', () async {
    final store = MemorySessionStore(token: 'stored');
    final container = containerWith(
      FakeStayRepository(
        meResult: apiError(401, 'UNAUTHORIZED', reason: 'STAY_CLOSED'),
      ),
      store,
    );
    final state = await container.read(sessionProvider.future);
    expect((state as SignedOut).reason, SignedOutReason.stayClosed);
    expect(store.token, isNull);
  });

  test('login stores the token and sends device id and language', () async {
    final repo = FakeStayRepository();
    final store = MemorySessionStore();
    final api = ApiClient.create('http://backend.test');
    final container = containerWith(repo, store, api: api);
    await container.read(sessionProvider.future);

    await container
        .read(sessionProvider.notifier)
        .login('K7M29XPQ', lang: 'en');

    expect(repo.logins.single, {
      'code': 'K7M29XPQ',
      'deviceId': 'test-device-0001',
      'lang': 'en',
    });
    expect(store.token, 'tok-1');
    expect(api.token, 'tok-1');
    expect(container.read(sessionProvider).value, isA<SignedIn>());
  });

  test('a failed login keeps the guest signed out and rethrows', () async {
    final container = containerWith(
      FakeStayRepository(loginResult: apiError(401, 'UNAUTHORIZED')),
      MemorySessionStore(),
    );
    await container.read(sessionProvider.future);
    await expectLater(
      container.read(sessionProvider.notifier).login('K7M29XPQ', lang: 'vi'),
      throwsA(isA<AppException>()),
    );
    expect(container.read(sessionProvider).value, isA<SignedOut>());
  });

  test('logout clears the token even if the request fails', () async {
    final store = MemorySessionStore(token: 'stored');
    final repo = FakeStayRepository();
    final container = containerWith(repo, store);
    await container.read(sessionProvider.future);

    await container.read(sessionProvider.notifier).logout();

    expect(repo.logouts, 1);
    expect(store.token, isNull);
    expect(container.read(sessionProvider).value, isA<SignedOut>());
  });

  test('any 401 from an authenticated call signs the guest out', () async {
    final store = MemorySessionStore(token: 'stored');
    final api = ApiClient.create('http://backend.test');
    final container = containerWith(FakeStayRepository(), store, api: api);
    await container.read(sessionProvider.future);

    api.onUnauthorized!(apiError(401, 'UNAUTHORIZED', reason: 'CODE_REISSUED'));
    await Future<void>.delayed(Duration.zero);

    final state = container.read(sessionProvider).value;
    expect((state! as SignedOut).reason, SignedOutReason.sessionEnded);
    expect(store.token, isNull);
    expect(api.token, isNull);
  });
}
