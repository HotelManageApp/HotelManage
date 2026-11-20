import type { ReactNode } from "react";
import { StaffGuard } from "@/components/auth/StaffGuard";
import { StaffShell } from "@/components/auth/StaffShell";
import { StaffEventsProvider } from "@/lib/realtime/useStaffEvents";

export default function StaffLayout({ children }: { children: ReactNode }) {
  return (
    <StaffGuard>
      <StaffEventsProvider>
        <StaffShell>{children}</StaffShell>
      </StaffEventsProvider>
    </StaffGuard>
  );
}
