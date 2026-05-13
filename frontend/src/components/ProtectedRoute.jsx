import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-slate-500 text-sm" data-testid="auth-loading">Loading…</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) {
    const fallback = user.role === "admin" ? "/admin/dashboard"
      : user.role === "coach" ? "/coach/dashboard" : "/parent/dashboard";
    return <Navigate to={fallback} replace />;
  }
  return children;
}
