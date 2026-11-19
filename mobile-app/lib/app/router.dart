import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/features/home/home_screen.dart';
import 'package:hotel_guest/features/room_service/cart_screen.dart';
import 'package:hotel_guest/features/room_service/menu_screen.dart';
import 'package:hotel_guest/features/room_service/order_detail_screen.dart';
import 'package:hotel_guest/features/room_service/order_list_screen.dart';
import 'package:hotel_guest/features/stay_access/qr_scan_screen.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/welcome/welcome_screen.dart';
import 'package:material_ui/material_ui.dart';

/// `/` welcome + sign-in, `/scan` QR, `/home` signed-in area, `/menu`,
/// `/cart` and `/orders` room service,
/// `/requests/<type>/<id>` where a tapped notification leads.
/// The session decides where you may be; any 401 sends you back to `/`.
GoRouter buildRouter(WidgetRef ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      if (session.isLoading && !session.hasValue) return null;
      final signedIn = session.value is SignedIn;
      final atPublic =
          state.matchedLocation == '/' || state.matchedLocation == '/scan';
      if (signedIn && atPublic) return '/home';
      if (!signedIn && !atPublic) return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/', builder: (context, state) => const WelcomeScreen()),
      GoRoute(path: '/scan', builder: (context, state) => const QrScanScreen()),
      GoRoute(path: '/home', builder: (context, state) => const HomeScreen()),
      GoRoute(path: '/menu', builder: (context, state) => const MenuScreen()),
      GoRoute(path: '/cart', builder: (context, state) => const CartScreen()),
      GoRoute(
        path: '/orders',
        builder: (context, state) => const OrderListScreen(),
      ),
      GoRoute(
        path: '/requests/food_order/:id',
        builder: (context, state) =>
            OrderDetailScreen(orderId: state.pathParameters['id']!),
      ),
      // Request types without a detail screen yet (housekeeping, checkout)
      // open the home screen (SPEC-notifications).
      GoRoute(
        path: '/requests/:type/:id',
        redirect: (context, state) => '/home',
      ),
    ],
  );
}
