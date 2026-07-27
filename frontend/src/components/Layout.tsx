import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";

interface NavSection {
  items: NavItem[];
}
interface NavItem {
  to: string;
  label: string;
  icon: JSX.Element;
  exact?: boolean;
}

function HomeIcon()       { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" /></svg>; }
function AssistantsIcon() { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1 1 .03 2.712-1.504 2.712H4.302c-1.534 0-2.504-1.712-1.504-2.712L4.5 15.3" /></svg>; }
function KnowledgeIcon()  { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" /></svg>; }
function AnalyticsIcon()  { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>; }
function SettingsIcon()   { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>; }
function LogoutIcon()     { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" /></svg>; }
function HiringIcon()     { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" /></svg>; }
function InterviewsIcon() { return <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-2.362A.75.75 0 0121.5 8.808v6.384a.75.75 0 01-1.03.67L15.75 13.5m-9-6h6a2.25 2.25 0 012.25 2.25v6a2.25 2.25 0 01-2.25 2.25h-6a2.25 2.25 0 01-2.25-2.25v-6A2.25 2.25 0 016.75 7.5z" /></svg>; }

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { to: "/home",       label: "Home",       icon: <HomeIcon />,       exact: true },
      { to: "/assistants", label: "Assistants", icon: <AssistantsIcon /> },
      { to: "/knowledge",  label: "Knowledge",  icon: <KnowledgeIcon />  },
      { to: "/interviews", label: "Interviews", icon: <InterviewsIcon /> },
      { to: "/hiring-agent", label: "Hiring Agent", icon: <HiringIcon /> },
      { to: "/analytics",  label: "Analytics",  icon: <AnalyticsIcon />  },
    ],
  },
];

export default function Layout() {
  const { logout, tenantId } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  const orgInitial = tenantId ? tenantId.slice(0, 2).toUpperCase() : "AC";

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `group flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors ${
      isActive
        ? "bg-gray-100 text-gray-900"
        : "text-gray-500 hover:bg-gray-100/70 hover:text-gray-900"
    }`;

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* ── Sidebar ── */}
      <nav
        aria-label="Primary navigation"
        className="w-[236px] flex-shrink-0 bg-white border-r border-gray-200/80 flex flex-col select-none"
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 h-[60px] flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-ink-900 flex items-center justify-center flex-shrink-0 shadow-xs">
            <svg className="w-[18px] h-[18px] text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div className="leading-none">
            <span className="font-semibold text-[14px] text-gray-900 tracking-tight block">Kore AI</span>
            <span className="text-[10px] text-gray-400 font-medium">Enterprise Platform</span>
          </div>
        </div>

        {/* Nav */}
        <div className="flex-1 px-3 py-2 overflow-y-auto">
          <p className="eyebrow px-3 pb-1.5 pt-2">Workspace</p>
          {NAV_SECTIONS.map((section, si) => (
            <ul key={si} className="space-y-0.5" role="list">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.exact} className={navClass}>
                    {({ isActive }) => (
                      <>
                        <span className={isActive ? "text-brand-600" : "text-gray-400 group-hover:text-gray-500"}>
                          {item.icon}
                        </span>
                        {item.label}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          ))}
        </div>

        {/* Footer */}
        <div className="px-3 py-3 space-y-1">
          <NavLink to="/settings" className={navClass}>
            {({ isActive }) => (
              <>
                <span className={isActive ? "text-brand-600" : "text-gray-400 group-hover:text-gray-500"}>
                  <SettingsIcon />
                </span>
                Settings
              </>
            )}
          </NavLink>

          {/* Org row + logout */}
          <div className="flex items-center gap-2.5 rounded-lg border border-gray-200/80 px-2.5 py-2 mt-1">
            <div className="avatar w-7 h-7 text-[10px]">{orgInitial}</div>
            <div className="flex-1 min-w-0 leading-tight">
              <span className="text-[12.5px] text-gray-800 truncate block font-medium">My Organisation</span>
              <span className="text-[10.5px] text-gray-400">Free plan</span>
            </div>
            <button onClick={handleLogout} aria-label="Sign out" className="icon-btn w-7 h-7">
              <LogoutIcon />
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
