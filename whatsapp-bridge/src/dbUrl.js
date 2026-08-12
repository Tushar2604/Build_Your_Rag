// Turning one DATABASE_URL into something node-postgres reads the same way
// SQLAlchemy does.
//
// The two clients disagree about the URL in ways that only show up against
// specific providers, so this lives in its own module: it is the piece most
// worth testing, and the verifier script imports it to check a real DSN before
// anyone points the app at it.

// Query params libpq understands but node-postgres does not handle the same
// way. `sslmode` is the dangerous one: newer pg-connection-string reads it from
// the URL and treats `require` as `verify-full`, which *overrides* the `ssl`
// option passed alongside it. Against a provider whose chain Node does not
// trust by default (Supabase's pooler), that fails with "self-signed
// certificate in certificate chain" no matter what `ssl` says.
const LIBPQ_ONLY_PARAMS = [
  "sslmode",
  "channel_binding",
  "target_session_attrs",
  "gssencmode",
  "options",
];

/** True when the DSN asks for TLS at all. Read the ORIGINAL url, before
 * normalizeDbUrl strips the param this looks for. */
export function wantsTls(url) {
  return /sslmode=(require|verify-ca|verify-full|prefer)/i.test(url || "");
}

/** Convert a Postgres URL that may carry SQLAlchemy's driver suffix, and drop
 * the libpq-only params node-postgres would misread. */
export function normalizeDbUrl(url) {
  const plain = (url || "").replace("postgresql+asyncpg://", "postgresql://");
  if (!plain.includes("?")) return plain;
  const [base, query] = plain.split("?");
  const kept = query
    .split("&")
    .filter((pair) => !LIBPQ_ONLY_PARAMS.includes(pair.split("=")[0].toLowerCase()));
  return kept.length ? `${base}?${kept.join("&")}` : base;
}
