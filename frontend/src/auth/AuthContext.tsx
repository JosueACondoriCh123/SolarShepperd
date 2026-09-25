import type { Session } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useState, type PropsWithChildren } from "react";

import { apiGet, setAccessTokenProvider } from "../api";
import { authMode, supabase } from "./supabase";

export interface UserProfile {
  id: string;
  email: string | null;
  display_name: string;
  timezone: string;
  status: string;
  role: "member";
  is_system_owner: boolean;
  onboarding_completed: boolean;
  notification_preferences: Record<string, boolean>;
  default_pilot_slug: string;
  created_at: string;
  last_seen_at: string | null;
}

interface AuthValue {
  loading: boolean;
  authenticated: boolean;
  emailVerified: boolean;
  isGuest: boolean;
  isOwner: boolean;
  isDevelopment: boolean;
  profile: UserProfile | null;
  signIn: (email: string, password: string, captchaToken?: string) => Promise<void>;
  signUp: (email: string, password: string, captchaToken?: string) => Promise<void>;
  exploreAsGuest: (captchaToken?: string) => Promise<void>;
  setDevRole: (role: "none" | "guest" | "member") => void;
  requestPasswordReset: (email: string, captchaToken?: string) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [devRole, setDevRoleState] = useState<"none" | "guest" | "member">(() => {
    const stored = localStorage.getItem("solarshepherd-dev-role") as "guest" | "member" | "none" | null;
    if (stored && stored !== "none") return stored;
    if (authMode === "development" || !supabase) return "member";
    return stored || "none";
  });

  const setDevRole = useCallback((role: "none" | "guest" | "member") => {
    setDevRoleState(role);
    if (role === "none") {
      localStorage.removeItem("solarshepherd-dev-role");
    } else {
      localStorage.setItem("solarshepherd-dev-role", role);
    }
  }, []);

  const isDevelopment = devRole !== "none" || authMode === "development" || !supabase;
  const isGuest = isDevelopment
    ? devRole === "guest"
    : Boolean(session?.user.is_anonymous);
  const authenticated = isDevelopment ? devRole !== "none" : Boolean(session);
  const emailVerified = isDevelopment
    || Boolean(session?.user.is_anonymous)
    || Boolean(session?.user.email_confirmed_at);

  const refreshProfile = useCallback(async () => {
    if (!authenticated || isGuest) {
      setProfile(null);
      return;
    }
    setProfile(await apiGet<UserProfile>("/me"));
  }, [authenticated, isGuest]);

  useEffect(() => {
    setAccessTokenProvider(async () => {
      if (isDevelopment) return devRole === "guest" ? "dev-guest" : devRole === "member" ? "dev-member" : null;
      const { data } = await supabase!.auth.getSession();
      return data.session?.access_token || null;
    });
    if (isDevelopment) {
      setLoading(false);
      return;
    }
    if (!supabase) {
      setLoading(false);
      return;
    }
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });
    return () => data.subscription.unsubscribe();
  }, [isDevelopment, devRole]);

  useEffect(() => {
    if (!loading) void refreshProfile();
  }, [loading, refreshProfile, session, devRole]);

  const signIn = async (email: string, password: string, captchaToken?: string) => {
    if (isDevelopment) {
      setDevRole("member");
      localStorage.setItem("solarshepherd-dev-role", "member");
      return;
    }
    if (!supabase) throw new Error("Supabase Auth is not configured.");
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
      options: captchaToken ? { captchaToken } : undefined,
    });
    if (error) throw error;
  };

  const signUp = async (email: string, password: string, captchaToken?: string) => {
    if (isDevelopment) {
      setDevRole("member");
      localStorage.setItem("solarshepherd-dev-role", "member");
      return;
    }
    if (!supabase) throw new Error("Supabase Auth is not configured.");
    if (session?.user.is_anonymous) {
      const { error } = await supabase.auth.updateUser(
        { email, password },
        { emailRedirectTo: `${window.location.origin}/verify-email` },
      );
      if (error) throw error;
      return;
    }
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        captchaToken,
        emailRedirectTo: `${window.location.origin}/verify-email`,
      },
    });
    if (error) throw error;
  };

  const exploreAsGuest = async (captchaToken?: string) => {
    if (isDevelopment) {
      setDevRole("guest");
      localStorage.setItem("solarshepherd-dev-role", "guest");
      return;
    }
    if (!supabase) throw new Error("Supabase Auth is not configured.");
    const { error } = await supabase.auth.signInAnonymously({ options: { captchaToken } });
    if (error) throw error;
  };

  const requestPasswordReset = async (email: string, captchaToken?: string) => {
    if (isDevelopment) return;
    if (!supabase) throw new Error("Supabase Auth is not configured.");
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
      captchaToken,
    });
    if (error) throw error;
  };

  const updatePassword = async (password: string) => {
    if (isDevelopment) return;
    if (!supabase) throw new Error("Supabase Auth is not configured.");
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw error;
  };

  const signOut = async () => {
    if (isDevelopment) {
      setDevRole("none");
      localStorage.removeItem("solarshepherd-dev-role");
    } else if (supabase) {
      await supabase.auth.signOut();
    }
    setProfile(null);
    localStorage.removeItem("solarshepherd-last-sync");
    navigator.serviceWorker?.controller?.postMessage({ type: "SOLARSHEPHERD_SIGNOUT" });
    window.dispatchEvent(new CustomEvent("solarshepherd-signout"));
  };

  const value: AuthValue = {
    loading,
    authenticated,
    emailVerified,
    isGuest,
    isOwner: Boolean(profile?.is_system_owner),
    isDevelopment,
    profile,
    signIn,
    signUp,
    exploreAsGuest,
    setDevRole,
    requestPasswordReset,
    updatePassword,
    signOut,
    refreshProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- provider and hook form one boundary
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
