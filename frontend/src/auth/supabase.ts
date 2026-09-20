import { createClient } from "@supabase/supabase-js";

export const authMode = import.meta.env.VITE_AUTH_MODE || "development";
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || "";
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || "";

export const supabase = supabaseUrl && publishableKey
  ? createClient(supabaseUrl, publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;

export const supabaseConfigured = Boolean(supabase);
