import { useState, useEffect, useRef, FormEvent, KeyboardEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { getChatbot, Chatbot } from "../api/chatbots";
import { createSession, askStream, greetStream } from "../api/chat";
import { CitationPayload } from "../api/client";
import { useVoice } from "../hooks/useVoice";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: CitationPayload[];
  tokensUsed?: number;
  streaming?: boolean;
}

function CitationsPanel({ citations }: { citations: CitationPayload[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-3 space-y-2" aria-label="Source citations">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">Sources</p>
      {citations.map((c) => (
        <div key={c.ordinal} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-brand-100 text-brand-700 text-[10px] font-bold">
              {c.ordinal}
            </span>
            <span className="text-xs text-gray-400 tabular-nums">
              score {c.score.toFixed(3)}
            </span>
          </div>
          <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{c.snippet}</p>
        </div>
      ))}
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold ${
          isUser ? "bg-brand-600 text-white" : "bg-gray-200 text-gray-600"
        }`}
        aria-hidden="true"
      >
        {isUser ? "U" : "AI"}
      </div>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            isUser
              ? "bg-brand-600 text-white rounded-tr-sm"
              : "bg-white border border-gray-200 text-gray-800 rounded-tl-sm shadow-sm"
          }`}
        >
          {msg.content || (msg.streaming && (
            <span className="inline-flex gap-1 items-center" aria-label="Generating response">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.3s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.15s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" />
            </span>
          ))}
        </div>
        {!isUser && msg.citations && msg.citations.length > 0 && (
          <CitationsPanel citations={msg.citations} />
        )}
        {!isUser && msg.tokensUsed !== undefined && !msg.streaming && (
          <p className="text-[10px] text-gray-300 mt-1 tabular-nums">
            {msg.tokensUsed.toLocaleString()} tokens
          </p>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { chatbotId } = useParams<{ chatbotId: string }>();
  const [chatbot, setChatbot] = useState<Chatbot | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const {
    sttSupported,
    ttsSupported,
    listening,
    startListening,
    stopListening,
    voiceMode,
    setVoiceMode,
    speak,
  } = useVoice((transcript) => sendMessage(transcript));

  useEffect(() => {
    if (!chatbotId) return;
    Promise.all([getChatbot(chatbotId), createSession(chatbotId)])
      .then(([bot, session]) => {
        setChatbot(bot);
        setSessionId(session.session_id);

        // AI-generated opening turn — the model greets first instead of the
        // page sitting empty. Silently falls back to the empty state on error.
        const greetingMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "",
          streaming: true,
        };
        let greetingText = "";
        setMessages([greetingMsg]);
        greetStream(session.session_id, {
          onToken: (token) => {
            greetingText += token;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === greetingMsg.id ? { ...m, content: m.content + token } : m,
              ),
            );
          },
          onDone: () => {
            setMessages((prev) =>
              prev.map((m) => (m.id === greetingMsg.id ? { ...m, streaming: false } : m)),
            );
            if (voiceMode) speak(greetingText);
          },
          onError: () => {
            setMessages((prev) => prev.filter((m) => m.id !== greetingMsg.id));
          },
        });
      })
      .catch((err) => setError(err.message ?? "Failed to initialize chat."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatbotId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || !sessionId || isStreaming) return;

    setInput("");
    setError(null);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    let fullAnswer = "";
    abortRef.current = askStream(sessionId, text, {
      onCitations: (citations) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id ? { ...m, citations } : m,
          ),
        );
      },
      onToken: (token) => {
        fullAnswer += token;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: m.content + token }
              : m,
          ),
        );
      },
      onDone: (tokensUsed) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, streaming: false, tokensUsed }
              : m,
          ),
        );
        setIsStreaming(false);
        inputRef.current?.focus();
        if (voiceMode) speak(fullAnswer);
      },
      onError: (err) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: "Sorry, something went wrong.", streaming: false }
              : m,
          ),
        );
        setError(err);
        setIsStreaming(false);
      },
    });
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    sendMessage();
  }

  function stopStreaming() {
    abortRef.current?.();
    abortRef.current = null;
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }

  if (error && !chatbot) {
    return (
      <div className="flex items-center justify-center h-full">
        <div role="alert" className="card p-8 max-w-sm text-center">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 flex items-center gap-3 flex-shrink-0">
        <div className="w-9 h-9 rounded-full bg-brand-600 flex items-center justify-center flex-shrink-0">
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </div>
        <div>
          <h1 className="text-sm font-semibold text-gray-900">
            {chatbot ? chatbot.name : "Loading…"}
          </h1>
          {sessionId && (
            <p className="text-xs text-gray-400 truncate max-w-xs">
              Session active
            </p>
          )}
        </div>
        {ttsSupported && (
          <button
            type="button"
            onClick={() => setVoiceMode(!voiceMode)}
            aria-pressed={voiceMode}
            aria-label={voiceMode ? "Turn off voice replies" : "Turn on voice replies"}
            title={voiceMode ? "Voice replies on" : "Voice replies off"}
            className={`ml-auto h-9 w-9 flex-shrink-0 rounded-lg flex items-center justify-center border ${
              voiceMode
                ? "bg-brand-50 border-brand-200 text-brand-600"
                : "bg-white border-gray-200 text-gray-400"
            }`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5L6 9H2v6h4l5 4V5z" />
              {voiceMode && (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13" />
              )}
            </svg>
          </button>
        )}
        {chatbotId && (
          <Link
            to={`/chatbots/${chatbotId}/settings`}
            className={`btn-secondary h-9 px-3 text-xs ${ttsSupported ? "" : "ml-auto"}`}
          >
            Embed &amp; Share
          </Link>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 space-y-6" aria-live="polite" aria-label="Chat messages">
        {messages.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center py-16">
            <div className="w-14 h-14 rounded-full bg-brand-50 flex items-center justify-center">
              <svg className="w-7 h-7 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <p className="text-sm text-gray-500 max-w-xs">
              {chatbot ? `Ask ${chatbot.name} anything about your documents.` : "Initializing…"}
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {error && messages.length > 0 && (
          <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 bg-white px-4 sm:px-6 py-4 flex-shrink-0">
        <form onSubmit={handleSubmit} className="flex gap-3 items-end">
          <div className="flex-1">
            <label htmlFor="chat-input" className="sr-only">Message</label>
            <textarea
              ref={inputRef}
              id="chat-input"
              name="message"
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question… (Enter to send, Shift+Enter for new line)"
              disabled={!sessionId || isStreaming}
              className="input resize-none min-h-[40px] max-h-40 py-2.5 overflow-y-auto leading-relaxed"
              maxLength={8000}
            />
          </div>

          {sttSupported && (
            <button
              type="button"
              onClick={() => (listening ? stopListening() : startListening())}
              disabled={!sessionId || isStreaming}
              aria-pressed={listening}
              aria-label={listening ? "Stop dictating" : "Ask by voice"}
              title={listening ? "Listening… tap to stop" : "Ask by voice"}
              className={`flex-shrink-0 h-10 w-10 rounded-xl flex items-center justify-center border ${
                listening
                  ? "bg-red-50 border-red-200 text-red-600 animate-pulse"
                  : "btn-secondary"
              }`}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15a3 3 0 003-3V6a3 3 0 10-6 0v6a3 3 0 003 3z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-14 0M12 18v3" />
              </svg>
            </button>
          )}

          {isStreaming ? (
            <button
              type="button"
              onClick={stopStreaming}
              aria-label="Stop generating"
              className="btn-secondary flex-shrink-0 h-10 px-3"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="6" y="6" width="12" height="12" rx="1" />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() || !sessionId}
              aria-label="Send message"
              className="btn-primary flex-shrink-0 h-10 px-3"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          )}
        </form>
        <p className="text-[11px] text-gray-300 mt-1.5 text-right tabular-nums">
          {input.length.toLocaleString()}/8,000
        </p>
      </div>
    </div>
  );
}
