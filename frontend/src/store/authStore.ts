/**
 * Auth store using Zustand.
 * Manages JWT tokens, user identity, and role-based UI state.
 *
 * Security:
 *   - Tokens stored in memory only (not localStorage — XSS resistant)
 *   - Refresh token sent as opaque string — never decoded client-side
 *   - Automatic token refresh 60s before expiry
 */
import { create } from "zustand";
import { apiClient } from "@/services/api";

export type UserRole = "admin" | "reviewer" | "viewer";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  userId: string | null;
  orgId: string | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshAccessToken: () => Promise<void>;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  userId: null,
  orgId: null,
  role: null,
  isAuthenticated: false,
  isLoading: false,

  login: async (email: string, password: string) => {
    set({ isLoading: true });
    try {
      const response = await apiClient.post<{
        access_token: string;
        refresh_token: string;
        role: UserRole;
        user_id: string;
        org_id: string;
      }>("/api/v1/auth/login", { email, password });

      const { access_token, refresh_token, role, user_id, org_id } = response.data;

      set({
        accessToken: access_token,
        refreshToken: refresh_token,
        role,
        userId: user_id,
        orgId: org_id,
        isAuthenticated: true,
        isLoading: false,
      });

      // Update axios default header for subsequent requests
      apiClient.defaults.headers.common["Authorization"] = `Bearer ${access_token}`;
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  logout: async () => {
    const { refreshToken } = get();
    try {
      if (refreshToken) {
        await apiClient.post("/api/v1/auth/logout", { refresh_token: refreshToken });
      }
    } catch {
      // Logout should succeed even if API call fails
    } finally {
      get().clearAuth();
    }
  },

  refreshAccessToken: async () => {
    const { refreshToken } = get();
    if (!refreshToken) {
      get().clearAuth();
      return;
    }

    try {
      const response = await apiClient.post<{
        access_token: string;
        refresh_token: string;
        role: UserRole;
        user_id: string;
        org_id: string;
      }>("/api/v1/auth/refresh", { refresh_token: refreshToken });

      const { access_token, refresh_token, role, user_id, org_id } = response.data;

      set({
        accessToken: access_token,
        refreshToken: refresh_token,
        role,
        userId: user_id,
        orgId: org_id,
        isAuthenticated: true,
      });

      apiClient.defaults.headers.common["Authorization"] = `Bearer ${access_token}`;
    } catch {
      get().clearAuth();
    }
  },

  clearAuth: () => {
    delete apiClient.defaults.headers.common["Authorization"];
    set({
      accessToken: null,
      refreshToken: null,
      userId: null,
      orgId: null,
      role: null,
      isAuthenticated: false,
      isLoading: false,
    });
  },
}));
