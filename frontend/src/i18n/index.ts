// The locale registry: what the site speaks, and what each locale is called in
// its own language.
//
// Endonyms on purpose ("Español", not "Spanish"). Someone who cannot read the
// current language cannot read the name of theirs written in it either, which
// is precisely the person the picker exists for.
import { LandingCopy } from "./types";
import { en } from "./en";
import { es } from "./es";
import { hi } from "./hi";
import { pt } from "./pt";
import { fr } from "./fr";
import { de } from "./de";
import { ar } from "./ar";
import { ja } from "./ja";

export type LocaleCode = "en" | "es" | "hi" | "pt" | "fr" | "de" | "ar" | "ja";

export interface LocaleMeta {
  code: LocaleCode;
  /** The language's name in itself. */
  label: string;
  /** For `<html lang>` — screen readers pick pronunciation from it, and search
   * engines pick the hreflang alternate. */
  htmlLang: string;
  dir: "ltr" | "rtl";
}

export const LOCALES: LocaleMeta[] = [
  { code: "en", label: "English", htmlLang: "en", dir: "ltr" },
  { code: "es", label: "Español", htmlLang: "es", dir: "ltr" },
  { code: "hi", label: "हिन्दी", htmlLang: "hi", dir: "ltr" },
  { code: "pt", label: "Português", htmlLang: "pt-BR", dir: "ltr" },
  { code: "fr", label: "Français", htmlLang: "fr", dir: "ltr" },
  { code: "de", label: "Deutsch", htmlLang: "de", dir: "ltr" },
  { code: "ja", label: "日本語", htmlLang: "ja", dir: "ltr" },
  // The one right-to-left locale. `dir` is applied to <html> by the provider,
  // which is what makes every logical CSS property in the page mirror.
  { code: "ar", label: "العربية", htmlLang: "ar", dir: "rtl" },
];

const COPY: Record<LocaleCode, LandingCopy> = { en, es, hi, pt, fr, de, ar, ja };

export const DEFAULT_LOCALE: LocaleCode = "en";

export function copyFor(code: LocaleCode): LandingCopy {
  return COPY[code] ?? COPY[DEFAULT_LOCALE];
}

export function metaFor(code: LocaleCode): LocaleMeta {
  return LOCALES.find((l) => l.code === code) ?? LOCALES[0];
}

/**
 * The best locale for a visitor who has never chosen one.
 *
 * Matches on the base language only — a browser set to `es-419` or `pt-PT`
 * should still land on Spanish or Portuguese rather than falling back to
 * English over a region subtag we do not carry a separate translation for.
 */
export function detectLocale(preferred: readonly string[]): LocaleCode {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split("-")[0];
    const hit = LOCALES.find((l) => l.code === base);
    if (hit) return hit.code;
  }
  return DEFAULT_LOCALE;
}

export type { LandingCopy } from "./types";
