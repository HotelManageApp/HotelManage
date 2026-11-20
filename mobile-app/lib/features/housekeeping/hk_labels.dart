import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

String amenityLabel(AppLocalizations l10n, String code) => switch (code) {
  'TOWEL' => l10n.amenityTOWEL,
  'WATER' => l10n.amenityWATER,
  'TOILETRIES' => l10n.amenityTOILETRIES,
  'PILLOW' => l10n.amenityPILLOW,
  'BLANKET' => l10n.amenityBLANKET,
  'SLIPPERS' => l10n.amenitySLIPPERS,
  'OTHER' => l10n.amenityOTHER,
  _ => code,
};

IconData amenityIcon(String code) => switch (code) {
  'TOWEL' => Icons.dry_cleaning,
  'WATER' => Icons.water_drop_outlined,
  'TOILETRIES' => Icons.soap_outlined,
  'PILLOW' => Icons.bed_outlined,
  'BLANKET' => Icons.layers_outlined,
  'SLIPPERS' => Icons.do_not_step,
  _ => Icons.more_horiz,
};

String hkTypeLabel(AppLocalizations l10n, String type) =>
    type == 'AMENITY' ? l10n.hkTypeAMENITY : l10n.hkTypeCLEANING;

String hkStatusLabel(AppLocalizations l10n, String status) => switch (status) {
  'REQUESTED' => l10n.hkStatusREQUESTED,
  'ASSIGNED' => l10n.hkStatusASSIGNED,
  'IN_PROGRESS' => l10n.hkStatusIN_PROGRESS,
  'DONE' => l10n.hkStatusDONE,
  'CANCELLED' => l10n.hkStatusCANCELLED,
  _ => status,
};

IconData hkStatusIcon(String status) => switch (status) {
  'REQUESTED' => Icons.hourglass_top,
  'ASSIGNED' => Icons.person_outline,
  'IN_PROGRESS' => Icons.cleaning_services_outlined,
  'DONE' => Icons.check_circle_outline,
  'CANCELLED' => Icons.cancel_outlined,
  _ => Icons.room_preferences,
};
