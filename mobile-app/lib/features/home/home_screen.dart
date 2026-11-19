import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

/// Signed-in home: who and where the guest is. Feature tiles (room service,
/// housekeeping, concierge) are added by their modules.
class HomeScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    if (session is! SignedIn) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final stay = session.stay;
    final locale = Localizations.localeOf(context).toLanguageTag();
    final checkout = DateFormat.yMd(locale)
        .add_Hm()
        .format(stay.expectedCheckoutAt.toLocal());

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.homeRoom(stay.roomNumber)),
        actions: [
          IconButton(
            tooltip: l10n.logout,
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).logout(),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            stay.guestName == null
                ? l10n.homeGreetingAnonymous
                : l10n.homeGreeting(stay.guestName!),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(l10n.homeCheckout(checkout)),
          if (stay.checkoutPending) ...[
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(l10n.homeCheckoutPending),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
