import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/features/concierge/chat_controller.dart';
import 'package:hotel_guest/features/concierge/chat_text.dart';

void main() {
  group('isAllowedLink', () {
    test('only https map links', () {
      expect(isAllowedLink('https://maps.google.com/?q=Ben+Thanh'), isTrue);
      expect(isAllowedLink('https://maps.app.goo.gl/abc'), isTrue);
      expect(isAllowedLink('http://maps.google.com/?q=x'), isFalse);
      expect(isAllowedLink('https://maps.google.com.evil.io/x'), isFalse);
      expect(
        isAllowedLink('https://evil.example.com/maps.google.com'),
        isFalse,
      );
      expect(isAllowedLink('https://user@maps.google.com/x'), isFalse);
      expect(isAllowedLink('javascript:alert(1)'), isFalse);
      expect(isAllowedLink('tel:0900000000'), isFalse);
    });
  });

  group('parseChatText', () {
    test('bullets, bold and allowed links', () {
      final lines = parseChatText(
        'Gợi ý:\n- **Chợ Bến Thành** — [bản đồ](https://maps.google.com/?q=bt)\n'
        '* Phở Hòa https://maps.app.goo.gl/x',
      );
      expect(lines, hasLength(3));
      expect(lines[0].bullet, isFalse);
      expect(lines[1].bullet, isTrue);
      expect(lines[1].pieces, [
        const TextPiece('Chợ Bến Thành', bold: true),
        const TextPiece(' — '),
        const TextPiece('bản đồ', link: 'https://maps.google.com/?q=bt'),
      ]);
      expect(lines[2].pieces.last.link, 'https://maps.app.goo.gl/x');
    });

    test('other links stay plain text, with the address visible', () {
      final lines = parseChatText(
        'Xem [ưu đãi](https://evil.example.com/win) hoặc https://evil.example.com',
      );
      expect(lines.single.pieces.where((p) => p.link != null), isEmpty);
      expect(
        lines.single.pieces.map((p) => p.text).join(),
        'Xem ưu đãi (https://evil.example.com/win) hoặc https://evil.example.com',
      );
    });

    test('numbered lists count as bullets; other markdown is shown as is', () {
      expect(parseChatText('1. Hồ bơi').single.bullet, isTrue);
      expect(parseChatText('# Tiêu đề').single.pieces.single.text, '# Tiêu đề');
    });
  });

  test('client message ids are UUID v4', () {
    final id = newClientMessageId();
    expect(
      id,
      matches(
        RegExp(
          '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-'
          r'[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ),
      ),
    );
    expect(newClientMessageId(), isNot(id));
  });
}
