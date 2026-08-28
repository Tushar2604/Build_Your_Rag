// App shell: grouped sidebar + top bar.
//
// The sidebar is grouped rather than one flat list because the nav has grown
// past the point where scanning it works — "Voice AI Setup" (build the thing),
// "Operations & Monitoring" (watch it run), "Campaigns" (run it at volume),
// "Account & Billing" (everything else) is the order someone actually moves
// through the product.
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Bot, BookOpen, LineChart, Settings, LogOut, Users2, PhoneCall, Radio,
  Megaphone, Plug, Mic, LifeBuoy, Search, Bell, Moon, Sun, ChevronLeft,
  ListChecks, LayoutDashboard, PhoneOutgoing, MessageCircle, UserSearch,
  CalendarDays, CalendarCheck, Briefcase, MapPin, Clock,
} from "lucide-react";
import { useAuth } from "../store/auth";
import { useTheme } from "../store/theme";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Bot;
  exact?: boolean;
  /** Only shown to Owner/Admin roles — the "admin panel" surfaces. */
  adminOnly?: boolean;
  badge?: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    // Its own group, above everything: the dashboard is where sign-in lands
    // and the one row that should never be hunted for inside a category.
    title: "Home",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, exact: true },
    ],
  },
  {
    // Its own group rather than a row inside "Operations": appointments are a
    // daily workflow with their own configuration underneath, and burying the
    // calendar in a list of monitoring pages is how it stops being found.
    title: "Appointments",
    items: [
      { to: "/appointments/calendar", label: "Calendar", icon: CalendarDays },
      { to: "/appointments", label: "Appointments", icon: CalendarCheck, exact: true },
      { to: "/appointments/services", label: "Services", icon: Briefcase, adminOnly: true },
      { to: "/appointments/resources", label: "Staff & Resources", icon: Users2, adminOnly: true },
      { to: "/appointments/locations", label: "Locations", icon: MapPin, adminOnly: true },
      { to: "/appointments/availability", label: "Availability", icon: Clock, adminOnly: true },
    ],
  },
  {
    title: "Voice AI Setup",
    items: [
      { to: "/assistants", label: "Voice AI Assistants", icon: Bot },
      { to: "/clone-voice", label: "Clone Voice", icon: Mic },
      { to: "/knowledge", label: "Files", icon: BookOpen },
      { to: "/integrations", label: "Integrations", icon: Plug, adminOnly: true },
    ],
  },
  {
    title: "Operations & Monitoring",
    items: [
      { to: "/channels", label: "Phone Numbers", icon: PhoneCall, adminOnly: true },
      { to: "/channels?tab=whatsapp", label: "WhatsApp Numbers", icon: MessageCircle, adminOnly: true },
      { to: "/candidates", label: "Candidates", icon: UserSearch, adminOnly: true },
      { to: "/interviews", label: "Call Logs", icon: PhoneOutgoing, adminOnly: true },
      { to: "/analytics", label: "Analytics", icon: LineChart },
    ],
  },
  {
    title: "Campaigns",
    items: [
      { to: "/interviews/bulk", label: "Bulk Call", icon: ListChecks, adminOnly: true },
      { to: "/broadcasts", label: "Broadcast", icon: Megaphone, adminOnly: true, badge: "New" },
    ],
  },
  {
    title: "Account & Billing",
    items: [
      { to: "/home", label: "Overview", icon: ListChecks, exact: true },
      { to: "/hiring-agent", label: "Hiring Agent", icon: Radio, adminOnly: true },
      { to: "/team", label: "Team", icon: Users2, adminOnly: true },
      { to: "/report-issue", label: "Report Issue", icon: LifeBuoy },
    ],
  },
];

/** Everything the ⌘K palette can jump to, flattened out of the groups. */
function searchTargets(isAdmin: boolean): NavItem[] {
  return NAV_GROUPS.flatMap((g) => g.items).filter((i) => !i.adminOnly || isAdmin);
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      className="chrome-control inline-flex items-center justify-center w-9 h-9 rounded-full
                 border chrome-rule"
    >
      {dark ? <Moon className="w-[18px] h-[18px]" strokeWidth={1.75} />
            : <Sun className="w-[18px] h-[18px]" strokeWidth={1.75} />}
    </button>
  );
}

