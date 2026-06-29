import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../store/auth";

export default function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <Outlet /> : <Navigate to="/login" replace />;
}
