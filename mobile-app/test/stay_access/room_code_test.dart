import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/features/stay_access/room_code.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';

void main() {
  group('normalizeRoomCode', () {
    test('accepts friendly input', () {
      expect(normalizeRoomCode('k7m2-9xpq'), 'K7M29XPQ');
      expect(normalizeRoomCode(' K7M2 9XPQ '), 'K7M29XPQ');
    });

    test('rejects impossible codes', () {
      for (final raw in ['', 'K7M2', 'K7M29XPQA', 'K7M2-9XP0', 'ABCDEFGI']) {
        expect(normalizeRoomCode(raw), isNull, reason: raw);
      }
    });
  });

  test('roomCodeFromQr only accepts check-in slip QR codes', () {
    expect(roomCodeFromQr('hotelapp://login?code=K7M29XPQ'), 'K7M29XPQ');
    expect(roomCodeFromQr('https://evil.test/?code=K7M29XPQ'), isNull);
    expect(roomCodeFromQr('hotelapp://login?code=nope'), isNull);
    expect(roomCodeFromQr('K7M29XPQ'), isNull);
  });

  test('formatter upper-cases, filters and inserts the dash', () {
    final formatter = RoomCodeInputFormatter();
    TextEditingValue type(String text) => formatter.formatEditUpdate(
      TextEditingValue.empty,
      TextEditingValue(text: text),
    );

    expect(type('k7m2').text, 'K7M2');
    expect(type('k7m29x').text, 'K7M2-9X');
    expect(type('k7m2 9x0pq1l').text, 'K7M2-9XPQ');
    expect(type('k7m29xpqzzz').text, 'K7M2-9XPQ');
    expect(type('k7m29x').selection.baseOffset, 7);
  });

  test('device ids are random and match the backend pattern', () {
    final ids = {for (var i = 0; i < 100; i++) newDeviceId()};
    expect(ids, hasLength(100));
    expect(ids.every(RegExp(r'^[A-Za-z0-9]{32}$').hasMatch), isTrue);
    expect(newDeviceId(Random(1)), newDeviceId(Random(1)));
  });

  test('memory store keeps one device id and clears the token', () async {
    final store = MemorySessionStore(token: 't');
    expect(await store.deviceId(), await store.deviceId());
    await store.clearToken();
    expect(await store.readToken(), isNull);
  });
}
