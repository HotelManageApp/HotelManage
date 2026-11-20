import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';

import '../stay_access/fakes.dart';
import 'fakes.dart';

class Harness {
  new({FakePushService? push, String? storedToken, FakeStayRepository? stays})
    : push = push ?? FakePushService(),
      repo = FakeNotificationsRepository() {
    container = ProviderContainer(
      overrides: [
        ...sessionOverrides(
          repo: stays ?? FakeStayRepository(),
          store: MemorySessionStore(token: storedToken),
        ),
        pushServiceProvider.overrideWithValue(this.push),
        notificationsRepositoryProvider.overrideWithValue(repo),
      ],
    );
    addTearDown(container.dispose);
    container.listen(notificationsProvider, (_, _) {});
  }

  final FakePushService push;
  final FakeNotificationsRepository repo;
  late final ProviderContainer container;

  Future<void> settle() => pumpEventQueue();
}

void main() {
  test('registers the push ID with the backend after sign-in', () async {
    final h = Harness();
    await h.container.read(sessionProvider.future);
    await h.settle();
    expect(h.push.permissionRequests, 0, reason: 'nothing before sign-in');

    await h.container
        .read(sessionProvider.notifier)
        .login('ABC234', lang: 'vi');
    await h.settle();
    expect(h.push.permissionRequests, 1);
    expect(h.repo.registered, ['fid-device-1234567890ab']);
  });

  test('a restored session registers too', () async {
    final h = Harness(storedToken: 'stored');
    await h.container.read(sessionProvider.future);
    await h.settle();
    expect(h.repo.registered, ['fid-device-1234567890ab']);
  });

  test('does not register when the guest refuses notifications', () async {
    final h = Harness(push: FakePushService(allow: false), storedToken: 's');
    await h.container.read(sessionProvider.future);
    await h.settle();
    expect(h.push.registers, 0);
    expect(h.repo.registered, isEmpty);
  });

  test('sends a replaced push ID again, and the same one only once', () async {
    final h = Harness(storedToken: 'stored');
    await h.container.read(sessionProvider.future);
    await h.settle();

    h.push.registrationsController
      ..add('fid-device-1234567890ab')
      ..add('fid-device-new-0987654321');
    await h.settle();
    expect(h.repo.registered, [
      'fid-device-1234567890ab',
      'fid-device-new-0987654321',
    ]);
  });

  test('ignores ID changes while signed out', () async {
    final h = Harness();
    await h.container.read(sessionProvider.future);
    h.push.registrationsController.add('fid-device-while-out-1234');
    await h.settle();
    expect(h.repo.registered, isEmpty);
  });

  test('a failed registration is retried on the next ID', () async {
    final h = Harness()..repo.failWith = apiError(503, 'UNAVAILABLE');
    await h.container.read(sessionProvider.future);
    await h.container
        .read(sessionProvider.notifier)
        .login('ABC234', lang: 'vi');
    await h.settle();
    expect(h.repo.registered, isEmpty);

    h.repo.failWith = null;
    h.push.registrationsController.add('fid-device-1234567890ab');
    await h.settle();
    expect(h.repo.registered, ['fid-device-1234567890ab']);
  });

  test('registers again for the next stay on the same phone', () async {
    final h = Harness(storedToken: 'stored');
    await h.container.read(sessionProvider.future);
    await h.settle();
    await h.container.read(sessionProvider.notifier).logout();
    await h.container
        .read(sessionProvider.notifier)
        .login('XYZ789', lang: 'en');
    await h.settle();
    expect(h.repo.registered, [
      'fid-device-1234567890ab',
      'fid-device-1234567890ab',
    ]);
  });

  test(
    'shows a foreground push and publishes it for screens to reload',
    () async {
      final h = Harness(storedToken: 'stored');
      await h.container.read(sessionProvider.future);
      const push = IncomingPush(
        payload: orderPayload,
        title: 'Bếp đang nấu',
        body: 'Món của Quý khách đang được chế biến.',
      );
      h.push.foreground.add(push);
      await h.settle();
      expect(h.push.shown.single.title, 'Bếp đang nấu');
      expect(h.container.read(notificationsProvider), orderPayload);
      expect(h.container.read(pendingRouteProvider), isNull);
    },
  );

  test('a tapped notification asks the app to open its request', () async {
    final h = Harness(storedToken: 'stored');
    await h.container.read(sessionProvider.future);
    h.push.taps.add(orderPayload);
    await h.settle();
    expect(
      h.container.read(pendingRouteProvider),
      '/requests/food_order/${orderPayload.entityId}',
    );
  });

  test('the notification that launched the app is opened once', () async {
    final h = Harness(push: FakePushService(launch: orderPayload));
    await h.settle();
    expect(h.container.read(pendingRouteProvider), orderPayload.route);
  });

  test('the disabled service never registers anything', () async {
    const disabled = DisabledPushService();
    expect(await disabled.requestPermission(), isFalse);
    expect(await disabled.registrations.isEmpty, isTrue);
    expect(await disabled.launchPayload(), isNull);
  });
}