/** Jump-to search. Filters the nav; Enter opens the top hit. */
function CommandSearch() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const q = query.trim().toLowerCase();
  const hits = q
    ? searchTargets(isAdmin).filter((i) => i.label.toLowerCase().includes(q)).slice(0, 6)
    : [];

  function go(to: string) {
    navigate(to);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  return (
    <div className="relative w-full max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" strokeWidth={1.75} />
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        // Blur is delayed so a click on a result lands before the list unmounts.
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) go(hits[0].to); }}
        placeholder="Search or jump to..."
        aria-label="Search or jump to a page"
        className="chrome-field w-full rounded-full pl-9 pr-14 py-2 text-[13px]"
      />
      <span className="absolute right-3 top-1/2 -translate-y-1/2 rounded border chrome-rule
                       px-1.5 py-0.5 text-[10px] font-medium text-gray-500 pointer-events-none">
        ⌘K
      </span>

      {open && hits.length > 0 && (
        <ul
          role="listbox"
          className="chrome-popover absolute z-50 mt-2 w-full overflow-hidden rounded-2xl
                     p-1.5 animate-scale-in"
        >
          {hits.map((hit) => {
            const Icon = hit.icon;
            return (
              <li key={hit.to}>
                <button
                  onMouseDown={() => go(hit.to)}
                  className="chrome-popover-item flex w-full items-center gap-2.5 rounded-xl
                             px-3 py-2 text-left text-[13px]"
                >
                  <Icon className="w-4 h-4 text-gray-500" strokeWidth={1.75} />
                  {hit.label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default function Layout() {
  const { logout, tenantId, isAdmin, email } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebarCollapsed") === "1",
  );

  useEffect(() => {
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  function handleLogout() {
    logout();
    navigate("/login");
  }

  const initials = (email || tenantId || "TA").slice(0, 2).toUpperCase();

  // Active items get a solid violet capsule with a glow — the same treatment
  // the reference gives its selected nav pill. Idle items stay quiet so the
  // active one is the only thing carrying colour in the rail.
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `group relative flex items-center gap-3 rounded-full px-3 py-2 text-[13px] font-semibold
     transition-all duration-200 ${
       isActive
         ? "bg-gradient-to-r from-brand-500 to-brand-500/70 text-white shadow-[0_4px_16px_-4px_rgba(139,92,246,0.65)]"
         : "chrome-item"
     }`;

  return (
    // No opaque background here: the aurora painted on <body> shows through the
    // whole shell, and the chrome floats on it as frosted glass.
    <div className="flex h-screen overflow-hidden">
      {/* ── Sidebar ── */}
      <nav
        aria-label="Primary navigation"
        className={`relative flex-shrink-0 glass-chrome flex flex-col select-none border-r
                    transition-[width] duration-300 ${collapsed ? "w-[68px]" : "w-[252px]"}`}
      >
        {/* Violet bloom behind the logo, and a coral one at the foot — the rail
            reads as lit from within rather than as a flat column. `chrome-bloom`
            dims both in the light theme, where the same alphas stain rather
            than glow. */}
        <div className="chrome-bloom pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(139,92,246,0.18),transparent_55%)]" />
        <div className="chrome-bloom pointer-events-none absolute bottom-0 inset-x-0 h-64 bg-[radial-gradient(circle_at_50%_100%,rgba(249,115,60,0.10),transparent_60%)]" />

        {/* Logo */}
        <div className="relative flex items-center gap-2.5 px-4 h-[64px] flex-shrink-0">
          <div className="relative w-9 h-9 rounded-xl bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700
                          flex items-center justify-center flex-shrink-0
                          shadow-[0_6px_20px_-6px_rgba(139,92,246,0.8)]">
            <Bot className="w-[19px] h-[19px] text-white" strokeWidth={2} />
          </div>
          {!collapsed && (
            <span className="chrome-brand font-display font-bold text-[16px] tracking-tight truncate">
              Evara<span className="text-aurora">AI</span>
            </span>
          )}
        </div>

        {/* Groups */}
        <div className="relative flex-1 px-3 pb-2 overflow-y-auto">
          {NAV_GROUPS.map((group) => {
            const items = group.items.filter((i) => !i.adminOnly || isAdmin);
            if (items.length === 0) return null;
            return (
              <div key={group.title} className="mb-4">
                {!collapsed && (
                  // gray-500, not gray-600: the grey scale inverts with the
                  // theme, and gray-600 is a *dark* grey in light — which is
                  // how these headings ended up invisible.
                  <p className="px-3 pb-1.5 pt-2 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-gray-500">
                    {group.title}
                  </p>
                )}
                {collapsed && <div className="mx-3 my-3 border-t chrome-rule" />}
                <ul className="space-y-0.5" role="list">
                  {items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <li key={item.to}>
                        <NavLink
                          to={item.to}
                          end={item.exact}
                          title={collapsed ? item.label : undefined}
                          className={navClass}
                        >
                          {({ isActive }) => (
                            <>
                              <Icon
                                className={`w-[18px] h-[18px] flex-shrink-0 transition-colors ${
                                  isActive ? "text-white" : "text-gray-500 group-hover:text-gray-800"
                                }`}
                                strokeWidth={1.75}
                              />
                              {!collapsed && (
                                <>
                                  <span className="truncate">{item.label}</span>
                                  {item.badge && (
                                    <span className={`ml-auto rounded-full px-1.5 py-0.5 text-[9.5px] font-bold
                                                     uppercase tracking-wide ${
                                                       isActive
                                                         ? "bg-white/20 text-white"
                                                         : "bg-cta-500/20 text-cta-400"
                                                     }`}>
                                      {item.badge}
                                    </span>
                                  )}
                                </>
                              )}
                            </>
                          )}
                        </NavLink>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="relative px-3 py-3 space-y-0.5 border-t chrome-rule">
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            className="chrome-item flex w-full items-center gap-3 rounded-full px-3 py-2
                       text-[13px] font-semibold"
          >
            <ChevronLeft
              className={`w-[18px] h-[18px] flex-shrink-0 transition-transform ${collapsed ? "rotate-180" : ""}`}
              strokeWidth={1.75}
            />
            {!collapsed && "Collapse"}
          </button>

          {isAdmin && (
            <NavLink to="/settings" title={collapsed ? "Settings" : undefined} className={navClass}>
              {({ isActive }) => (
                <>
                  <Settings
                    className={`w-[18px] h-[18px] flex-shrink-0 ${isActive ? "text-white" : "text-gray-500"}`}
                    strokeWidth={1.75}
                  />
                  {!collapsed && "Settings"}
                </>
              )}
            </NavLink>
          )}

          <button
            onClick={handleLogout}
            title={collapsed ? "Logout" : undefined}
            className="flex w-full items-center gap-3 rounded-full px-3 py-2 text-[13px] font-semibold
                       text-gray-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
          >
            <LogOut className="w-[18px] h-[18px] flex-shrink-0" strokeWidth={1.75} />
            {!collapsed && "Logout"}
          </button>
        </div>
      </nav>

      {/* ── Main column ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="relative flex-shrink-0 h-[64px] glass-chrome border-b
                           flex items-center gap-4 px-6">
          <div className="flex-1 flex justify-center">
            <CommandSearch />
          </div>

          <div className="flex items-center gap-2.5 flex-shrink-0">
            <button
              aria-label="Notifications"
              className="chrome-control relative inline-flex items-center justify-center
                         w-9 h-9 rounded-full"
            >
              <Bell className="w-[18px] h-[18px]" strokeWidth={1.75} />
            </button>
            <div
              title={email || undefined}
              className="inline-flex items-center justify-center w-9 h-9 rounded-full
                         bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 text-white text-[11px]
                         font-bold uppercase tracking-tight
                         shadow-[0_4px_14px_-4px_rgba(139,92,246,0.7)]"
            >
              {initials}
            </div>
            <ThemeToggle />
          </div>
        </header>

        {/* Transparent so the body aurora reads through the content column. */}
        <main className="flex-1 overflow-y-auto min-h-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
