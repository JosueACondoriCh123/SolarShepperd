import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { OwnerRoute, ProtectedRoute } from "./components/ProtectedRoute";
import { AuthPage } from "./pages/AuthPage";
import { LandingPage } from "./pages/LandingPage";
import { LegalPage } from "./pages/LegalPage";
import { PilotProvider, preferredPilotSlug } from "./pilot/PilotContext";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const FieldFlowPage = lazy(() => import("./pages/FieldFlowPage").then((module) => ({ default: module.FieldFlowPage })));
const TelemetryPage = lazy(() => import("./pages/TelemetryPage").then((module) => ({ default: module.TelemetryPage })));
const LandscapePage = lazy(() => import("./pages/LandscapePage").then((module) => ({ default: module.LandscapePage })));
const RoutePlannerPage = lazy(() => import("./pages/RoutePlannerPage").then((module) => ({ default: module.RoutePlannerPage })));
const CapacityPage = lazy(() => import("./pages/CapacityPage").then((module) => ({ default: module.CapacityPage })));
const OperationsPage = lazy(() => import("./pages/OperationsPage").then((module) => ({ default: module.OperationsPage })));
const MissionsPage = lazy(() => import("./pages/MissionsPage").then((module) => ({ default: module.MissionsPage })));
const SamplesPage = lazy(() => import("./pages/SamplesPage").then((module) => ({ default: module.SamplesPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));
const AlertsPage = lazy(() => import("./pages/AlertsPage").then((module) => ({ default: module.AlertsPage })));
const ResponsesPage = lazy(() => import("./pages/ResponsesPage").then((module) => ({ default: module.ResponsesPage })));
const ResponseDetailPage = lazy(() => import("./pages/ResponseDetailPage").then((module) => ({ default: module.ResponseDetailPage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((module) => ({ default: module.TeamPage })));
const DataSourcesPage = lazy(() => import("./pages/DataSourcesPage").then((module) => ({ default: module.DataSourcesPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));

function ConsoleLayout() {
  return (
    <ProtectedRoute>
      <PilotProvider>
        <AppShell>
          <Suspense fallback={<div className="page-loading">Loading scientific workspace…</div>}>
            <Outlet />
          </Suspense>
        </AppShell>
      </PilotProvider>
    </ProtectedRoute>
  );
}

const owner = (element: ReactNode) => <OwnerRoute>{element}</OwnerRoute>;
const legacySections = [
  "dashboard", "field-flow", "telemetry", "landscape", "routes", "capacity", "missions", "samples",
  "reports", "alerts", "responses", "operations", "data-sources", "team", "settings",
] as const;

function LegacyConsoleRedirect({ section }: { section: string }) {
  return <Navigate to={`/app/${preferredPilotSlug()}/${section}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/signup" element={<AuthPage mode="signup" />} />
      <Route path="/forgot-password" element={<AuthPage mode="forgot" />} />
      <Route path="/reset-password" element={<AuthPage mode="reset" />} />
      <Route path="/verify-email" element={<AuthPage mode="verify" />} />
      <Route path="/privacy" element={<LegalPage kind="privacy" />} />
      <Route path="/terms" element={<LegalPage kind="terms" />} />
      <Route path="/app" element={<LegacyConsoleRedirect section="dashboard" />} />
      {legacySections.map((section) => (
        <Route
          key={section}
          path={`/app/${section}`}
          element={<LegacyConsoleRedirect section={section} />}
        />
      ))}
      <Route path="/app/:pilotSlug" element={<ConsoleLayout />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="field-flow" element={<FieldFlowPage />} />
        <Route path="telemetry" element={<TelemetryPage />} />
        <Route path="landscape" element={<LandscapePage />} />
        <Route path="routes" element={<RoutePlannerPage />} />
        <Route path="capacity" element={<CapacityPage />} />
        <Route path="missions" element={<MissionsPage />} />
        <Route path="responses" element={<ResponsesPage />} />
        <Route path="responses/:caseId" element={<ResponseDetailPage />} />
        <Route path="samples" element={<SamplesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="operations" element={owner(<OperationsPage />)} />
        <Route path="data-sources" element={owner(<DataSourcesPage />)} />
        <Route path="team" element={owner(<TeamPage />)} />
      </Route>
      {(["telemetry", "landscape", "routes", "capacity", "operations", "responses"] as const).map((path) => (
        <Route key={path} path={`/${path}`} element={<LegacyConsoleRedirect section={path} />} />
      ))}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
