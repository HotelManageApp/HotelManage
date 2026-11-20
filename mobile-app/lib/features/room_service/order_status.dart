import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// The guest-facing name of an order status.
String orderStatusLabel(AppLocalizations l10n, String status) =>
    switch (status) {
      'PENDING' => l10n.orderStatusPENDING,
      'CONFIRMED' => l10n.orderStatusCONFIRMED,
      'PREPARING' => l10n.orderStatusPREPARING,
      'DELIVERING' => l10n.orderStatusDELIVERING,
      'COMPLETED' => l10n.orderStatusCOMPLETED,
      'CANCELLED' => l10n.orderStatusCANCELLED,
      _ => status,
    };

IconData orderStatusIcon(String status) => switch (status) {
  'PENDING' => Icons.hourglass_top,
  'CONFIRMED' => Icons.thumb_up_alt_outlined,
  'PREPARING' => Icons.soup_kitchen_outlined,
  'DELIVERING' => Icons.delivery_dining,
  'COMPLETED' => Icons.check_circle_outline,
  'CANCELLED' => Icons.cancel_outlined,
  _ => Icons.receipt_long,
};
