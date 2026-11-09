import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spin } from "antd";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import MainLayout from "./layouts/MainLayout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import DatasetsPage from "./pages/DatasetsPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import TasksPage from "./pages/TasksPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import AnnotationWorkspacePage from "./pages/AnnotationWorkspacePage";
import ExportsPage from "./pages/ExportsPage";
import ExportDetailPage from "./pages/ExportDetailPage";
import EvaluationsPage from "./pages/EvaluationsPage";
import EvaluationDetailPage from "./pages/EvaluationDetailPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import ProtocolsPage from "./pages/ProtocolsPage";
import UsersPage from "./pages/UsersPage";
import AccessTokensPage from "./pages/AccessTokensPage";
import DeviceAuthorizePage from "./pages/DeviceAuthorizePage";
import type { ReactNode } from "react";

function Loading() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <Spin size="large" />
    </div>
  );
}

function PrivateRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

function AdminRoute({ children }: { children: ReactNode }) {
  const { user, loading, isAdmin } = useAuth();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <PrivateRoute>
                <MainLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="datasets" element={<DatasetsPage />} />
            <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
            <Route path="tasks" element={<TasksPage />} />
            <Route path="tasks/:taskId" element={<TaskDetailPage />} />
            <Route path="annotations" element={<Navigate to="/datasets" replace />} />
            <Route
              path="datasets/:datasetId/annotate/:taskId/:caseId"
              element={<AnnotationWorkspacePage />}
            />
            <Route
              path="tasks/:taskId/annotate/:caseId"
              element={<AnnotationWorkspacePage />}
            />
            <Route path="exports" element={<ExportsPage />} />
            <Route path="exports/:exportId" element={<ExportDetailPage />} />
            <Route path="experiments" element={<ExperimentsPage />} />
            <Route path="evaluations" element={<EvaluationsPage />} />
            <Route
              path="evaluations/:evaluationId"
              element={<EvaluationDetailPage />}
            />
            <Route path="access" element={<AccessTokensPage />} />
            <Route path="device" element={<DeviceAuthorizePage />} />
            <Route
              path="protocols"
              element={
                <AdminRoute>
                  <ProtocolsPage />
                </AdminRoute>
              }
            />
            <Route
              path="users"
              element={
                <AdminRoute>
                  <UsersPage />
                </AdminRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
