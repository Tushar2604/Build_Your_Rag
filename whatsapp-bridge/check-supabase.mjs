// Pre-flight for a Supabase DATABASE_URL, run before pointing anything at it.
//
// Checks the failure modes that actually bite, in the order they bite:
// the pooler vs direct host (direct is IPv6-only and unreachable from Render),
// TLS, whether node-postgres can connect at all, and how fast it answers when
// cold — the last one being what decides whether a QR renders inside its ~20s
// validity window.
//
// Reads SUPABASE_TEST_URL from .env. Never prints the password.
import fs from "node:fs";
import pg from "pg";

const env = Object.fromEntries(
  fs.readFileSync("C:/projects/Build_Your_Rag/.env", "utf8")
    .split(/\r?\n/)
    .filter((l) => /^[A-Z][A-Z0-9_]*=/.test(l))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
);

const raw = env.SUPABASE_TEST_URL;
if (!raw) {
  console.log("MISSING: add SUPABASE_TEST_URL to .env first");
  process.exit(1);
}

const redact = (u) => u.replace(/:\/\/([^:]+):([^@]+)@/, "://$1:***@");
console.log("url:", redact(raw));

let problems = 0;
const fail = (m) => { console.log("  FAIL " + m); problems++; };
const ok = (m) => console.log("  ok   " + m);

// --- static checks on the string itself ---
console.log("\n[1] connection string shape");
raw.startsWith("postgresql+asyncpg://")
  ? ok("has postgresql+asyncpg:// prefix (SQLAlchemy picks the right driver)")
  : fail("missing postgresql+asyncpg:// prefix");

// Placeholders left in the template are the single most common mistake, and
// they fail late with a confusing DNS error rather than an obvious one.
const placeholder = raw.match(/YOUR[_-]?(REGION|PASSWORD)|\[[A-Z-]+\]/i);
if (placeholder) fail(`unreplaced placeholder "${placeholder[0]}" — substitute the real value`);

// Everything between the last ':' of the userinfo and the final '@' is the
// password. A bare '@' or ':' in there splits the URL somewhere unintended:
// parsers disagree about whether the first or last '@' separates host from
// credentials, so it can work in one client and break in another.
const userinfo = raw.slice(raw.indexOf("://") + 3, raw.lastIndexOf("@"));
const password = userinfo.slice(userinfo.indexOf(":") + 1);
const unsafe = [...new Set((password.match(/[@:/#?[\]]/g) || []))];
unsafe.length
  ? fail(
      `password contains unencoded ${unsafe.map((c) => `"${c}"`).join(", ")} — ` +
      `percent-encode it (@ -> %40, : -> %3A, / -> %2F, # -> %23, ? -> %3F)`,
    )
  : ok("password has no characters needing percent-encoding");

const url = new URL(raw.replace("postgresql+asyncpg://", "postgresql://"));

url.hostname.includes("pooler.supabase.com")
  ? ok(`pooler host (${url.hostname})`)
  : fail(`host is ${url.hostname} — direct hosts are IPv6-only and Render cannot reach them; use the Session pooler`);

url.port === "5432"
  ? ok("port 5432 (session mode)")
  : fail(`port ${url.port} — 6543 is the transaction pooler, which breaks asyncpg prepared statements`);

url.username.includes(".")
  ? ok(`username ${url.username.split(".")[0]}.<project-ref>`)
  : fail(`username "${url.username}" is missing the .<project-ref> suffix the pooler needs to route`);

/sslmode=require/.test(raw)
  ? ok("sslmode=require present (the bridge regex-matches this to enable TLS)")
  : fail("no sslmode=require — the bridge will connect without TLS and Supabase will refuse");

// --- live connection ---
console.log("\n[2] live connection");
// Import the bridge's own helpers so this tests the real code path, not an
// approximation of it — the sslmode-stripping is exactly what was broken.
const { normalizeDbUrl, wantsTls } = await import("./src/dbUrl.js");
const pool = new pg.Pool({
  connectionString: normalizeDbUrl(raw),
  ssl: wantsTls(raw) ? { rejectUnauthorized: false } : undefined,
  connectionTimeoutMillis: 30_000,
});

try {
  const t0 = Date.now();
  const { rows } = await pool.query("select version() v, current_database() db");
  const ms = Date.now() - t0;
  ok(`connected in ${ms}ms — ${rows[0].db}`);
  ok(rows[0].v.split(",")[0]);
  if (ms > 3000) {
    console.log(`  WARN cold start ${ms}ms — first pairing after idle may be slow`);
  }

  // Latency when warm is what the QR window actually depends on.
  const t1 = Date.now();
  await pool.query("select 1");
  ok(`warm query ${Date.now() - t1}ms`);

  const { rows: t } = await pool.query(
    "select count(*)::int n from information_schema.tables where table_schema='public'",
  );
  console.log(`\n[3] schema\n  ${t[0].n} tables in public`);
  if (t[0].n === 0) {
    console.log("  (empty — alembic upgrade head will build it on first boot)");
  }
} catch (e) {
  fail(`could not connect: ${e.message}`);
}
await pool.end().catch(() => {});

console.log(problems === 0 ? "\nRESULT: ready to use" : `\nRESULT: ${problems} problem(s) above`);
process.exit(problems === 0 ? 0 : 1);
