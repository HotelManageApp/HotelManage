import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/app/app.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/concierge/chat_repository.dart';
import 'package:hotel_guest/features/concierge/suggested_action_button.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:material_ui/material_ui.dart';

import '../room_service/fakes.dart';
import '../stay_access/fakes.dart';

class Ask {
  const new(this.message, this.clientMessageId);

  final String message;
  final String clientMessageId;
}

/// Scripted backend + ai-service for the chat.
class FakeChatRepository implements ChatRepository {
  List<ChatHistoryLine> lines = [];
  HotelContact contact = const HotelContact(
    receptionPhone: '028 3822 1234',
    chatEnabled: true,
  );
  final List<Object> answers = []; // ChatReply, AppException or Completer
  final List<Ask> asks = [];

  @override
  Future<List<ChatHistoryLine>> history() async => lines;

  @override
  Future<HotelContact> hotelContact() async => contact;

  @override
  Future<ChatReply> ask(
    String message, {
    required String clientMessageId,
  }) async {
    asks.add(Ask(message, clientMessageId));
    final next = answers.removeAt(0);
    if (next is Completer<ChatReply>) return await next.future;
    if (next is AppException) throw next;
    return next as ChatReply;
  }
}

ChatReply reply(String text, [List<String> targets = const []]) =>
    ChatReply(messageId: 'm-${text.hashCode}', text: text, targets: targets);

AppException error(int status, String code, {int? retryAfter}) => AppException(
  status: status,
  code: code,
  message: code,
  retryAfterSeconds: retryAfter,
);

class Setup {
  new(this.chat, this.launched);

  final FakeChatRepository chat;
  final List<Uri> launched;
}

