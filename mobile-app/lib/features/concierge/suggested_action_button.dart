import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

/// Opens tel: and map links outside the app. Overridden in tests.
final linkLauncherProvider = Provider<Future<bool> Function(Uri)>(
  (ref) =>
      (uri) => launchUrl(uri, mode: LaunchMode.externalApplication),
);

/// Screen each concierge suggestion opens.
const actionRoutes = {
  'ROOM_SERVICE': '/menu',
  'HOUSEKEEPING': '/housekeeping',
  'MY_REQUESTS': '/orders',
};

/// A button under a concierge answer: open a screen of the app, or call
/// reception. Unknown targets render nothing.
class SuggestedActionButton extends ConsumerWidget {
  const new({required this.target, required this.receptionPhone, super.key});

  final String target;
  final String receptionPhone;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    if (target == 'CALL_RECEPTION') {
      final phone = receptionPhone.replaceAll(RegExp('[^0-9+]'), '');
      if (phone.isEmpty) return const SizedBox.shrink();
      return OutlinedButton.icon(
        key: Key('action-$target'),
        icon: const Icon(Icons.call),
        label: Text(l10n.actionCallReception),
        onPressed: () =>
            ref.read(linkLauncherProvider)(Uri(scheme: 'tel', path: phone)),
      );
    }
    final route = actionRoutes[target];
    if (route == null) return const SizedBox.shrink();
    final label = switch (target) {
      'ROOM_SERVICE' => l10n.actionRoomService,
      'HOUSEKEEPING' => l10n.actionHousekeeping,
      _ => l10n.actionMyRequests,
    };
    return FilledButton.tonal(
      key: Key('action-$target'),
      onPressed: () => context.push(route),
      child: Text(label),
    );
  }
}
