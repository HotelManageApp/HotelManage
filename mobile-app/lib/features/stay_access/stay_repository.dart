import 'package:hotel_guest/core/api_client.dart';

/// The guest's own stay, as returned by /guest/me and the login response.
class GuestStay {
  const new({
    required this.roomNumber,
    required this.guestName,
    required this.expectedCheckoutAt,
    required this.status,
  });

  factory fromJson(Map<String, dynamic> json) => GuestStay(
    roomNumber: json['room_number'] as String,
    guestName: json['guest_name'] as String?,
    expectedCheckoutAt: DateTime.parse(json['expected_checkout_at'] as String),
    status: json['status'] as String,
  );

  final String roomNumber;
  final String? guestName;
  final DateTime expectedCheckoutAt;
  final String status;

  bool get checkoutPending => status == 'CHECKOUT_PENDING';
}

class GuestLogin {
  const new({required this.token, required this.stay});

  final String token;
  final GuestStay stay;
}

/// Calls to /api/v1/guest/* (SPEC-stay-access). Errors are AppException.
class StayRepository {
  const new(this._api);

  final ApiClient _api;

  Future<GuestLogin> loginWithCode({
    required String code,
    required String deviceId,
    required String lang,
  }) async {
    final data = await _api.post(
      '/api/v1/guest/auth/room-code',
      body: {'code': code, 'device_id': deviceId, 'lang': lang},
    );
    final json = Map<String, dynamic>.from(data as Map);
    return GuestLogin(
      token: json['access_token'] as String,
      stay: GuestStay.fromJson(Map<String, dynamic>.from(json['stay'] as Map)),
    );
  }

  Future<GuestStay> me() async {
    final data = await _api.get('/api/v1/guest/me');
    return GuestStay.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> logout() => _api.post('/api/v1/guest/auth/logout');
}
