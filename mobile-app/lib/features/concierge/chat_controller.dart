import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/concierge/chat_repository.dart';

enum ChatRole { guest, assistant, notice }

enum Delivery { sending, sent, failed }

/// Why a notice line is shown (the screen picks the words).
enum NoticeKind { slowDown, busy, disabled }

class ChatEntry {
  const new({
    required this.key,
    required this.role,
    required this.text,
    this.targets = const [],
    this.delivery = Delivery.sent,
    this.clientMessageId,
    this.notice,
    this.retryAfterSeconds,
  });

  final String key;
  final ChatRole role;
  final String text;
  final List<String> targets;
  final Delivery delivery;
  final String? clientMessageId;
  final NoticeKind? notice;
  final int? retryAfterSeconds;

  ChatEntry withDelivery(Delivery value) => ChatEntry(
    key: key,
    role: role,
    text: text,
    targets: targets,
    delivery: value,
    clientMessageId: clientMessageId,
  );
}

class ChatState {
  const new({
    this.entries = const [],
    this.loading = true,
    this.waiting = false,
    this.receptionPhone = '',
    this.chatEnabled = true,
    this.loadFailed = false,
  });

  final List<ChatEntry> entries;
  final bool loading;

  /// "Concierge is answering…"
  final bool waiting;
  final String receptionPhone;
  final bool chatEnabled;
  final bool loadFailed;

  bool get isEmpty => !entries.any((e) => e.role != ChatRole.notice);

  ChatState copyWith({
    List<ChatEntry>? entries,
    bool? loading,
    bool? waiting,
    String? receptionPhone,
    bool? chatEnabled,
    bool? loadFailed,
  }) => ChatState(
    entries: entries ?? this.entries,
    loading: loading ?? this.loading,
    waiting: waiting ?? this.waiting,
    receptionPhone: receptionPhone ?? this.receptionPhone,
    chatEnabled: chatEnabled ?? this.chatEnabled,
    loadFailed: loadFailed ?? this.loadFailed,
  );
}

/// 36 random hex chars shaped like a UUID v4 (the backend validates a UUID).
String newClientMessageId([Random? random]) {
  final rng = random ?? Random.secure();
  final b = List<int>.generate(16, (_) => rng.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

/// The concierge conversation of this stay: history from the backend, new
/// questions through ai-service, retries with the same client_message_id.
class ChatController extends Notifier<ChatState> {
  int _seq = 0;
  String _nextKey() => 'local-${_seq++}';

  ChatRepository get _repo => ref.read(chatRepositoryProvider);

  @override
  ChatState build() => const ChatState();

  Future<void> load() async {
    state = state.copyWith(loading: true, loadFailed: false);
    try {
      final results = await Future.wait([
        _repo.history(),
        _repo.hotelContact(),
      ]);
      final history = results[0] as List<ChatHistoryLine>;
      final contact = results[1] as HotelContact;
      state = state.copyWith(
        loading: false,
        receptionPhone: contact.receptionPhone,
        chatEnabled: contact.chatEnabled,
        entries: [
          for (final line in history)
            ChatEntry(
              key: line.id,
              role: line.fromGuest ? ChatRole.guest : ChatRole.assistant,
              text: line.text,
            ),
          ...state.entries.where((e) => e.key.startsWith('local-')),
        ],
      );
    } on AppException {
      state = state.copyWith(loading: false, loadFailed: true);
    }
  }

  Future<void> send(String text) async {
    final message = text.trim();
    if (message.isEmpty || state.waiting) return;
    final entry = ChatEntry(
      key: _nextKey(),
      role: ChatRole.guest,
      text: message.length > 1000 ? message.substring(0, 1000) : message,
      delivery: Delivery.sending,
      clientMessageId: newClientMessageId(),
    );
    state = state.copyWith(entries: [...state.entries, entry]);
    await _deliver(entry);
  }

  /// Sends a failed message again with the same client_message_id.
  Future<void> retry(String key) async {
    if (state.waiting) return;
    final entry = state.entries.firstWhere((e) => e.key == key);
    if (entry.delivery != Delivery.failed) return;
    _replace(entry.withDelivery(Delivery.sending));
    await _deliver(entry);
  }

  Future<void> _deliver(ChatEntry entry) async {
    state = state.copyWith(waiting: true);
    try {
      final reply = await _repo.ask(
        entry.text,
        clientMessageId: entry.clientMessageId!,
      );
      _replace(entry.withDelivery(Delivery.sent));
      _add(
        ChatEntry(
          key: reply.messageId,
          role: ChatRole.assistant,
          text: reply.text,
          targets: reply.targets,
        ),
      );
    } on AppException catch (error) {
      _failed(entry, error);
    } finally {
      state = state.copyWith(waiting: false);
    }
  }

  void _failed(ChatEntry entry, AppException error) {
    if (error.isUnauthorized) return; // the session controller signs out
    if (error.isNetworkError) {
      _replace(entry.withDelivery(Delivery.failed)); // tap to retry
      return;
    }
    // The server answered: this message is done, explain what happened.
    _replace(entry.withDelivery(Delivery.sent));
    if (error.status == 429) {
      _add(
        ChatEntry(
          key: _nextKey(),
          role: ChatRole.notice,
          text: error.message,
          notice: NoticeKind.slowDown,
          retryAfterSeconds: error.retryAfterSeconds,
        ),
      );
    } else if (error.code == 'CHAT_DISABLED') {
      state = state.copyWith(chatEnabled: false);
      _add(
        ChatEntry(
          key: _nextKey(),
          role: ChatRole.notice,
          text: error.message,
          notice: NoticeKind.disabled,
          targets: const ['CALL_RECEPTION'],
        ),
      );
    } else {
      _add(
        ChatEntry(
          key: _nextKey(),
          role: ChatRole.notice,
          text: error.message,
          notice: NoticeKind.busy,
          targets: const ['CALL_RECEPTION'],
        ),
      );
    }
  }

  void _add(ChatEntry entry) =>
      state = state.copyWith(entries: [...state.entries, entry]);

  void _replace(ChatEntry entry) => state = state.copyWith(
    entries: [
      for (final e in state.entries)
        if (e.key == entry.key) entry else e,
    ],
  );
}

final NotifierProvider<ChatController, ChatState> chatProvider =
    NotifierProvider.autoDispose<ChatController, ChatState>(ChatController.new);
