/**
 * Root application component.
 *
 * Routing strategy:
 *   /login          → public (unauthenticated)
 *   /               → protected → role-aware dashboard
 *   /contracts/*    → protected → admin + reviewer
 *   /chat           → protected → all roles (response scoped by role)
 *   /users          → protected → admin only
 *   /audit          → protected → admin only
 *
 * Role enforcement:
 *   - Route-level: ProtectedRoute checks JWT role from Zustand store
 *   - Data-level:  ChromaDB filter on the backend (tamper-proof)
 */
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuthStore } from "./store/authStore";

// ── Lazy-loaded pages (code-split — only loaded when navigated to) ────────────
import { lazy, Suspense } from "react";

const LoginPage    = lazy(() => import("./pages/LoginPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const ContractsPage = lazy(() => import("./pages/ContractsPage"));
const ChatPage     = lazy(() => import("./pages/ChatPage"));
const UsersPage    = lazy(() => import("./pages/UsersPage"));

// ── Loading fallback ──────────────────────────────────────────────────────────
function PageLoader() {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      height: "100vh",
      fontFamily: "system-ui, sans-serif",
      color: "#6b7280",
    }}>
      Loading…
    </div>
  );
}

// ── Protected route guard ─────────────────────────────────────────────────────
interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: "admin" | "reviewer" | "viewer";
}

function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { isAuthenticated, role } = useAuthStore();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRole && role !== requiredRole) {
    // Non-admin trying to access admin route → redirect to dashboard
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected — all authenticated roles */}
        <Route path="/" element={
          <ProtectedRoute><DashboardPage /></ProtectedRoute>
        } />
        <Route path="/chat" element={
          <ProtectedRoute><ChatPage /></ProtectedRoute>
        } />

        {/* Protected — admin + reviewer */}
        <Route path="/contracts/*" element={
          <ProtectedRoute><ContractsPage /></ProtectedRoute>
        } />

        {/* Protected — admin only */}
        <Route path="/users" element={
          <ProtectedRoute requiredRole="admin"><UsersPage /></ProtectedRoute>
        } />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
