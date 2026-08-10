import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./store/auth";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";

import LoginPage          from "./pages/LoginPage";
import RegisterPage       from "./pages/RegisterPage";
import WidgetChatPage     from "./pages/WidgetChatPage";
import EmbedChatPage      from "./pages/EmbedChatPage";
import InterviewCallPage  from "./pages/InterviewCallPage";
import HomePage           from "./pages/HomePage";
import AssistantsPage     from "./pages/AssistantsPage";
import AssistantDetailPage from "./pages/AssistantDetailPage";
import KnowledgePage      from "./pages/KnowledgePage";
import InterviewsPage     from "./pages/InterviewsPage";
import BulkInterviewPage  from "./pages/BulkInterviewPage";
import InterviewDetailPage from "./pages/InterviewDetailPage";
import ChannelsPage       from "./pages/ChannelsPage";
import BroadcastsPage     from "./pages/BroadcastsPage";
import BroadcastCreatePage from "./pages/BroadcastCreatePage";
import BroadcastDetailPage from "./pages/BroadcastDetailPage";
import IntegrationsPage   from "./pages/IntegrationsPage";
import CloneVoicePage     from "./pages/CloneVoicePage";
import ReportIssuePage    from "./pages/ReportIssuePage";
import AnalyticsPage      from "./pages/AnalyticsPage";
import SettingsPage       from "./pages/SettingsPage";
import HiringAgentPage    from "./pages/HiringAgentPage";
import TeamPage           from "./pages/TeamPage";
import AcceptInvitePage   from "./pages/AcceptInvitePage";

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
          {/* Candidate-facing virtual interview — token-scoped, no account needed */}
          <Route path="/interview/:token" element={<InterviewCallPage />} />
          {/* Accept a team invite — token-scoped, no account needed yet */}
          <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />

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
              <Route path="/clone-voice" element={<CloneVoicePage />}   />
              <Route path="/report-issue" element={<ReportIssuePage />} />

              {/* Admin panel: Owner/Admin roles only */}
              <Route element={<ProtectedRoute requireAdmin />}>
                <Route path="/interviews" element={<InterviewsPage />}     />
                <Route path="/interviews/bulk" element={<BulkInterviewPage />} />
                <Route path="/interviews/:id" element={<InterviewDetailPage />} />
                <Route path="/channels"  element={<ChannelsPage />}      />
                <Route path="/integrations"   element={<IntegrationsPage />}    />
                <Route path="/broadcasts"     element={<BroadcastsPage />}      />
                {/* Registered before /:id so "new" is a page, not an id. */}
                <Route path="/broadcasts/new" element={<BroadcastCreatePage />} />
                <Route path="/broadcasts/:id" element={<BroadcastDetailPage />} />
                <Route path="/hiring-agent" element={<HiringAgentPage />}  />
                <Route path="/team"       element={<TeamPage />}           />
                <Route path="/settings"   element={<SettingsPage />}       />
              </Route>

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
