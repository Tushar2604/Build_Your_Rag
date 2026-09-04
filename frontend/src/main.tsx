import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Type is loaded from the <link> in index.html (Sora + Plus Jakarta Sans) so
// the two families arrive together in one stylesheet rather than five chunks.
import "./index.css";
import App from "./App";
import { ThemeProvider } from "./store/theme";
import { OnboardingProvider } from "./store/onboarding";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <OnboardingProvider>
        <App />
      </OnboardingProvider>
    </ThemeProvider>
  </StrictMode>,
);
