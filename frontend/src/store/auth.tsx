import {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { login as apiLogin, register as apiRegister, TokenResponse } from "../api/auth";

const ADMIN_ROLES = ["owner", "admin"];

interface AuthState {
  accessToken: string | null;
  tenantId: string | null;
  userId: string | null;
  role: string | null;
}

interface AuthContextValue extends AuthState {
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (tenantName: string, email: string, password: string) => Promise<void>;
  /** Same effect as login/register — used after accepting a team invite,
   * which returns the same TokenResponse shape. */
  applySession: (resp: TokenResponse) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function saveTokens(resp: TokenResponse) {
  localStorage.setItem("access_token", resp.access_token);
  localStorage.setItem("refresh_token", resp.refresh_token);
  localStorage.setItem("tenant_id", resp.tenant_id);
  localStorage.setItem("user_id", resp.user_id);
  localStorage.setItem("role", resp.role);
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("tenant_id");
  localStorage.removeItem("user_id");
  localStorage.removeItem("role");
}

function readState(): AuthState {
  return {
    accessToken: localStorage.getItem("access_token"),
    tenantId: localStorage.getItem("tenant_id"),
    userId: localStorage.getItem("user_id"),
    role: localStorage.getItem("role"),
  };
}

function stateFromResponse(resp: TokenResponse): AuthState {
  return { accessToken: resp.access_token, tenantId: resp.tenant_id, userId: resp.user_id, role: resp.role };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(readState);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await apiLogin(email, password);
    saveTokens(resp);
    setState(stateFromResponse(resp));
  }, []);

  const register = useCallback(async (tenantName: string, email: string, password: string) => {
    const resp = await apiRegister(tenantName, email, password);
    saveTokens(resp);
    setState(stateFromResponse(resp));
  }, []);

  const applySession = useCallback((resp: TokenResponse) => {
    saveTokens(resp);
    setState(stateFromResponse(resp));
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setState({ accessToken: null, tenantId: null, userId: null, role: null });
  }, []);

  return (
    <AuthContext.Provider
      value={{
        ...state,
        isAuthenticated: !!state.accessToken,
        isAdmin: !!state.role && ADMIN_ROLES.includes(state.role),
        login,
        register,
        applySession,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
