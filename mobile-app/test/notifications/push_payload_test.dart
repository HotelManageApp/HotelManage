import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/features/notifications/push_payload.dart';

import 'fakes.dart';

void main() {
  group('PushPayload.fromData', () {
    test('reads a status push', () {
      final payload = PushPayload.fromData({
        'type': 'HOUSEKEEPING',
        'entity_id': '6f1c2a3b-0000-4000-8000-000000000002',
        'status': 'IN_PROGRESS',
        'title_key': 'housekeeping.IN_PROGRESS',
        'occurred_at': '2026-11-19T07:30:00Z',
      });
      expect(payload?.type, 'HOUSEKEEPING');
      expect(payload?.status, 'IN_PROGRESS');
      expect(payload?.titleKey, 'housekeeping.IN_PROGRESS');
    });

    test('ignores pushes that are not ours or look tampered with', () {
      final valid = orderPayload.toData();
      expect(PushPayload.fromData({...valid, 'type': 'PROMO'}), isNull);
      expect(
        PushPayload.fromData({...valid, 'entity_id': '../../admin'}),
        isNull,
      );
      expect(PushPayload.fromData({...valid}..remove('status')), isNull);
      expect(PushPayload.fromData(const {}), isNull);
    });
  });

  test('survives the round trip through a local notification payload', () {
    expect(
      PushPayload.fromJsonString(orderPayload.toJsonString()),
      orderPayload,
    );
    expect(PushPayload.fromJsonString('not json'), isNull);
    expect(PushPayload.fromJsonString('[1, 2]'), isNull);
    expect(PushPayload.fromJsonString(null), isNull);
  });

  test('routes to the request, or home for stay-level pushes', () {
    expect(orderPayload.route, '/requests/food_order/${orderPayload.entityId}');
    const thanks = PushPayload(
      type: 'STAY',
      entityId: '6f1c2a3b-0000-4000-8000-000000000003',
      status: 'CLOSED',
    );
    expect(thanks.route, '/home');
  });
}
