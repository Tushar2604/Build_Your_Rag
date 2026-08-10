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
  ListChecks, LayoutDashboard, PhoneOutgoing, MessageCircle,
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
      { to: "/home", label: "Overview", icon: LayoutDashboard, exact: true },
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
      className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-white/10
                 text-gray-400 transition-colors hover:bg-white/[0.06] hover:text-gray-100"
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
        className="w-full rounded-lg border border-white/10 bg-white/[0.04] pl-9 pr-14 py-2 text-[13px]
                   text-gray-100 placeholder:text-gray-500 transition-colors
                   focus:border-brand-500/60 focus:outline-none focus:bg-white/[0.07]"
      />
      <span className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-white/10
                       px-1.5 py-0.5 text-[10px] font-medium text-gray-500 pointer-events-none">
        ⌘K
      </span>

      {open && hits.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-50 mt-1.5 w-full overflow-hidden rounded-lg border border-white/10
                     bg-ink-900 shadow-modal py-1"
        >
          {hits.map((hit) => {
            const Icon = hit.icon;
            return (
              <li key={hit.to}>
                <button
                  onMouseDown={() => go(hit.to)}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px]
                             text-gray-300 transition-colors hover:bg-white/[0.06] hover:text-white"
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

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium
     transition-all duration-150 ${
       isActive
         ? "bg-brand-500/10 text-brand-400"
         : "text-gray-400 hover:bg-white/[0.05] hover:text-gray-100"
     }`;

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* ── Sidebar ── */}
      <nav
        aria-label="Primary navigation"
        className={`relative flex-shrink-0 bg-ink-950 flex flex-col select-none border-r border-white/[0.06]
                    transition-[width] duration-200 ${collapsed ? "w-[68px]" : "w-[248px]"}`}
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(20,184,166,0.07),transparent_55%)]" />

        {/* Logo */}
        <div className="relative flex items-center gap-2.5 px-4 h-[62px] flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center flex-shrink-0">
            <Bot className="w-[18px] h-[18px] text-white" strokeWidth={2} />
          </div>
          {!collapsed && (
            <span className="font-bold text-[15px] tracking-tight text-white truncate">
              Kore<span className="text-brand-400">AI</span>
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
                  <p className="px-3 pb-1.5 pt-2 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-gray-600">
                    {group.title}
                  </p>
                )}
                {collapsed && <div className="mx-3 my-3 border-t border-white/[0.06]" />}
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
                                  isActive ? "text-brand-400" : "text-gray-500 group-hover:text-gray-300"
                                }`}
                                strokeWidth={1.75}
                              />
                              {!collapsed && (
                                <>
                                  <span className="truncate">{item.label}</span>
                                  {item.badge && (
                                    <span className="ml-auto rounded px-1.5 py-0.5 text-[9.5px] font-semibold
                                                     uppercase tracking-wide bg-brand-500/15 text-brand-400">
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
        <div className="relative px-3 py-3 space-y-0.5 border-t border-white/[0.06]">
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium
                       text-gray-400 transition-colors hover:bg-white/[0.05] hover:text-gray-100"
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
                    className={`w-[18px] h-[18px] flex-shrink-0 ${isActive ? "text-brand-400" : "text-gray-500"}`}
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
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium
                       text-gray-400 transition-colors hover:bg-white/[0.05] hover:text-gray-100"
          >
            <LogOut className="w-[18px] h-[18px] flex-shrink-0" strokeWidth={1.75} />
            {!collapsed && "Logout"}
          </button>
        </div>
      </nav>

      {/* ── Main column ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="flex-shrink-0 h-[62px] bg-ink-950 border-b border-white/[0.06]
                           flex items-center gap-4 px-6">
          <div className="flex-1 flex justify-center">
            <CommandSearch />
          </div>

          <div className="flex items-center gap-2.5 flex-shrink-0">
            <button
              aria-label="Notifications"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg text-gray-400
                         transition-colors hover:bg-white/[0.06] hover:text-gray-100"
            >
              <Bell className="w-[18px] h-[18px]" strokeWidth={1.75} />
            </button>
            <div
              title={email || undefined}
              className="inline-flex items-center justify-center w-9 h-9 rounded-full
                         bg-gradient-to-br from-brand-400 to-brand-600 text-white text-[11px]
                         font-semibold uppercase tracking-tight"
            >
              {initials}
            </div>
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto min-h-0 bg-canvas">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
