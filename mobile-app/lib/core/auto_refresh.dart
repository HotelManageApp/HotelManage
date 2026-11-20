import 'dart:async';

import 'package:flutter/widgets.dart';

/// Calls [onRefresh] every [interval] while this widget is on screen and
/// whenever the app comes back to the foreground: the fallback when a push
/// is late or never arrives (SPEC-notifications).
class AutoRefresh extends StatefulWidget {
  const new({
    required this.onRefresh,
    required this.child,
    this.interval = const Duration(seconds: 15),
    super.key,
  });

  final VoidCallback onRefresh;
  final Duration interval;
  final Widget child;

  @override
  State<AutoRefresh> createState() => _AutoRefreshState();
}

class _AutoRefreshState extends State<AutoRefresh> {
  Timer? _timer;
  late final AppLifecycleListener _lifecycle;

  @override
  void initState() {
    super.initState();
    _start();
    _lifecycle = AppLifecycleListener(
      onResume: () {
        widget.onRefresh();
        _start();
      },
      onPause: () => _timer?.cancel(),
    );
  }

  void _start() {
    _timer?.cancel();
    _timer = Timer.periodic(widget.interval, (_) => widget.onRefresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _lifecycle.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
