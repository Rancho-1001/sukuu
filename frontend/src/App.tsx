import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth/context";
import { RequireAuth, RequireRole } from "./auth/guards";
import { homeFor } from "./auth/roles";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/admin/DashboardPage";
import { ChildBalancePage } from "./pages/parent/ChildBalancePage";
import { MyChildrenPage } from "./pages/parent/MyChildrenPage";
import { CollectionsPage } from "./pages/staff/CollectionsPage";

/** Sends each role to the screen where their job starts. */
function Home() {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;
  return <Navigate to={user ? homeFor(user.role) : "/login"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />

          {/* Admin */}
          <Route element={<RequireRole roles={["admin"]} />}>
            <Route path="/dashboard" element={<DashboardPage />} />
          </Route>

          {/* Bursar and admin */}
          <Route element={<RequireRole roles={["admin", "staff"]} />}>
            <Route path="/collections" element={<CollectionsPage />} />
          </Route>

          {/* Parent */}
          <Route element={<RequireRole roles={["parent"]} />}>
            <Route path="/my-children" element={<MyChildrenPage />} />
            <Route path="/my-children/:studentId" element={<ChildBalancePage />} />
          </Route>

          <Route path="*" element={<Home />} />
        </Route>
      </Route>
    </Routes>
  );
}
