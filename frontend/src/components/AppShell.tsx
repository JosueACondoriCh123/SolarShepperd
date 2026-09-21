import {
  Activity, Bell, ChevronRight, CircleDotDashed, DatabaseZap, FileText, Gauge, Hexagon, Home,
  LogOut, Map, MoreHorizontal, Route as RouteIcon, Settings, ShieldAlert, ShieldCheck, Sprout, Users,
} from "lucide-react";
import type { PropsWithChildren } from "react";
import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { countPrivateDrafts } from "../offlineStore";
import { usePilot } from "../pilot/PilotContext";
import { PilotSelector } from "./PilotSelector";

const navigation = [
  { group: "Overview", section: "dashboard", label: "Dashboard", icon: Home, access: "all" },
  { group: "Overview", section: "field-flow", label: "Field decision loop", icon: CircleDotDashed, access: "all" },
  { group: "Observe", section: "telemetry", label: "Live telemetry", icon: Activity, access: "all" },
  { group: "Observe", section: "landscape", label: "Landscape", icon: Map, access: "all" },
  { group: "Plan", section: "routes", label: "Route planner", icon: RouteIcon, access: "all" },
  { group: "Plan", section: "missions", label: "Missions", icon: ChevronRight, access: "member" },
  { group: "Plan", section: "responses", label: "Response Center", icon: ShieldAlert, access: "member" },
  { group: "Evidence", section: "samples", label: "Samples", icon: Sprout, access: "member" },
  { group: "Evidence", section: "capacity", label: "Capacity", icon: Gauge, access: "all" },
  { group: "Evidence", section: "reports", label: "Reports", icon: FileText, access: "member" },
  { group: "Manage", section: "alerts", label: "Alerts", icon: Bell, access: "member" },
  { group: "Manage", section: "operations", label: "Operations", icon: DatabaseZap, access: "owner" },
  { group: "Manage", section: "data-sources", label: "Data sources", icon: DatabaseZap, access: "owner" },
  { group: "Manage", section: "team", label: "Team", icon: Users, access: "owner" },
  { group: "Manage", section: "settings", label: "Settings", icon: Settings, access: "member" },
] as const;

function Brand() {
  const { pilot } = usePilot();
  return (
    <NavLink to={`/app/${pilot.slug}/dashboard`} className="brand">
      <div className="brand-mark" aria-hidden="true">
        <Hexagon size={25} strokeWidth={1.5} />
        <span />
      </div>
      <div><strong>SolarShepherd</strong><small>Field console // v0.3</small></div>
    </NavLink>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const auth = useAuth();
  const { pilot, pilots, selectPilot } = usePilot();
  const navigate = useNavigate();
  const location = useLocation();
  const [online, setOnline] = useState(navigator.onLine);
  const [lastSync, setLastSync] = useState(localStorage.getItem("solarshepherd-last-sync"));
  const pilotNotice = (location.state as { pilotNotice?: string } | null)?.pilotNotice;

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine);
    const updateSync = (event: Event) => setLastSync((event as CustomEvent<string>).detail);
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    window.addEventListener("solarshepherd-sync", updateSync);
    return () => {
      window.removeEventListener("online", updateOnline);
      window.removeEventListener("offline", updateOnline);
      window.removeEventListener("solarshepherd-sync", updateSync);
    };
  }, []);

  const visible = navigation.filter((item) => item.access === "all"
    || (item.access === "member" && !auth.isGuest)
    || (item.access === "owner" && auth.isOwner));
  const pathFor = (section: string) => `/app/${pilot.slug}/${section}`;
  const logout = async () => {
    if (auth.profile && await countPrivateDrafts(auth.profile.id) > 0) {
      navigate(pathFor("settings") + "?logout=1");
      return;
    }
    await auth.signOut();
    navigate("/");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <div className="pilot-chip"><PilotSelector pilot={pilot} pilots={pilots} onSelect={selectPilot} /></div>
        <nav className="primary-nav" aria-label="Primary navigation">
          {["Overview", "Observe", "Plan", "Evidence", "Manage"].map((group) => {
            const items = visible.filter((item) => item.group === group);
            return items.length ? (
              <div className="nav-group" key={group}>
                <span className="nav-group-label">{group}</span>
                {items.map(({ section, label, icon: Icon }) => (
                  <NavLink key={section} to={pathFor(section)} className={({ isActive }) => isActive ? "active" : ""}>
                    <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
                  </NavLink>
                ))}
              </div>
            ) : null;
          })}
        </nav>
        <div className="sidebar-account">
          <div>
            <strong>{auth.isGuest ? "Guest explorer" : auth.profile?.display_name || "Field member"}</strong>
            <span>{auth.isOwner ? "System owner" : auth.isGuest ? "Read-only access" : "Member"}</span>
          </div>
          <button aria-label="Log out" onClick={() => void logout()}><LogOut size={16} /></button>
        </div>
        <div className="sidebar-trust"><ShieldCheck size={19} /><div><strong>Evidence first</strong><span>No fabricated field values</span></div></div>
      </aside>
      <div className="workspace">
        <header className="mobile-header"><Brand /><PilotSelector pilot={pilot} pilots={pilots} onSelect={selectPilot} /></header>
        {pilotNotice && <div className="pilot-notice" role="status">{pilotNotice}</div>}
        {!online && <div className="connectivity-banner">OFFLINE READ-ONLY · LAST SYNC {lastSync ? new Date(lastSync).toLocaleString() : "UNKNOWN"}</div>}
        <main key={pilot.slug}>{children}</main>
        <nav className="mobile-nav" aria-label="Mobile navigation">
          {[
            { section: "dashboard", label: "Home", icon: Home },
            { section: "landscape", label: "Map", icon: Map },
            { section: auth.isGuest ? "routes" : "missions", label: auth.isGuest ? "Route" : "Missions", icon: RouteIcon },
            { section: auth.isGuest ? "telemetry" : "alerts", label: auth.isGuest ? "Weather" : "Alerts", icon: Bell },
            { section: auth.isGuest ? "dashboard" : "settings", label: "More", icon: MoreHorizontal },
          ].map(({ section, label, icon: Icon }) => (
            <NavLink key={section} to={pathFor(section)} aria-label={label}><Icon size={20} /><span>{label}</span></NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
