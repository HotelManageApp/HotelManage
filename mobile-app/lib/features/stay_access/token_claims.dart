import 'dart:convert';

/// Reads the `stay_id` claim of a stay session token without verifying it.
///
/// Only used as a local key (the cart belongs to one stay). The backend never
/// trusts anything the app derives from it: it reads the stay from the token
/// it verifies itself (C4.1).
String? stayIdFromToken(String? token) {
  if (token == null) return null;
  final parts = token.split('.');
  if (parts.length != 3) return null;
  try {
    final json = utf8.decode(base64Url.decode(base64Url.normalize(parts[1])));
    final claims = jsonDecode(json);
    final stayId = claims is Map ? claims['stay_id'] : null;
    return stayId is String && stayId.isNotEmpty ? stayId : null;
  } on FormatException {
    return null;
  }
}
