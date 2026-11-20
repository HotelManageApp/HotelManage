import 'package:hotel_guest/features/express_checkout/checkout_models.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// The bill's lines and the server's total, labelled as an estimate or as
/// the bill reception verified.
class BillView extends StatelessWidget {
  const new({required this.bill, super.key});

  final GuestBill bill;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          bill.isEstimate ? l10n.checkoutEstimateLabel : l10n.checkoutFinalBill,
          key: const Key('bill-label'),
          style: theme.textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        for (final (index, line) in bill.lines.indexed)
          Padding(
            key: Key('bill-line-$index'),
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: Text(line.description)),
                Text(
                  '${line.isDiscount ? '−' : ''}${formatVnd(line.amountVnd)}',
                ),
              ],
            ),
          ),
        const Divider(),
        Row(
          children: [
            Expanded(
              child: Text(
                l10n.checkoutTotal,
                style: theme.textTheme.titleMedium,
              ),
            ),
            Text(
              formatVnd(bill.totalVnd),
              key: const Key('bill-total'),
              style: theme.textTheme.titleMedium,
            ),
          ],
        ),
      ],
    );
  }
}
