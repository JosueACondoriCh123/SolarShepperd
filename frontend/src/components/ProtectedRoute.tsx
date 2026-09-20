import type { PropsWithChildren } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) return <div className="page-loading">Checking field credentials…</div>;
  if (!auth.authenticated) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (!auth.emailVerified) return <Navigate to="/verify-email" replace />;
  return children;
}

export function OwnerRoute({ children }: PropsWithChildren) {
  const auth = useAuth();
  const { pilotSlug = "jkuat" } = useParams();
  if (auth.loading || (!auth.isGuest && !auth.profile)) return <div className="page-loading">Checking owner permissions…</div>;
  if (!auth.isOwner) return <Navigate to={`/app/${pilotSlug}/dashboard`} replace />;
  return children;
}
