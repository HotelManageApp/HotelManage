import 'dart:async';

import 'package:hotel_guest/core/errors.dart';

import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';
import 'package:hotel_guest/features/notifications/push_service.dart';

const orderPayload = PushPayload(
  type: 'FOOD_ORDER',
  entityId: '6f1c2a3b-0000-4000-8000-000000000001',
  status: 'PREPARING',
  titleKey: 'food_order.PREPARING',
);

/// Push platform under test control.
class FakePushService implements PushService {
  new({
    this.allow = true,
    this.pushId = 'fid-device-1234567890ab',
    this.launch,
  });

  bool allow;
  String? pushId;
  PushPayload? launch;
  int permissionRequests = 0;
  int registers = 0;
  final List<IncomingPush> shown = [];

  final registrationsController = StreamController<String>.broadcast();
  final foreground = StreamController<IncomingPush>.broadcast();
  final taps = StreamController<PushPayload>.broadcast();

  @override
  Future<bool> requestPermission() async {
    permissionRequests++;
    return allow;
  }

  @override
  Future<void> register() async {
    registers++;
    final id = pushId;
    if (id != null) registrationsController.add(id);
  }

  @override
  Stream<String> get registrations => registrationsController.stream;

  @override
  Stream<IncomingPush> get foregroundMessages => foreground.stream;

  @override
  Stream<PushPayload> get opened => taps.stream;

  @override
  Future<PushPayload?> launchPayload() async => launch;

  @override
  Future<void> show(IncomingPush push) async => shown.add(push);
}

/// Records the push IDs sent to the backend; can be told to fail.
class FakeNotificationsRepository implements NotificationsRepository {
  final List<String> registered = [];
  AppException? failWith;

  @override
  Future<void> registerPushId(String pushId) async {
    final error = failWith;
    if (error != null) throw error;
    registered.add(pushId);
  }
}
