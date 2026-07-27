import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getInterviewByToken, greetInterview, respondInterview, InterviewBootstrap } from "../api/interviews";
import VoiceCallPanel, { VoiceCallHandlers } from "../components/VoiceCallPanel";

export default function InterviewCallPage() {
  const { token = "" } = useParams<{ token: string }>();
  const [bootstrap, setBootstrap] = useState<InterviewBootstrap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    getInterviewByToken(token)
      .then(setBootstrap)
      .catch((e) => setError(e.message || "Interview not found."));
  }, [token]);

  // Camera is presence-only: a local, muted preview so it feels like a real
  // interview. Never recorded, uploaded, or analyzed.
  useEffect(() => {
    if (!bootstrap?.can_join) return;
    let active = true;
    navigator.mediaDevices
      ?.getUserMedia({ video: true, audio: false })
      .then((stream) => {
        if (active) setCameraStream(stream);
        else stream.getTracks().forEach((t) => t.stop());
      })
      .catch(() => setCameraError("Camera access was denied or unavailable — continuing without video."));
    return () => {
      active = false;
    };
  }, [bootstrap?.can_join]);

  useEffect(() => {
    if (videoRef.current && cameraStream) videoRef.current.srcObject = cameraStream;
    return () => {
      cameraStream?.getTracks().forEach((t) => t.stop());
    };
  }, [cameraStream]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
        <div className="text-center">
          <p className="text-lg font-semibold text-gray-900">Interview unavailable</p>
          <p className="text-sm text-gray-500 mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!bootstrap) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100 text-sm text-gray-400">
        Loading…
      </div>
    );
  }

  if (bootstrap.status === "completed") {
    return (
      <StatusScreen
        title="This interview has already been completed."
        detail="Thank you for your time — the hiring team will be in touch."
      />
    );
  }

  if (bootstrap.status === "cancelled") {
    return <StatusScreen title="This interview has been cancelled." detail="" />;
  }

  if (!bootstrap.can_join) {
    return (
      <StatusScreen
        title={`Your interview with ${bootstrap.tenant_name || "the hiring team"} hasn't started yet.`}
        detail={`It's scheduled for ${new Date(bootstrap.scheduled_at).toLocaleString()}. Come back at that time and this link will let you join.`}
      />
    );
  }

  const adapter = {
    createSession: async () => token,
    greet: (_sid: string, h: VoiceCallHandlers) =>
      greetInterview(token, {
        onToken: h.onToken,
        onDone: () => h.onDone?.(),
        onError: h.onError,
      }),
    ask: (_sid: string, text: string, h: VoiceCallHandlers) =>
      respondInterview(token, text, {
        onToken: h.onToken,
        onDone: (completed) => {
          if (completed) h.onEnded?.();
          else h.onDone?.();
        },
        onError: h.onError,
      }),
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-gray-100">
      <div className="md:w-80 flex-shrink-0 bg-ink-950 flex flex-col">
        <div className="px-5 py-4 text-white">
          <p className="text-sm font-semibold">{bootstrap.role_title || "Interview"}</p>
          <p className="text-xs text-white/60 mt-0.5">{bootstrap.tenant_name}</p>
        </div>
        <div className="flex-1 relative flex items-center justify-center min-h-[240px]">
          {cameraStream ? (
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              className="w-full h-full object-cover"
              style={{ transform: "scaleX(-1)" }}
            />
          ) : (
            <p className="text-white/40 text-xs text-center px-8">
              {cameraError || "Requesting camera…"}
            </p>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        <header className="px-5 py-4 bg-white border-b border-gray-200">
          <h1 className="text-sm font-semibold text-gray-900">
            Hi{bootstrap.candidate_name ? `, ${bootstrap.candidate_name}` : ""} — let's get started
          </h1>
        </header>
        <div className="flex-1">
          <VoiceCallPanel botName={bootstrap.tenant_name || "the interviewer"} adapter={adapter} />
        </div>
      </div>
    </div>
  );
}

function StatusScreen({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div className="text-center max-w-sm">
        <p className="text-lg font-semibold text-gray-900">{title}</p>
        {detail && <p className="text-sm text-gray-500 mt-2">{detail}</p>}
      </div>
    </div>
  );
}
