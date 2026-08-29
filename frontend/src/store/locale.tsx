// Which language the marketing site is being read in.
//
// Deliberately separate from the console's own state. The site is a public
// page a stranger lands on; the console is a workspace someone signs into.
// They have different audiences, and tying the two together would mean a
// Spanish-speaking visitor who signs up gets a half-translated dashboard.
//
// The choice is stored per browser rather than per account for the same
// reason: at the moment it matters, there is no account.
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";

import {
  DEFAULT_LOCALE, LandingCopy, LocaleCode, LOCALES, copyFor, detectLocale, metaFor,
} from "../i18n";

const STORAGE_KEY = "evara:locale";

interface LocaleValue {
  locale: LocaleCode;
  setLocale: (code: LocaleCode) => void;
  /** Every string on the page, already in the current language. */
  t: LandingCopy;
  dir: "ltr" | "rtl";
}

const Ctx = createContext<LocaleValue | null>(null);

function initialLocale(): LocaleCode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) as LocaleCode | null;
    if (stored && LOCALES.some((l) => l.code === stored)) return stored;
  } catch {
    // Private mode or blocked storage. Falling through to the browser's own
    // language is a better guess than English-by-default anyway.
  }
  return detectLocale(navigator.languages ?? [navigator.language ?? ""]);
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleCode>(initialLocale);
  const meta = metaFor(locale);

  // `lang` and `dir` on <html> are not cosmetic: screen readers choose a
  // pronunciation from `lang`, search engines read it, and `dir` is what makes
  // every logical CSS property in the page mirror for a right-to-left script.
  useEffect(() => {
    const root = document.documentElement;
    const prevLang = root.lang;
    const prevDir = root.dir;
    root.lang = meta.htmlLang;
    root.dir = meta.dir;
    return () => {
      // Restored on unmount so navigating from the landing page into the
      // console does not leave the app claiming to be in Hindi.
      root.lang = prevLang;
      root.dir = prevDir;
    };
  }, [meta.htmlLang, meta.dir]);

  const setLocale = useCallback((code: LocaleCode) => {
    setLocaleState(code);
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch {
      // The choice still applies to this visit; it just will not be remembered.
    }
  }, []);

  const value = useMemo<LocaleValue>(
    () => ({ locale, setLocale, t: copyFor(locale), dir: meta.dir }),
    [locale, setLocale, meta.dir],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLocale(): LocaleValue {
  const ctx = useContext(Ctx);
  // A sensible default rather than a throw: a component rendered outside the
  // provider should show English, not blow up the page.
  return (
    ctx ?? {
      locale: DEFAULT_LOCALE,
      setLocale: () => undefined,
      t: copyFor(DEFAULT_LOCALE),
      dir: "ltr",
    }
  );
}
