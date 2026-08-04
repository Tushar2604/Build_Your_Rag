import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Bot, BookOpen, LineChart, Settings, LogOut,
  Users2, PhoneCall, Radio, Sparkles,
} from "lucide-react";
import { useAuth } from "../store/auth";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  exact?: boolean;
  /** Only shown to Owner/Admin roles — the "admin panel" surfaces. */
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/home",         label: "Home",         icon: LayoutDashboard, exact: true },
  { to: "/assistants",   label: "Assistants",   icon: Bot },
  { to: "/knowledge",    label: "Knowledge",    icon: BookOpen },
  { to: "/interviews",   label: "Interviews",   icon: PhoneCall, adminOnly: true },
  { to: "/channels",     label: "Channels",     icon: Radio,     adminOnly: true },
  { to: "/hiring-agent", label: "Hiring Agent", icon: Users2,    adminOnly: true },
  { to: "/team",         label: "Team",         icon: Users2,    adminOnly: true },
  { to: "/analytics",    label: "Analytics",    icon: LineChart },
];

export default function Layout() {
  const { logout, tenantId, isAdmin } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  const orgInitial = tenantId ? tenantId.slice(0, 2).toUpperCase() : "AC";

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `group relative flex items-center gap-2.5 pl-3 pr-3 py-2 rounded-lg text-[13px] font-medium
     transition-all duration-150 ${
      isActive
        ? "bg-white/[0.07] text-white before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:h-4 before:w-[3px] before:rounded-full before:bg-brand-400"
        : "text-gray-400 hover:bg-white/[0.04] hover:text-gray-100"
    }`;

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* ── Sidebar ── */}
      <nav
        aria-label="Primary navigation"
        className="relative w-[236px] flex-shrink-0 bg-ink-950 flex flex-col select-none overflow-hidden"
      >
        {/* Ambient texture — faint radial glow, not flat black */}
        <div className="pointer-events-none absolute inset-0 mesh-bg-navy opacity-90" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(255,255,255,0.05),transparent_60%)]" />

        {/* Logo */}
        <div className="relative flex items-center gap-2.5 px-4 h-[60px] flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-brand-900/40">
            <Sparkles className="w-[18px] h-[18px] text-white" strokeWidth={2} />
          </div>
          <div className="leading-none">
            <span className="font-semibold text-[14px] text-white tracking-tight block">Kore AI</span>
            <span className="text-[10px] text-gray-500 font-medium">Enterprise Platform</span>
          </div>
        </div>

        {/* Nav */}
        <div className="relative flex-1 px-3 py-2 overflow-y-auto">
          <p className="px-3 pb-1.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-gray-600">Workspace</p>
          <ul className="space-y-0.5" role="list">
            {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.exact} className={navClass}>
                    {({ isActive }) => (
                      <>
                        <Icon
                          className={`w-[18px] h-[18px] transition-colors ${isActive ? "text-brand-400" : "text-gray-500 group-hover:text-gray-300"}`}
                          strokeWidth={1.75}
                        />
                        {item.label}
                      </>
                    )}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Footer */}
        <div className="relative px-3 py-3 space-y-1">
          {isAdmin && (
            <NavLink to="/settings" className={navClass}>
              {({ isActive }) => (
                <>
                  <Settings
                    className={`w-[18px] h-[18px] transition-colors ${isActive ? "text-brand-400" : "text-gray-500 group-hover:text-gray-300"}`}
                    strokeWidth={1.75}
                  />
                  Settings
                </>
              )}
            </NavLink>
          )}

          {/* Org row + logout */}
          <div className="flex items-center gap-2.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 mt-1">
            <div className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-white font-semibold uppercase tracking-tight text-[10px]">
              {orgInitial}
            </div>
            <div className="flex-1 min-w-0 leading-tight">
              <span className="text-[12.5px] text-gray-200 truncate block font-medium">My Organisation</span>
              <span className="text-[10.5px] text-gray-500">Free plan</span>
            </div>
            <button
              onClick={handleLogout}
              aria-label="Sign out"
              className="inline-flex items-center justify-center w-7 h-7 rounded-md text-gray-500 transition-colors hover:bg-white/10 hover:text-gray-100"
            >
              <LogOut className="w-[15px] h-[15px]" strokeWidth={1.75} />
            </button>
          </div>
        </div>
      </nav>

      {/* ── Main ── */}
      <main className="flex-1 overflow-y-auto min-h-0 bg-canvas">
        <Outlet />
      </main>
    </div>
  );
}
