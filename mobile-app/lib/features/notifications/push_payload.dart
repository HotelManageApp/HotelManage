import 'dart:convert';

import 'package:flutter/foundation.dart';

/// The `data` part of a push (SPEC-notifications): which request changed and
/// its new status. It never carries a room number, name, price or token.
@immutable
class PushPayload {
  const new({
    required this.type,
    required this.entityId,
    required this.status,
    this.titleKey,
  });

  /// Returns null for anything that is not one of our status pushes.
  static PushPayload? fromData(Map<String, dynamic> data) {
    final type = data['type'];
    final entityId = data['entity_id'];
    final status = data['status'];
    if (type is! String || entityId is! String || status is! String) {
      return null;
    }
    if (!knownTypes.contains(type) || !_id.hasMatch(entityId)) return null;
    final titleKey = data['title_key'];
    return PushPayload(
      type: type,
      entityId: entityId,
      status: status,
      titleKey: titleKey is String ? titleKey : null,
    );
  }

  /// The payload stored with a notification shown while the app was open.
  static PushPayload? fromJsonString(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map
          ? fromData(Map<String, dynamic>.from(decoded))
          : null;
    } on FormatException {
      return null;
    }
  }

  static const knownTypes = {'FOOD_ORDER', 'HOUSEKEEPING', 'CHECKOUT', 'STAY'};
  static final _id = RegExp(r'^[0-9a-fA-F-]{8,64}$');

  final String type;
  final String entityId;
  final String status;
  final String? titleKey;

  Map<String, String> toData() => {
    'type': type,
    'entity_id': entityId,
    'status': status,
    'title_key': ?titleKey,
  };

  String toJsonString() => jsonEncode(toData());

  /// Where tapping the notification leads. A stay-level push (welcome,
  /// thank-you) has no detail screen and opens the home screen.
  String get route =>
      type == 'STAY' ? '/home' : '/requests/${type.toLowerCase()}/$entityId';

  @override
  bool operator ==(Object other) =>
      other is PushPayload &&
      other.type == type &&
      other.entityId == entityId &&
      other.status == status &&
      other.titleKey == titleKey;

  @override
  int get hashCode => Object.hash(type, entityId, status, titleKey);
}
