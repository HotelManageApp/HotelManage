import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';

/// Must match `android.notification.channel_id` sent by backend-api.
const requestsChannelId = 'requests';

/// [PushService] backed by Firebase Cloud Messaging, with
/// flutter_local_notifications for pushes that arrive while the app is open.
class FirebasePushService implements PushService {
  new _(this._messaging, this._local, this._channel, this._opened);

  /// Starts Firebase; falls back to [DisabledPushService] when this build has
  /// no Firebase configuration.
  static Future<PushService> start(Locale locale) async {
    try {
      await Firebase.initializeApp();
    } on Object catch (error) {
      debugPrint('Push notifications disabled: $error');
      return const DisabledPushService();
    }

    final opened = StreamController<PushPayload>.broadcast();
    final local = FlutterLocalNotificationsPlugin();
    await local.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      ),
      onDidReceiveNotificationResponse: (response) {
        final payload = PushPayload.fromJsonString(response.payload);
        if (payload != null) opened.add(payload);
      },
    );

    final l10n = lookupAppLocalizations(locale);
    final channel = AndroidNotificationChannel(
      requestsChannelId,
      l10n.notificationChannelName,
      description: l10n.notificationChannelDescription,
      importance: Importance.high,
    );
    await local
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.createNotificationChannel(channel);

    FirebaseMessaging.onMessageOpenedApp.listen((message) {
      final payload = PushPayload.fromData(message.data);
      if (payload != null) opened.add(payload);
    });

    return FirebasePushService._(
      FirebaseMessaging.instance,
      local,
      channel,
      opened,
    );
  }

  final FirebaseMessaging _messaging;
  final FlutterLocalNotificationsPlugin _local;
  final AndroidNotificationChannel _channel;
  final StreamController<PushPayload> _opened;

  @override
  Future<bool> requestPermission() async {
    final settings = await _messaging.requestPermission();
    return settings.authorizationStatus == AuthorizationStatus.authorized ||
        settings.authorizationStatus == AuthorizationStatus.provisional;
  }

  @override
  Future<void> register() => _messaging.register();

  @override
  Stream<String> get registrations => _messaging.onRegistered;

  @override
  Stream<IncomingPush> get foregroundMessages => FirebaseMessaging.onMessage
      .map((message) {
        final payload = PushPayload.fromData(message.data);
        if (payload == null) return null;
        return IncomingPush(
          payload: payload,
          title: message.notification?.title,
          body: message.notification?.body,
        );
      })
      .where((push) => push != null)
      .cast<IncomingPush>();

  @override
  Stream<PushPayload> get opened => _opened.stream;

  @override
  Future<PushPayload?> launchPayload() async {
    final message = await _messaging.getInitialMessage();
    if (message != null) return PushPayload.fromData(message.data);
    final details = await _local.getNotificationAppLaunchDetails();
    if (details == null || !details.didNotificationLaunchApp) return null;
    return PushPayload.fromJsonString(details.notificationResponse?.payload);
  }

  @override
  Future<void> show(IncomingPush push) => _local.show(
    // One notification per request: a newer status replaces the older one.
    id: push.payload.entityId.hashCode & 0x7fffffff,
    title: push.title,
    body: push.body,
    payload: push.payload.toJsonString(),
    notificationDetails: NotificationDetails(
      android: AndroidNotificationDetails(
        _channel.id,
        _channel.name,
        channelDescription: _channel.description,
        importance: Importance.high,
        priority: Priority.high,
      ),
    ),
  );
}
