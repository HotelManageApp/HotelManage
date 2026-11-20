import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/providers.dart';

/// Buttons the concierge may suggest (SPEC-concierge-guide); anything else
/// from the server is ignored.
const chatTargets = {
  'ROOM_SERVICE',
  'HOUSEKEEPING',
  'MY_REQUESTS',
  'CALL_RECEPTION',
};

class ChatHistoryLine {
  const new({required this.id, required this.fromGuest, required this.text});

  final String id;
  final bool fromGuest;
  final String text;
}

class ChatReply {
  const new({
    required this.messageId,
    required this.text,
    required this.targets,
  });

  factory fromJson(Map<String, dynamic> json) => ChatReply(
    messageId: json['message_id'] as String,
    text: json['reply'] as String,
    targets: [
      for (final a in (json['suggested_actions'] as List?) ?? const [])
        if (a is Map && chatTargets.contains(a['target']))
          a['target'] as String,
    ],
  );

  final String messageId;
  final String text;
  final List<String> targets;
}

class HotelContact {
  const new({required this.receptionPhone, required this.chatEnabled});

  final String receptionPhone;
  final bool chatEnabled;
}

/// History and hotel info come straight from backend-api; questions go to
/// ai-service. Both calls carry the guest's own token.
class ChatRepository {
  const new(this._api, this._ai);

  final ApiClient _api;
  final ApiClient _ai;

  Future<List<ChatHistoryLine>> history() async {
    final data = await _api.get(
      '/api/v1/guest/chat/messages',
      query: {'limit': 50},
    );
    return [
      for (final m in data as List)
        ChatHistoryLine(
          id: (m as Map)['id'] as String,
          fromGuest: m['role'] == 'GUEST',
          text: m['content'] as String,
        ),
    ];
  }

  Future<HotelContact> hotelContact() async {
    final data = Map<String, dynamic>.from(
      await _api.get('/api/v1/guest/hotel-info') as Map,
    );
    return HotelContact(
      receptionPhone: data['reception_phone'] as String? ?? '',
      chatEnabled: data['chat_enabled'] as bool? ?? true,
    );
  }

  /// [clientMessageId] stays the same when the guest retries after a network
  /// failure, so the server stores the exchange once.
  Future<ChatReply> ask(
    String message, {
    required String clientMessageId,
  }) async {
    _ai
      ..token = _api.token
      ..onUnauthorized = _api.onUnauthorized;
    final data = await _ai.post(
      '/api/v1/chat',
      body: {'message': message, 'client_message_id': clientMessageId},
    );
    return ChatReply.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

final aiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient.create(ref.watch(appConfigProvider).aiBaseUrl),
);

final chatRepositoryProvider = Provider<ChatRepository>(
  (ref) =>
      ChatRepository(ref.watch(apiClientProvider), ref.watch(aiClientProvider)),
);
