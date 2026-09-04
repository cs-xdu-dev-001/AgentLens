import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { AppErrorBoundary } from "./components/AppErrorBoundary.jsx";
import { AuthProvider } from "./auth/AuthProvider.jsx";
import { TooltipProvider } from "./components/Tooltip.jsx";
import "./styles.css";
import "./refinement.css";
import "./template.css";
import "./sidebar-polish.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <AuthProvider>
        <TooltipProvider>
          <App />
        </TooltipProvider>
      </AuthProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);
