import type { ReactNode } from "react";
import { StaffGuard } from "@/components/auth/StaffGuard";
import { StaffShell } from "@/components/auth/StaffShell";

export default function StaffLayout({ children }: { children: ReactNode }) {
  return (
    <StaffGuard>
      <StaffShell>{children}</StaffShell>
    </StaffGuard>
  );
}
