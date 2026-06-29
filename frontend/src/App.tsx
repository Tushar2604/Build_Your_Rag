import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./store/auth";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";

import LoginPage          from "./pages/LoginPage";
import RegisterPage       from "./pages/RegisterPage";
import WidgetChatPage     from "./pages/WidgetChatPage";
import EmbedChatPage      from "./pages/EmbedChatPage";
import HomePage           from "./pages/HomePage";
import AssistantsPage     from "./pages/AssistantsPage";
import AssistantDetailPage from "./pages/AssistantDetailPage";
import KnowledgePage      from "./pages/KnowledgePage";
import AnalyticsPage      from "./pages/AnalyticsPage";
import SettingsPage       from "./pages/SettingsPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/login"    element={<LoginPage />}    />
          <Route path="/register" element={<RegisterPage />} />

          {/* Public widget — unauthenticated share link */}
          <Route path="/c/:publicKey"     element={<WidgetChatPage />} />
          {/* Iframe-optimized embed — no platform chrome, postMessage API */}
          <Route path="/embed/:publicKey" element={<EmbedChatPage />} />

          {/* Authenticated routes */}
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              {/* Redirect root → home */}
              <Route index element={<Navigate to="/home" replace />} />

              <Route path="/home"       element={<HomePage />}           />
              <Route path="/assistants" element={<AssistantsPage />}     />
              <Route path="/assistants/:id" element={<AssistantDetailPage />} />
              <Route path="/knowledge"  element={<KnowledgePage />}      />
              <Route path="/analytics"  element={<AnalyticsPage />}      />
              <Route path="/settings"   element={<SettingsPage />}       />

              {/* Legacy redirects so old bookmarks keep working */}
              <Route path="/documents"                         element={<Navigate to="/knowledge"  replace />} />
              <Route path="/chatbots"                          element={<Navigate to="/assistants" replace />} />
              <Route path="/chatbots/:id"                      element={<Navigate to="/assistants" replace />} />
              <Route path="/chatbots/:id/settings"             element={<Navigate to="/assistants" replace />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
