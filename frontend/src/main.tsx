import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Type is loaded from the <link> in index.html (Sora + Plus Jakarta Sans) so
// the two families arrive together in one stylesheet rather than five chunks.
import "./index.css";
import App from "./App";
import { ThemeProvider } from "./store/theme";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      {/* Onboarding state is NOT provided here: it is an authenticated read,
          and this tree also renders the public landing page, the embeddable
          widget and the candidate interview screen. It lives in Layout, which
          only ever mounts behind ProtectedRoute. */}
      <App />
    </ThemeProvider>
  </StrictMode>,
);
