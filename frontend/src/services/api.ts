/// <reference types="vite/client" />
/**
 * Configured Axios instance with JWT interceptor and auto-refresh.
 */
import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL ||
  (window.location.hostname.includes("app.github.dev")
    ? `https://${window.location.hostname.replace("-5173", "-8000").replace("-5174", "-8000")}`
    : "http://localhost:8000");

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

let isRefreshing = false;
let failedQueue: Array<{ resolve: (token: string) => void; reject: (error: unknown) => void }> = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((p) => { if (error) p.reject(error); else if (token) p.resolve(token); });
  failedQueue = [];
};

apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes("/auth/")
    ) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => { failedQueue.push({ resolve, reject }); })
          .then((token) => { originalRequest.headers["Authorization"] = `Bearer ${token}`; return apiClient(originalRequest); });
      }
      originalRequest._retry = true;
      isRefreshing = true;
      try {
        const { useAuthStore } = await import("../store/authStore");
        await useAuthStore.getState().refreshAccessToken();
        const newToken = useAuthStore.getState().accessToken;
        if (!newToken) throw new Error("No token after refresh");
        processQueue(null, newToken);
        originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        const { useAuthStore } = await import("../store/authStore");
        useAuthStore.getState().clearAuth();
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }
    return Promise.reject(error);
  }
);

export interface ApiError { detail: string; trace_id?: string; }

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    return data?.detail ?? error.message ?? "An unexpected error occurred";
  }
  return error instanceof Error ? error.message : "An unexpected error occurred";
}
