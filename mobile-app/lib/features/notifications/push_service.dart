import 'package:hotel_guest/features/notifications/push_payload.dart';

/// A push that arrived while the app was in the foreground.
class IncomingPush {
  const new({required this.payload, this.title, this.body});

  final PushPayload payload;

  /// Already in the guest's language (the backend picks the template).
  final String? title;
  final String? body;
}

/// What the app needs from the push platform (Firebase + local
/// notifications). Kept small so the controller can be tested with a fake.
abstract interface class PushService {
  /// Asks for permission to show notifications (Android 13+). True if the
  /// guest allowed it.
  Future<bool> requestPermission();

  /// Registers this app instance with FCM. The resulting ID arrives on
  /// [registrations].
  Future<void> register();

  /// The Firebase Installation ID (FID) the backend sends pushes to; emitted
  /// after [register] and again whenever Firebase replaces it.
  Stream<String> get registrations;

  /// Pushes received while the app is open; the system does not show these.
  Stream<IncomingPush> get foregroundMessages;

  /// Notifications the guest tapped while the app was running or in the
  /// background.
  Stream<PushPayload> get opened;

  /// The notification whose tap started the app, if any.
  Future<PushPayload?> launchPayload();

  /// Shows a foreground push in the `requests` channel.
  Future<void> show(IncomingPush push);
}

/// Used when Firebase is not configured on this build (no
/// google-services.json): the app works without push and relies on screens
/// refreshing themselves.
class DisabledPushService implements PushService {
  const new();

  @override
  Future<bool> requestPermission() async => false;

  @override
  Future<void> register() async {}

  @override
  Stream<String> get registrations => const Stream.empty();

  @override
  Stream<IncomingPush> get foregroundMessages => const Stream.empty();

  @override
  Stream<PushPayload> get opened => const Stream.empty();

  @override
  Future<PushPayload?> launchPayload() async => null;

  @override
  Future<void> show(IncomingPush push) async {}
}
