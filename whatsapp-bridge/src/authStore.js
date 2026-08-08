// Baileys auth state persisted to Postgres.
//
// Baileys ships `useMultiFileAuthState`, which writes to disk. That is wrong for
// this deployment: the container filesystem is ephemeral on free hosts, so a
// sleep or a redeploy would wipe the keys and force the user to scan a new QR
// every time. Keeping them in Postgres is what makes a link survive a restart.
//
// The shape Baileys expects is `{ creds, keys: { get, set } }`, where `keys`
// addresses many small records by (type, id) — hence a key-value table rather
// than a single JSON blob.

import { initAuthCreds, BufferJSON, proto } from "@whiskeysockets/baileys";

/** Baileys stores Buffers and protobufs; BufferJSON is its round-trip codec. */
const serialize = (value) => JSON.stringify(value, BufferJSON.replacer);
const deserialize = (text) => JSON.parse(text, BufferJSON.reviver);

const CREDS_KEY = "creds";

export async function useDbAuthState(pool, sessionId) {
  async function readKey(key) {
    const { rows } = await pool.query(
      "SELECT value FROM whatsapp_web_auth WHERE session_id = $1 AND key = $2",
      [sessionId, key],
    );
    return rows.length ? deserialize(rows[0].value) : null;
  }

  async function writeKey(key, value) {
    await pool.query(
      `INSERT INTO whatsapp_web_auth (session_id, key, value, updated_at)
       VALUES ($1, $2, $3, now())
       ON CONFLICT (session_id, key) DO UPDATE
         SET value = EXCLUDED.value, updated_at = now()`,
      [sessionId, key, serialize(value)],
    );
  }

  async function removeKey(key) {
    await pool.query(
      "DELETE FROM whatsapp_web_auth WHERE session_id = $1 AND key = $2",
      [sessionId, key],
    );
  }

  const creds = (await readKey(CREDS_KEY)) || initAuthCreds();

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const result = {};
          await Promise.all(
            ids.map(async (id) => {
              let value = await readKey(`${type}-${id}`);
              // app-state-sync-keys come back out as protobufs, not plain JSON.
              if (type === "app-state-sync-key" && value) {
                value = proto.Message.AppStateSyncKeyData.fromObject(value);
              }
              if (value) result[id] = value;
            }),
          );
          return result;
        },
        set: async (data) => {
          const writes = [];
          for (const type of Object.keys(data)) {
            for (const id of Object.keys(data[type])) {
              const value = data[type][id];
              const key = `${type}-${id}`;
              // Baileys signals a delete by setting the value to null.
              writes.push(value ? writeKey(key, value) : removeKey(key));
            }
          }
          await Promise.all(writes);
        },
      },
    },
    saveCreds: () => writeKey(CREDS_KEY, creds),
    /** Called on logout — the keys are dead, and leaving them would make the
     * bridge retry a link WhatsApp has already revoked. */
    clear: async () => {
      await pool.query("DELETE FROM whatsapp_web_auth WHERE session_id = $1", [sessionId]);
    },
  };
}
