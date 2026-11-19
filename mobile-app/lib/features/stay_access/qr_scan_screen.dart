import 'dart:async';

import 'package:go_router/go_router.dart';
import 'package:hotel_guest/features/stay_access/room_code.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// Scans the check-in slip QR and pops with the room code.
/// Any other QR is rejected with a message; scanning continues.
class QrScanScreen extends StatefulWidget {
  const new({super.key});

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen> {
  final MobileScannerController _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
  );
  bool _done = false;
  String? _error;

  @override
  void dispose() {
    unawaited(_controller.dispose());
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_done) return;
    for (final barcode in capture.barcodes) {
      final code = roomCodeFromQr(barcode.rawValue ?? '');
      if (code != null) {
        _done = true;
        context.pop(code);
        return;
      }
    }
    setState(() => _error = AppLocalizations.of(context).scanInvalidQr);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.loginScanQr)),
      body: Stack(
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          if (_error != null)
            Align(
              alignment: Alignment.bottomCenter,
              child: Card(
                margin: const EdgeInsets.all(24),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_error!),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
