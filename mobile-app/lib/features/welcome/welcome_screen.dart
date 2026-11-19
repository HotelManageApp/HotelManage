import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// First screen.
///
/// Login by room code / QR replaces the body in T18; the language picker
/// stays.
class WelcomeScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final locale = ref.watch(localeProvider);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              Icon(
                Icons.room_service_outlined,
                size: 72,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 16),
              Text(
                l10n.welcomeTitle,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 8),
              Text(l10n.welcomeSubtitle, textAlign: TextAlign.center),
              const Spacer(),
              SegmentedButton<String>(
                segments: [
                  ButtonSegment(
                    value: 'vi',
                    label: Text(l10n.languageVietnamese),
                  ),
                  ButtonSegment(value: 'en', label: Text(l10n.languageEnglish)),
                ],
                selected: {locale.languageCode},
                onSelectionChanged: (selection) => ref
                    .read(localeProvider.notifier)
                    .select(Locale(selection.first)),
              ),
              const SizedBox(height: 24),
              const _ServerStatus(),
            ],
          ),
        ),
      ),
    );
  }
}

class _ServerStatus extends ConsumerWidget {
  const new();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final health = ref.watch(backendHealthProvider);

    final (IconData icon, Color color, String label) = health.when(
      data: (h) => h.ok
          ? (Icons.check_circle, Colors.green, l10n.serverOnline)
          : (Icons.error, Colors.orange, l10n.serverDegraded),
      error: (_, _) => (Icons.cloud_off, Colors.red, l10n.serverUnreachable),
      loading: () => (Icons.hourglass_empty, Colors.grey, l10n.serverChecking),
    );

    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 6),
        Text(label, key: const Key('server-status')),
        IconButton(
          tooltip: l10n.retry,
          icon: const Icon(Icons.refresh, size: 18),
          onPressed: () => ref.invalidate(backendHealthProvider),
        ),
      ],
    );
  }
}
