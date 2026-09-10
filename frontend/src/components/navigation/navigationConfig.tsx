import {
  Award,
  House,
  BarChart2,
  Calendar,
  ClipboardList,
  FileText,
  Gift,
  Landmark,
  MessageCircle,
  MessageSquare,
  Settings,
  Target,
  type LucideIcon,
} from "lucide-react";

export type NavigationItemId =
  | "home"
  | "chat"
  | "analytics"
  | "manage"
  | "calendar"
  | "goals"
  | "mortgage"
  | "reports"
  | "feedback"
  | "plan"
  | "invite"
  | "settings";

export type NavigationGroup = "primary" | "planning" | "account";

export type NavigationItem = {
  id: NavigationItemId;
  label: string;
  href: string;
  icon: LucideIcon;
  group: NavigationGroup;
};

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: "home", label: "Home", href: "/home", icon: House, group: "primary" },
  { id: "analytics", label: "Analytics", href: "/analytics", icon: BarChart2, group: "primary" },
  { id: "manage", label: "Gestisci", href: "/spazio", icon: ClipboardList, group: "primary" },
  // La Chat resta raggiungibile con un click su desktop e dallo sheet "Altro" su
  // mobile: il posto in barra va alla Home, che è la schermata d'ingresso.
  { id: "chat", label: "Chat", href: "/chat", icon: MessageCircle, group: "planning" },
  { id: "calendar", label: "Calendario", href: "/calendario", icon: Calendar, group: "planning" },
  { id: "goals", label: "Obiettivi", href: "/goals", icon: Target, group: "planning" },
  { id: "mortgage", label: "Mutuo", href: "/mutuo", icon: Landmark, group: "planning" },
  { id: "reports", label: "Report", href: "/reports", icon: FileText, group: "planning" },
  { id: "feedback", label: "Feedback", href: "/feedback", icon: MessageSquare, group: "account" },
  { id: "plan", label: "Il tuo piano", href: "/abbonamenti", icon: Award, group: "account" },
  { id: "invite", label: "Invita amici", href: "/invita", icon: Gift, group: "account" },
  { id: "settings", label: "Impostazioni", href: "/impostazioni", icon: Settings, group: "account" },
];

const MOBILE_PRIMARY_IDS: readonly NavigationItemId[] = ["home", "analytics", "manage"];

export const MOBILE_PRIMARY_ITEMS: readonly NavigationItem[] = NAVIGATION_ITEMS.filter((item) =>
  MOBILE_PRIMARY_IDS.includes(item.id),
);

export const MOBILE_MORE_ITEMS: readonly NavigationItem[] = NAVIGATION_ITEMS.filter(
  (item) => !MOBILE_PRIMARY_IDS.includes(item.id),
);

export function isNavigationItemActive(pathname: string, href: string): boolean {
  const currentPath = pathname.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
  const targetPath = href.replace(/\/+$/, "") || "/";

  if (currentPath === targetPath) {
    return true;
  }
  return targetPath !== "/" && currentPath.startsWith(`${targetPath}/`);
}
