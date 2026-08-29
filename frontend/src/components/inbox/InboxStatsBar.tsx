// The counter strip across the top of the inbox.
//
// Workspace-wide rather than per-number, and served pre-computed: the rules
// behind a rate ("of threads we wrote to, how many replied") belong in one
// place, and re-deriving them in the browser is how two surfaces end up
// disagreeing about the same figure.
import {
  BarChart3, CheckCheck, Eye, Hash, MessageSquare, Megaphone, Phone, Reply,
} from "lucide-react";

import { InboxStats } from "../../api/whatsappInbox";

/** 1,842 rather than 1842 — a four-digit count is read, not counted. */
function compact(n: number): string {
  return n.toLocaleString();
}

function Stat({
  icon: Icon,
  value,
  label,
  tint,
}: {
  icon: typeof Phone;
  value: string;
  label: string;
  tint: string;
}) {
  return (
    <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap">
      <Icon className={`h-[15px] w-[15px] ${tint}`} strokeWidth={2} />
      <span className="text-[13px] font-bold tabular-nums text-gray-900">{value}</span>
      <span className="text-[12.5px] text-gray-500">{label}</span>
    </span>
  );
}

export default function InboxStatsBar({ stats }: { stats: InboxStats | null }) {
  if (!stats) {
    // A fixed-height placeholder, so the panes below don't jump down the
    // moment the numbers land.
    return <div className="h-[46px] flex-shrink-0 border-b border-gray-200 bg-surface" />;
  }

  const pct = (n: number) => `${n.toFixed(1)}%`;

  return (
    <div
      className="flex h-[46px] flex-shrink-0 items-center gap-6 overflow-x-auto border-b
                 border-gray-200 bg-surface px-5"
      aria-label="WhatsApp activity summary"
    >
      <Stat
        icon={Phone}
        tint="text-brand-500"
        value={compact(stats.connected_numbers)}
        label={`Connected Number${stats.connected_numbers === 1 ? "" : "s"}`}
      />
      <Stat
        icon={MessageSquare}
        tint="text-indigo-500"
        value={compact(stats.active_conversations)}
        label="Active Conversations"
      />
      <Stat
        icon={Hash}
        tint="text-sky-500"
        value={compact(stats.messages_sent)}
        // The window is the server's to name — it is a rolling one, not the
        // calendar month, so that a campaign sent on the 31st has not vanished
        // by breakfast on the 1st.
        label={`Messages Sent · ${stats.period_label}`}
      />
      <Stat
        icon={CheckCheck}
        tint="text-emerald-500"
        value={pct(stats.delivery_rate)}
        label="Delivery Rate"
      />
      <Stat icon={Eye} tint="text-violet-500" value={pct(stats.read_rate)} label="Read Rate" />
      <Stat icon={Reply} tint="text-amber-500" value={pct(stats.reply_rate)} label="Reply Rate" />
      <Stat
        icon={Megaphone}
        tint="text-rose-500"
        value={compact(stats.active_campaigns)}
        label={`Active Campaign${stats.active_campaigns === 1 ? "" : "s"}`}
      />
      {stats.unread > 0 && (
        <Stat
          icon={BarChart3}
          tint="text-red-500"
          value={compact(stats.unread)}
          label="Unread"
        />
      )}
    </div>
  );
}