Future<Setup> openChat(WidgetTester tester, {FakeChatRepository? chat}) async {
  final fake = chat ?? FakeChatRepository();
  final launched = <Uri>[];
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        ...sessionOverrides(
          repo: FakeStayRepository(),
          store: MemorySessionStore(token: tokenFor('stay-A')),
        ),
        cartStoreProvider.overrideWithValue(MemoryCartStore()),
        roomServiceRepositoryProvider.overrideWithValue(
          FakeRoomServiceRepository(),
        ),
        chatRepositoryProvider.overrideWithValue(fake),
        linkLauncherProvider.overrideWithValue((uri) async {
          launched.add(uri);
          return true;
        }),
      ],
      child: const HotelGuestApp(),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('tile-concierge')));
  await tester.pumpAndSettle();
  return Setup(fake, launched);
}

Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(find.byKey(const Key('chat-input')), text);
  await tester.tap(find.byKey(const Key('chat-send')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('first open: greeting and quick questions; a chip asks it', (
    tester,
  ) async {
    final chat = FakeChatRepository()
      ..answers.add(reply('Bữa sáng 06:30–09:30 tại tầng 1.'));
    await openChat(tester, chat: chat);
    expect(
      find.text('Xin chào! Tôi có thể giúp gì cho Quý khách?'),
      findsOneWidget,
    );

    await tester.tap(find.text('Mấy giờ ăn sáng?'));
    await tester.pumpAndSettle();
    expect(chat.asks.single.message, 'Mấy giờ ăn sáng?');
    expect(find.text('Bữa sáng 06:30–09:30 tại tầng 1.'), findsOneWidget);
    expect(
      find.text('Gần đây có gì chơi?'),
      findsNothing,
      reason: 'chips only when empty',
    );
  });

  testWidgets('shows the history of the stay', (tester) async {
    final chat = FakeChatRepository()
      ..lines = const [
        ChatHistoryLine(id: '1', fromGuest: true, text: 'Wi-Fi?'),
        ChatHistoryLine(id: '2', fromGuest: false, text: 'Mạng Hotel-Guest.'),
      ];
    await openChat(tester, chat: chat);
    expect(find.text('Wi-Fi?'), findsOneWidget);
    expect(find.text('Mạng Hotel-Guest.'), findsOneWidget);
    expect(find.text('Mấy giờ ăn sáng?'), findsNothing);
  });

  testWidgets('"answering…" while waiting; suggestion opens its screen', (
    tester,
  ) async {
    final pending = Completer<ChatReply>();
    final chat = FakeChatRepository()..answers.add(pending);
    await openChat(tester, chat: chat);

    await tester.enterText(
      find.byKey(const Key('chat-input')),
      'Cho tôi đặt phở',
    );
    await tester.tap(find.byKey(const Key('chat-send')));
    await tester.pump();
    expect(find.byKey(const Key('chat-typing')), findsOneWidget);

    pending.complete(
      reply('Quý khách đặt món trong mục Đặt đồ ăn ạ.', ['ROOM_SERVICE']),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat-typing')), findsNothing);
    await tester.tap(find.byKey(const Key('action-ROOM_SERVICE')));
    await tester.pumpAndSettle();
    expect(find.text('Thực đơn'), findsOneWidget, reason: 'menu screen');
  });

  testWidgets('a lost message is sent again with the same client id', (
    tester,
  ) async {
    final chat = FakeChatRepository()
      ..answers.addAll([
        const AppException(status: 0, code: 'NETWORK_ERROR', message: 'x'),
        reply('Hồ bơi mở 06:00–21:00.'),
      ]);
    await openChat(tester, chat: chat);
    await type(tester, 'Hồ bơi mấy giờ?');
    expect(find.text('Chưa gửi được. Chạm để gửi lại.'), findsOneWidget);

    await tester.tap(find.text('Chưa gửi được. Chạm để gửi lại.'));
    await tester.pumpAndSettle();
    expect(chat.asks, hasLength(2));
    expect(chat.asks[1].clientMessageId, chat.asks[0].clientMessageId);
    expect(find.text('Hồ bơi mở 06:00–21:00.'), findsOneWidget);
    expect(find.text('Chưa gửi được. Chạm để gửi lại.'), findsNothing);
  });

  testWidgets('a new question gets a new client id', (tester) async {
    final chat = FakeChatRepository()..answers.addAll([reply('A'), reply('B')]);
    await openChat(tester, chat: chat);
    await type(tester, 'Một');
    await type(tester, 'Hai');
    expect(chat.asks[0].clientMessageId, isNot(chat.asks[1].clientMessageId));
  });

  testWidgets('429 says how long to wait', (tester) async {
    final chat = FakeChatRepository()
      ..answers.add(error(429, 'RATE_LIMITED', retryAfter: 30));
    await openChat(tester, chat: chat);
    await type(tester, 'Hỏi tiếp');
    expect(
      find.text('Quý khách gửi hơi nhanh, vui lòng thử lại sau 30 giây.'),
      findsOneWidget,
    );
    expect(find.text('Chưa gửi được. Chạm để gửi lại.'), findsNothing);
  });

  testWidgets('busy (503/504) offers to call reception', (tester) async {
    final chat = FakeChatRepository()..answers.add(error(504, 'LLM_TIMEOUT'));
    final setup = await openChat(tester, chat: chat);
    await type(tester, 'Có spa không?');
    expect(
      find.text(
        'Hệ thống đang bận, Quý khách vui lòng thử lại hoặc gọi Lễ tân.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('action-CALL_RECEPTION')));
    expect(setup.launched.single, Uri(scheme: 'tel', path: '02838221234'));
  });

  testWidgets('a chatbot switched off replaces the input', (tester) async {
    final chat = FakeChatRepository()
      ..contact = const HotelContact(
        receptionPhone: '028 1',
        chatEnabled: false,
      );
    await openChat(tester, chat: chat);
    expect(find.byKey(const Key('chat-input')), findsNothing);
    expect(
      find.text('Trợ lý ảo đang tạm tắt. Quý khách vui lòng liên hệ Lễ tân.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('action-CALL_RECEPTION')), findsOneWidget);
  });

  testWidgets('switched off while chatting (503 CHAT_DISABLED)', (
    tester,
  ) async {
    final chat = FakeChatRepository()..answers.add(error(503, 'CHAT_DISABLED'));
    await openChat(tester, chat: chat);
    await type(tester, 'Xin chào');
    expect(find.byKey(const Key('chat-input')), findsNothing);
  });

  testWidgets('only allowed map links open', (tester) async {
    final chat = FakeChatRepository()
      ..answers.add(
        reply(
          '- **Chợ Bến Thành**: [bản đồ](https://maps.google.com/?q=bt)\n'
          '- Ưu đãi: https://evil.example.com/win',
        ),
      );
    final setup = await openChat(tester, chat: chat);
    await type(tester, 'Gần đây có gì chơi?');

    await tester.tap(find.text('bản đồ'));
    expect(setup.launched.single, Uri.parse('https://maps.google.com/?q=bt'));
    expect(
      find.textContaining('https://evil.example.com/win', findRichText: true),
      findsOneWidget,
    );
    expect(
      find.text('https://evil.example.com/win'),
      findsNothing,
      reason: 'not a link',
    );
  });

  testWidgets('no call button without a reception phone', (tester) async {
    final chat = FakeChatRepository()
      ..contact = const HotelContact(receptionPhone: '', chatEnabled: true)
      ..answers.add(error(503, 'LLM_UNAVAILABLE'));
    await openChat(tester, chat: chat);
    await type(tester, 'Hỏi');
    expect(find.byKey(const Key('action-CALL_RECEPTION')), findsNothing);
  });
}
