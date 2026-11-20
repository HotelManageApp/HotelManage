import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/features/concierge/chat_controller.dart';
import 'package:hotel_guest/features/concierge/chat_repository.dart';
import 'package:hotel_guest/features/housekeeping/hk_requests_screen.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/order_detail_screen.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../housekeeping/fakes.dart';
import '../room_service/fakes.dart';
import '../stay_access/fakes.dart';
import 'chat_screen_test.dart' show FakeChatRepository;

const actionId = '9f86d081884c4d63a4b5f2c0e0b5a1c3';

ChatReply summary({String kind = 'FOOD_ORDER', int? total = 170000}) =>
    ChatReply(
      messageId: 'm-summary',
      text:
          'Dạ, Quý khách kiểm tra giúp tôi.\n\nTóm tắt đơn của Quý khách:\n'
          '- Phở bò × 2: 65.000đ × 2 = 130.000đ\nTổng cộng: 170.000đ\n'
          'Quý khách xác nhận đặt đơn này chứ?',
      targets: const [],
      pending: PendingConfirmation(id: actionId, kind: kind, totalVnd: total),
    );

ChatReply created(String target, String id) => ChatReply(
  messageId: 'm-created-$id',
  text: 'Đã gửi ạ.',
  targets: const [],
  entityActions: [EntityAction(target: target, entityId: id)],
);

class Clock {
  DateTime now = DateTime(2026, 11, 20, 19);
}

Future<(FakeChatRepository, Clock)> open(
  WidgetTester tester, {
  String status = 'ACTIVE',
  List<ChatReply> answers = const [],
}) async {
  final chat = FakeChatRepository()..answers.addAll(answers);
  final clock = Clock();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: FakeStayRepository(meResult: stayWith(status: status)),
          store: MemorySessionStore(token: tokenFor('stay-A')),
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(
          FakeRoomServiceRepository(),
        ),
        housekeepingRepositoryProvider.overrideWithValue(
          FakeHousekeepingRepository(),
        ),
        chatRepositoryProvider.overrideWithValue(chat),
        chatClockProvider.overrideWithValue(() => clock.now),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('tile-concierge')));
  await tester.pumpAndSettle();
  return (chat, clock);
}

Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(find.byKey(const Key('chat-input')), text);
  await tester.tap(find.byKey(const Key('chat-send')));
  await tester.pumpAndSettle();
}

bool enabled(WidgetTester tester, String key) =>
    tester.widget<ButtonStyleButton>(find.byKey(Key(key))).onPressed != null;

