import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";

import Login from "./pages/auth/Login";
import Register from "./pages/auth/Register";
import AcceptInvite from "./pages/auth/AcceptInvite";

import AdminDashboard from "./pages/admin/Dashboard";
import AdminSessions from "./pages/admin/Sessions";
import AdminStudents from "./pages/admin/Students";
import AdminUsers from "./pages/admin/Users";
import AdminPayments from "./pages/admin/Payments";
import AdminExpenses from "./pages/admin/Expenses";
import AdminPayouts from "./pages/admin/Payouts";
import AdminReports from "./pages/admin/Reports";
import AdminAuditLogs from "./pages/admin/AuditLogs";
import AdminDuesFollowup from "./pages/admin/DuesFollowup";
import AdminCoachPayslip from "./pages/admin/CoachPayslip";
import AdminSettings from "./pages/admin/Settings";
import RegisterStudent from "./pages/auth/RegisterStudent";

import CoachDashboard from "./pages/coach/Dashboard";
import CoachSessions from "./pages/coach/Sessions";
import CoachSessionDetail from "./pages/coach/SessionDetail";

import ParentDashboard from "./pages/parent/Dashboard";
import ParentChildren from "./pages/parent/Children";
import ParentPayments from "./pages/parent/Payments";
import ParentAttendance from "./pages/parent/Attendance";
import ParentProgress from "./pages/parent/Progress";

import Messages from "./pages/shared/Messages";

function RoleRedirect() {
  const { user } = useAuth();
  if (user === null) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "admin") return <Navigate to="/admin/dashboard" replace />;
  if (user.role === "coach") return <Navigate to="/coach/dashboard" replace />;
  return <Navigate to="/parent/dashboard" replace />;
}

const L = (Page) => (
  <ProtectedRoute>
    <Layout><Page /></Layout>
  </ProtectedRoute>
);

const LR = (Page, roles) => (
  <ProtectedRoute roles={roles}>
    <Layout><Page /></Layout>
  </ProtectedRoute>
);

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Toaster position="top-right" richColors />
          <Routes>
            <Route path="/" element={<RoleRedirect />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/register-student" element={<RegisterStudent />} />
            <Route path="/accept-invite/:token" element={<AcceptInvite />} />

            <Route path="/admin/dashboard" element={LR(AdminDashboard, ["admin"])} />
            <Route path="/admin/sessions" element={LR(AdminSessions, ["admin"])} />
            <Route path="/admin/students" element={LR(AdminStudents, ["admin"])} />
            <Route path="/admin/users" element={LR(AdminUsers, ["admin"])} />
            <Route path="/admin/payments" element={LR(AdminPayments, ["admin"])} />
            <Route path="/admin/expenses" element={LR(AdminExpenses, ["admin"])} />
            <Route path="/admin/payouts" element={LR(AdminPayouts, ["admin"])} />
            <Route path="/admin/reports" element={LR(AdminReports, ["admin"])} />
            <Route path="/admin/audit-logs" element={LR(AdminAuditLogs, ["admin"])} />
            <Route path="/admin/dues" element={LR(AdminDuesFollowup, ["admin"])} />
            <Route path="/admin/coach-payslip" element={LR(AdminCoachPayslip, ["admin", "coach"])} />
            <Route path="/admin/settings" element={LR(AdminSettings, ["admin"])} />

            <Route path="/coach/dashboard" element={LR(CoachDashboard, ["coach"])} />
            <Route path="/coach/sessions" element={LR(CoachSessions, ["coach"])} />
            <Route path="/coach/sessions/:id" element={LR(CoachSessionDetail, ["coach", "admin"])} />

            <Route path="/parent/dashboard" element={LR(ParentDashboard, ["parent"])} />
            <Route path="/parent/children" element={LR(ParentChildren, ["parent"])} />
            <Route path="/parent/payments" element={LR(ParentPayments, ["parent"])} />
            <Route path="/parent/attendance" element={LR(ParentAttendance, ["parent"])} />
            <Route path="/parent/progress" element={LR(ParentProgress, ["parent"])} />

            <Route path="/messages" element={L(Messages)} />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
