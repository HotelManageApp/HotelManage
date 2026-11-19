import 'package:go_router/go_router.dart';

import 'package:hotel_guest/features/welcome/welcome_screen.dart';

/// Routes are added per feature (stay_access in T18, room_service in T30, ...).
GoRouter buildRouter() => GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/', builder: (context, state) => const WelcomeScreen()),
  ],
);
