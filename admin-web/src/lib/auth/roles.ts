export const ROLES = ["RECEPTION", "KITCHEN", "HOUSEKEEPING"] as const;
export type Role = (typeof ROLES)[number];

export type Area = "reception" | "kitchen" | "housekeeping";

export const AREA_BY_ROLE: Record<Role, Area> = {
  RECEPTION: "reception",
  KITCHEN: "kitchen",
  HOUSEKEEPING: "housekeeping",
};

const AREAS = new Set<string>(Object.values(AREA_BY_ROLE));

/** Landing page of a role, without the locale prefix (next-intl adds it). */
export function roleHome(role: Role): `/${Area}` {
  return `/${AREA_BY_ROLE[role]}`;
}

/** The role area a locale-less pathname belongs to, or null for shared pages (/account, ...). */
export function areaOf(pathname: string): Area | null {
  const first = pathname.split("/").filter(Boolean)[0] ?? "";
  return AREAS.has(first) ? (first as Area) : null;
}

/** UI-side check only, for a friendlier screen; the backend enforces roles on every call. */
export function canAccess(role: Role, pathname: string): boolean {
  const area = areaOf(pathname);
  return area === null || area === AREA_BY_ROLE[role];
}
