import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/express_checkout/checkout_repository.dart';

import '../core/api_client_test.dart' show FakeAdapter, clientWith, jsonBody;

const Map<String, Object> bill = {
  'room_number': '101',
  'lines': [
    {'type': 'ROOM', 'description': 'Tiền phòng', 'amount_vnd': 1200000},
    {'type': 'DISCOUNT', 'description': 'Khách quen', 'amount_vnd': 50000},
  ],
  'total_vnd': 1150000,
  'open_orders': 0,
  'currency': 'VND',
  'generated_at': '2026-11-20T03:00:00Z',
};

void main() {
  test('sends only the confirmation, rating and trimmed note — never a room, '
      'stay or amount', () async {
    final adapter = FakeAdapter(
      (_) => jsonBody({
        'checkout_request_id': 'q1',
        'status': 'CHECKOUT_REQUESTED',
        'open_orders': 0,
        'message_key': 'checkout.awaiting_reception',
      }, 201),
    );
    final repo = CheckoutRepository(clientWith(adapter));

    expect(await repo.create(rating: 5, note: '  Tuyệt vời '), 'q1');
    expect(await repo.create(note: '   '), 'q1');

    final first = adapter.requests.first;
    expect(first.method, 'POST');
    expect(first.path, '/api/v1/guest/checkout-requests');
    expect(first.data, {
      'guest_confirmed': true,
      'feedback_rating': 5,
      'feedback_note': 'Tuyệt vời',
      'source': 'APP',
    });
    expect(adapter.requests.last.data, {
      'guest_confirmed': true,
      'source': 'APP',
    });
  });

  test(
    'reads the estimate and the verified bill as the server sent them',
    () async {
      final adapter = FakeAdapter(
        (options) => options.path.endsWith('/preview')
            ? jsonBody({...bill, 'is_estimate': true}, 200)
            : jsonBody({
                'id': 'q1',
                'status': 'BILLING_VERIFIED',
                'created_at': '2026-11-20T03:00:00Z',
                'feedback_rating': 4,
                'reject_reason': null,
                'bill': {...bill, 'is_estimate': false},
              }, 200),
      );
      final repo = CheckoutRepository(clientWith(adapter));

      final estimate = await repo.preview();
      expect(estimate.isEstimate, isTrue);
      expect(estimate.totalVnd, 1150000);
      expect(estimate.lines.last.isDiscount, isTrue);

      final request = (await repo.current())!;
      expect(request.isOpen, isTrue);
      expect(request.bill!.isEstimate, isFalse);
      expect(request.bill!.lines, hasLength(2));
    },
  );

  test('no request yet (404) is null; other errors surface', () async {
    var status = 404;
    final repo = CheckoutRepository(
      clientWith(
        FakeAdapter(
          (_) => jsonBody({
            'error': {'code': 'X', 'message': 'x', 'details': <Object>[]},
          }, status),
        ),
      ),
    );
    expect(await repo.current(), isNull);
    status = 500;
    await expectLater(
      repo.current(),
      throwsA(isA<AppException>().having((e) => e.status, 'status', 500)),
    );
  });
}
