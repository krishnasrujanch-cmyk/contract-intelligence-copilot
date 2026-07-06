/**
 * React application entry point.
 *
 * Bootstrap order:
 *   1. TanStack Query client (server state + caching)
 *   2. React Router (SPA routing + protected routes)
 *   3. App component (role-aware layout)
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:          60 * 1000,   // 1 minute — prevent excessive refetches
      retry:              1,
      refetchOnWindowFocus: false,      // don't refetch on tab switch in a legal app
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found. Check index.html.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
