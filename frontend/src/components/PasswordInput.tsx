// A password field you can unmask.
//
// Typing a password blind is the main reason people fail a sign-in they were
// going to pass — especially on a phone keyboard, and especially when the rule
// is "at least N characters" and you cannot see how many you have. The reveal
// defaults to off and never persists across a page load.
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export default function PasswordInput({
  id,
  value,
  onChange,
  autoComplete = "current-password",
  placeholder = "••••••••",
  required = true,
  minLength,
  className = "input",
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
  minLength?: number;
  className?: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <input
        id={id}
        name={autoComplete === "new-password" ? "new-password" : "password"}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        required={required}
        minLength={minLength}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        // Room for the toggle, so a long password does not run underneath it.
        className={`${className} pr-11`}
        placeholder={placeholder}
      />
      <button
        type="button"
        // Not in the tab order: reaching it between the password field and the
        // submit button interrupts the one flow everybody uses.
        tabIndex={-1}
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-gray-400 hover:text-gray-600 rounded"
      >
        {visible ? (
          <EyeOff className="w-4 h-4" strokeWidth={1.75} />
        ) : (
          <Eye className="w-4 h-4" strokeWidth={1.75} />
        )}
      </button>
    </div>
  );
}