void main() {
  testWidgets('"Xác nhận" sends the card id; "Xem đơn" opens the order', (
    tester,
  ) async {
    final (chat, _) = await open(
      tester,
      answers: [summary(), created('OPEN_ORDER', 'o-1')],
    );
    await type(tester, 'Cho 2 phở bò');

    expect(find.byKey(const Key('confirm-card-m-summary')), findsOneWidget);
    expect(find.text('Xác nhận đơn đặt món'), findsOneWidget);
    expect(find.text('Tổng: 170.000 ₫'), findsOneWidget);
    expect(chat.asks.single.confirmActionId, isNull);

    await tester.tap(find.byKey(const Key('confirm-yes')));
    await tester.pumpAndSettle();
    expect(chat.asks.last.message, 'Xác nhận');
    expect(chat.asks.last.confirmActionId, actionId);
    expect(enabled(tester, 'confirm-yes'), isFalse, reason: 'used: locked');

    await tester.tap(find.byKey(const Key('open-OPEN_ORDER')));
    await tester.pumpAndSettle();
    expect(find.byType(OrderDetailScreen), findsOneWidget);
  });

  testWidgets('"Sửa lại" locks the card and puts the cursor in the input', (
    tester,
  ) async {
    final (chat, _) = await open(tester, answers: [summary()]);
    await type(tester, 'Cho 2 phở bò');
    await tester.tap(find.byKey(const Key('confirm-edit')));
    await tester.pumpAndSettle();

    expect(enabled(tester, 'confirm-yes'), isFalse);
    expect(enabled(tester, 'confirm-edit'), isFalse);
    final input = tester.widget<TextField>(find.byKey(const Key('chat-input')));
    expect(input.focusNode!.hasFocus, isTrue);
    expect(chat.asks, hasLength(1), reason: 'nothing sent');
  });

  testWidgets('after 10 minutes the card locks and says so', (tester) async {
    final (chat, clock) = await open(tester, answers: [summary()]);
    await type(tester, 'Cho 2 phở bò');
    clock.now = clock.now.add(const Duration(minutes: 9, seconds: 59));
    await tester.pump(const Duration(minutes: 9, seconds: 59));
    expect(enabled(tester, 'confirm-yes'), isTrue);

    clock.now = clock.now.add(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 2));
    expect(enabled(tester, 'confirm-yes'), isFalse);
    expect(find.byKey(const Key('confirm-expired')), findsOneWidget);
    expect(chat.asks, hasLength(1));
  });

  testWidgets('a newer message locks an older card', (tester) async {
    final (chat, _) = await open(
      tester,
      answers: [
        summary(),
        const ChatReply(
          messageId: 'm-2',
          text: 'Phở không cay ạ.',
          targets: [],
        ),
      ],
    );
    await type(tester, 'Cho 2 phở bò');
    await type(tester, 'Phở có cay không?');
    expect(enabled(tester, 'confirm-yes'), isFalse);
    expect(find.byKey(const Key('confirm-expired')), findsNothing);
    expect(chat.asks.last.confirmActionId, isNull);
  });

  testWidgets('a checkout summary and "Xem yêu cầu" for housekeeping', (
    tester,
  ) async {
    await open(
      tester,
      answers: [
        summary(kind: 'CHECKOUT', total: null),
        created('OPEN_HOUSEKEEPING', 'hk-1'),
      ],
    );
    await type(tester, 'Tôi muốn trả phòng');
    expect(find.text('Xác nhận trả phòng'), findsOneWidget);
    expect(find.byKey(const Key('confirm-total')), findsNothing);

    await type(tester, 'Mang 2 khăn');
    expect(find.text('Xem yêu cầu'), findsOneWidget);
    await tester.tap(find.byKey(const Key('open-OPEN_HOUSEKEEPING')));
    await tester.pumpAndSettle();
    expect(find.byType(HkRequestDetailScreen), findsOneWidget);
  });

  testWidgets('waiting for check-out: the chat says it is look-up only', (
    tester,
  ) async {
    await open(tester, status: 'CHECKOUT_PENDING');
    expect(find.text('Đang chờ trả phòng — chỉ tra cứu'), findsOneWidget);
    expect(find.byKey(const Key('chat-input')), findsOneWidget);
  });

  testWidgets('no look-up note for an active stay', (tester) async {
    await open(tester);
    expect(find.byKey(const Key('chat-lookup-only')), findsNothing);
  });

  test('replies parse cards and buttons; unknown ones are ignored', () {
    final parsed = ChatReply.fromJson({
      'message_id': 'm1',
      'reply': 'x',
      'suggested_actions': [
        {'type': 'OPEN_SCREEN', 'target': 'MY_REQUESTS'},
        {'type': 'OPEN_ENTITY', 'target': 'OPEN_ORDER', 'entity_id': 'o-1'},
        {'type': 'OPEN_ENTITY', 'target': 'OPEN_CHECKOUT'},
        {'type': 'OPEN_ENTITY', 'target': 'OPEN_BANK', 'entity_id': 'b'},
      ],
      'pending_confirmation': {
        'id': actionId,
        'kind': 'FOOD_ORDER',
        'summary': {'total_vnd': 170000, 'items': <Object>[]},
      },
    });
    expect(parsed.targets, ['MY_REQUESTS']);
    expect(parsed.entityActions.single.entityId, 'o-1');
    expect(parsed.pending!.id, actionId);
    expect(parsed.pending!.totalVnd, 170000);

    expect(PendingConfirmation.fromJson(null), isNull);
    expect(PendingConfirmation.fromJson({'id': 1, 'kind': 'X'}), isNull);
    expect(
      PendingConfirmation.fromJson({'id': 'a', 'kind': 'CHECKOUT'})!.totalVnd,
      isNull,
    );
  });
}
