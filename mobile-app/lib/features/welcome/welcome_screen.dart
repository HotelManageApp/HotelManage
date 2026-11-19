import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/stay_access/room_code.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// Language choice and sign-in with the room code from the check-in slip
/// (typed or scanned as QR).
class WelcomeScreen extends ConsumerStatefulWidget {
  const new({super.key});

  @override
  ConsumerState<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends ConsumerState<WelcomeScreen> {
  final TextEditingController _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit([String? scanned]) async {
    final l10n = AppLocalizations.of(context);
    final code = normalizeRoomCode(scanned ?? _code.text);
    if (code == null) {
      setState(() => _error = l10n.loginInvalidCode);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(sessionProvider.notifier)
          .login(code, lang: ref.read(localeProvider).languageCode);
    } on AppException catch (error) {
      if (mounted) setState(() => _error = _messageFor(error, l10n));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _messageFor(AppException error, AppLocalizations l10n) {
    if (error.isNetworkError) return l10n.serverUnreachable;
    return switch (error.status) {
      401 => l10n.loginInvalidCode,
      409 when error.code == 'TOO_MANY_DEVICES' => l10n.loginTooManyDevices,
      429 => l10n.loginRateLimited(
        ((error.retryAfterSeconds ?? 60) / 60).ceil().clamp(1, 60),
      ),
      _ => l10n.loginFailed,
    };
  }

  Future<void> _scan() async {
    final scanned = await context.push<String>('/scan');
    if (scanned == null || !mounted) return;
    _code.text = formatRoomCode(scanned);
    await _submit(scanned);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = ref.watch(localeProvider);
    final session = ref.watch(sessionProvider).value;
    final notice = switch (session) {
      SignedOut(reason: SignedOutReason.stayClosed) => l10n.noticeStayClosed,
      SignedOut(reason: SignedOutReason.sessionEnded) =>
        l10n.noticeSessionEnded,
      _ => null,
    };

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 24),
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
            const SizedBox(height: 24),
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
            if (notice != null) ...[
              const SizedBox(height: 16),
              Card(
                key: const Key('session-notice'),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(notice),
                ),
              ),
            ],
            const SizedBox(height: 24),
            TextField(
              key: const Key('room-code-field'),
              controller: _code,
              inputFormatters: [RoomCodeInputFormatter()],
              textCapitalization: TextCapitalization.characters,
              autocorrect: false,
              enableSuggestions: false,
              style: const TextStyle(fontSize: 24, letterSpacing: 4),
              textAlign: TextAlign.center,
              decoration: InputDecoration(
                labelText: l10n.loginCodeLabel,
                hintText: 'XXXX-XXXX',
                errorText: _error,
                border: const OutlineInputBorder(),
              ),
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(_busy ? l10n.loginSubmitting : l10n.loginSubmit),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _busy ? null : _scan,
              icon: const Icon(Icons.qr_code_scanner),
              label: Text(l10n.loginScanQr),
            ),
            const SizedBox(height: 16),
            Text(
              l10n.loginHelp,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
