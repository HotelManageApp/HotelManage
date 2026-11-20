import 'package:flutter/services.dart';

/// Room codes as issued by backend-api (SPEC-stay-access): 8 symbols from an
/// alphabet without look-alikes (no 0 O 1 I L), shown as XXXX-XXXX.
const roomCodeAlphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
const roomCodeLength = 8;
const qrPrefix = 'hotelapp://login?code=';

/// Canonical 8-char code, or null when [raw] cannot be a valid code.
String? normalizeRoomCode(String raw) {
  final cleaned = raw.toUpperCase().replaceAll(RegExp(r'[\s-]'), '');
  if (cleaned.length != roomCodeLength) return null;
  for (final rune in cleaned.split('')) {
    if (!roomCodeAlphabet.contains(rune)) return null;
  }
  return cleaned;
}

String formatRoomCode(String code) =>
    code.length <= 4 ? code : '${code.substring(0, 4)}-${code.substring(4)}';

/// The code inside a check-in slip QR, or null for any other QR.
String? roomCodeFromQr(String payload) {
  final value = payload.trim();
  if (!value.startsWith(qrPrefix)) return null;
  return normalizeRoomCode(value.substring(qrPrefix.length));
}

/// Upper-cases, drops characters outside the alphabet and inserts the dash.
class RoomCodeInputFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final kept = newValue.text
        .toUpperCase()
        .split('')
        .where(roomCodeAlphabet.contains)
        .take(roomCodeLength)
        .join();
    final text = formatRoomCode(kept);
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
}
