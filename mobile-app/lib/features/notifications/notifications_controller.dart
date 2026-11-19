import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';

/// Overridden in `main.dart` with the started Firebase service.
final pushServiceProvider = Provider<PushService>(
  (ref) => const DisabledPushService(),
);

/// `PUT /api/v1/guest/me/fcm-token` (SPEC-notifications). The value is the
/// device's Firebase Installation ID, which FCM now uses as the push target.
class NotificationsRepository {
  const new(this._api);

  final ApiClient _api;

  Future<void> registerPushId(String pushId) =>
      _api.put('/api/v1/guest/me/fcm-token', body: {'fcm_token': pushId});
}

final notificationsRepositoryProvider = Provider<NotificationsRepository>(
  (ref) => NotificationsRepository(ref.watch(apiClientProvider)),
);

/// A route the app should open because the guest tapped a notification.
/// The app shell consumes it and clears it.
class PendingRoute extends Notifier<String?> {
  @override
  String? build() => null;

  String? get route => state;
  set route(String? value) => state = value;
}

final pendingRouteProvider = NotifierProvider<PendingRoute, String?>(
  PendingRoute.new,
);

/// Wires push to the session:
/// - after sign-in, asks for permission, registers with FCM and sends the
///   device's push ID to the backend (again whenever Firebase replaces it);
/// - shows pushes that arrive while the app is open;
/// - turns a tapped notification into a route.
///
/// Its state is the latest status push. Screens that show requests watch it
/// and reload when a push about their type arrives.
class NotificationsController extends Notifier<PushPayload?> {
  PushService get _push => ref.read(pushServiceProvider);

  /// Latest ID from Firebase, and the one the backend has for this session.
  String? _latest;
  String? _registered;

  @override
  PushPayload? build() {
    final push = ref.watch(pushServiceProvider);
    final subscriptions = [
      push.foregroundMessages.listen(_onForeground),
      push.opened.listen(_onOpened),
      push.registrations.listen((pushId) {
        _latest = pushId;
        unawaited(_register(pushId));
      }),
    ];
    ref
      ..onDispose(() {
        for (final subscription in subscriptions) {
          unawaited(subscription.cancel());
        }
      })
      ..listen(sessionProvider, (previous, next) {
        final wasSignedIn = previous?.value is SignedIn;
        final isSignedIn = next.value is SignedIn;
        if (isSignedIn && !wasSignedIn) unawaited(_onSignedIn());
        if (!isSignedIn) _registered = null;
      }, fireImmediately: true);
    unawaited(
      push.launchPayload().then((payload) {
        if (payload != null) _onOpened(payload);
      }),
    );
    return null;
  }

  /// Every push is news, even one equal to the previous (the same status
  /// twice, or a tap on a push that was shown in the foreground).
  @override
  bool updateShouldNotify(PushPayload? previous, PushPayload? next) => true;

  Future<void> _onSignedIn() async {
    if (!await _push.requestPermission()) return;
    final known = _latest;
    if (known != null) await _register(known);
    await _push.register();
  }

  Future<void> _register(String pushId) async {
    if (ref.read(sessionProvider).value is! SignedIn) return;
    if (pushId == _registered) return;
    try {
      await ref.read(notificationsRepositoryProvider).registerPushId(pushId);
      _registered = pushId;
    } on AppException {
      // Not fatal: screens still refresh on their own. A 401 already signs
      // the guest out through the API client.
    }
  }

  void _onForeground(IncomingPush push) {
    unawaited(_push.show(push));
    state = push.payload;
  }

  void _onOpened(PushPayload payload) {
    state = payload;
    ref.read(pendingRouteProvider.notifier).route = payload.route;
  }
}

final notificationsProvider =
    NotifierProvider<NotificationsController, PushPayload?>(
      NotificationsController.new,
    );

/// Reloads [ref]'s provider whenever a push about [type] arrives, so open
/// screens follow staff updates without waiting for their 15 s refresh.
void reloadOnPush(Ref ref, String type) {
  ref.listen(notificationsProvider, (_, payload) {
    if (payload?.type == type) ref.invalidateSelf();
  });
}
