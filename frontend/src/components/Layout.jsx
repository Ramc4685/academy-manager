import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  LayoutDashboard, CalendarDays, Users, UserCircle2, GraduationCap, DollarSign,
  Receipt, Coins, FileBarChart2, ShieldCheck, MessageSquare, Bell, LogOut,
  Menu, X,
} from "lucide-react";

const adminNav = [
  { to: "/admin/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/admin/sessions", icon: CalendarDays, label: "Sessions" },
  { to: "/calendar", icon: CalendarDays, label: "Calendar" },
  { to: "/admin/students", icon: GraduationCap, label: "Students" },
  { to: "/admin/waitlist", icon: Bell, label: "Waitlist" },
  { to: "/admin/users", icon: Users, label: "Coaches & Parents" },
  { to: "/admin/payments", icon: DollarSign, label: "Payments" },
  { to: "/admin/dues", icon: Receipt, label: "Dues Followup" },
  { to: "/admin/expenses", icon: Receipt, label: "Expenses" },
  { to: "/admin/payouts", icon: Coins, label: "Coach Payouts" },
  { to: "/admin/coach-payslip", icon: Coins, label: "Coach Payslip" },
  { to: "/admin/reports", icon: FileBarChart2, label: "Reports" },
  { to: "/admin/audit-logs", icon: ShieldCheck, label: "Audit Logs" },
  { to: "/admin/settings", icon: ShieldCheck, label: "Settings" },
  { to: "/messages", icon: MessageSquare, label: "Messages" },
];

const coachNav = [
  { to: "/coach/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/coach/sessions", icon: CalendarDays, label: "My Sessions" },
  { to: "/calendar", icon: CalendarDays, label: "Calendar" },
  { to: "/admin/coach-payslip", icon: Coins, label: "My Payslip" },
  { to: "/messages", icon: MessageSquare, label: "Messages" },
];

const parentNav = [
  { to: "/parent/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/parent/children", icon: GraduationCap, label: "My Children" },
  { to: "/calendar", icon: CalendarDays, label: "Calendar" },
  { to: "/parent/payments", icon: DollarSign, label: "Payments" },
  { to: "/parent/attendance", icon: CalendarDays, label: "Attendance" },
  { to: "/parent/progress", icon: UserCircle2, label: "Progress" },
  { to: "/messages", icon: MessageSquare, label: "Messages" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [notifs, setNotifs] = useState([]);
  const [showNotifs, setShowNotifs] = useState(false);

  const nav = user?.role === "admin" ? adminNav : user?.role === "coach" ? coachNav : parentNav;

  const loadNotifs = async () => {
    try {
      const { data } = await api.get("/notifications");
      setNotifs(data);
    } catch { /* */ }
  };

  useEffect(() => {
    loadNotifs();
    const t = setInterval(loadNotifs, 30000);
    return () => clearInterval(t);
  }, []);

  const unread = notifs.filter((n) => !n.read).length;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const markAllRead = async () => {
    await api.post("/notifications/read-all");
    loadNotifs();
  };

  return (
    <div className="min-h-screen bg-slate-50 flex font-body">
      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-40 w-64 bg-slate-900 text-slate-200 transform ${open ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0 transition-transform duration-200`}
        data-testid="app-sidebar"
      >
        <div className="h-16 flex items-center gap-3 px-6 border-b border-slate-800">
          <div className="w-9 h-9 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-bold text-lg font-display">
            B
          </div>
          <div className="leading-tight">
            <div className="font-display font-bold text-white tracking-tight">Badminton</div>
            <div className="text-[11px] text-slate-400 uppercase tracking-[0.18em]">Academy Manager</div>
          </div>
        </div>
        <nav className="p-3 space-y-1">
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-yellow-400 text-slate-900 font-semibold"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white"
                }`
              }
              data-testid={`nav-${to.replace(/\//g, "-")}`}
            >
              <Icon className="w-4 h-4" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-4 left-0 right-0 px-3">
          <button
            onClick={handleLogout}
            data-testid="logout-button"
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
          >
            <LogOut className="w-4 h-4" /> <span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Overlay on mobile */}
      {open && (
        <div className="lg:hidden fixed inset-0 bg-black/40 z-30" onClick={() => setOpen(false)} />
      )}

      <div className="flex-1 min-w-0 lg:ml-0">
        {/* Top bar */}
        <header className="sticky top-0 z-20 h-16 backdrop-blur-xl bg-white/80 border-b border-slate-200 flex items-center justify-between px-4 lg:px-8">
          <button onClick={() => setOpen(true)} className="lg:hidden p-2 rounded-md text-slate-700" data-testid="open-menu">
            <Menu className="w-5 h-5" />
          </button>
          <div className="hidden lg:block">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Welcome back</div>
            <div className="font-display font-semibold text-slate-900 tracking-tight">{user?.name || user?.email}</div>
          </div>
          <div className="flex items-center gap-3 relative">
            <button
              data-testid="notifications-button"
              onClick={() => setShowNotifs((v) => !v)}
              className="relative p-2 rounded-lg hover:bg-slate-100 text-slate-700"
            >
              <Bell className="w-5 h-5" />
              {unread > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-blue-600 text-white text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
                  {unread}
                </span>
              )}
            </button>
            {showNotifs && (
              <div className="absolute right-0 top-12 w-80 max-h-96 overflow-y-auto bg-white border border-slate-200 rounded-xl shadow-lg z-50" data-testid="notifications-panel">
                <div className="flex items-center justify-between p-3 border-b border-slate-100">
                  <div className="font-display font-semibold text-slate-900 text-sm">Notifications</div>
                  <button onClick={markAllRead} className="text-xs text-blue-600 hover:underline" data-testid="mark-all-read">
                    Mark all read
                  </button>
                </div>
                {notifs.length === 0 && (
                  <div className="p-6 text-center text-sm text-slate-500">No notifications</div>
                )}
                {notifs.map((n) => (
                  <div key={n.id} className={`p-3 border-b border-slate-100 text-sm ${!n.read ? "bg-blue-50/50" : ""}`}>
                    <div className="font-medium text-slate-900">{n.title}</div>
                    <div className="text-slate-600 text-xs mt-0.5">{n.message}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-slate-200">
              <div className="text-right">
                <div className="text-xs text-slate-500">{user?.role}</div>
                <div className="text-sm font-medium text-slate-900">{user?.email}</div>
              </div>
            </div>
          </div>
        </header>

        <main className="p-4 lg:p-8 max-w-[1400px] mx-auto">{children}</main>
      </div>
    </div>
  );
}
