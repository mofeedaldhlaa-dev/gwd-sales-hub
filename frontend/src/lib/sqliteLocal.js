import { Capacitor } from "@capacitor/core";
import { openDB } from "idb";
import { deviceId, genUUID } from "@/lib/utils";
import { getAppNow } from "@/lib/DateService";
import { ensureNativeDatabaseFile } from "@/lib/nativeLocalDatabase";

export const LOCAL_DB_NAME = "gawad_net_local.db";
const LEGACY_DB_NAME = "jawad_offline";
const LEGACY_DB_VERSION = 2;
const QUEUE_STORE = "queue";
const CACHE_STORE = "cache";
const META_STORE = "meta";

let connectionPromise = null;
let nativeDb = null;

export const isNativeSqlite = () => Capacitor.isNativePlatform();
const nowIso = () => getAppNow().toISOString();
const json = (value) => JSON.stringify(value === undefined ? null : value);
const parseJson = (value, fallback = null) => {
  try { return value === null || value === undefined ? fallback : JSON.parse(value); } catch { return fallback; }
};

const getNativeDb = async () => {
  if (!isNativeSqlite()) return null;
  if (nativeDb) return nativeDb;
  if (!connectionPromise) {
    connectionPromise = (async () => {
      // Explicitly materialize the file in the app-private Android database
      // directory before Capacitor's connection wrapper is opened. This makes
      // the storage contract observable and avoids a WebView-only fallback.
      await ensureNativeDatabaseFile();
      const { CapacitorSQLite, SQLiteConnection } = await import("@capacitor-community/sqlite");
      const sqlite = new SQLiteConnection(CapacitorSQLite);
      try { await sqlite.checkConnectionsConsistency(); } catch (_) { /* first connection */ }
      let db;
      try {
        const existing = await sqlite.isConnection(LOCAL_DB_NAME, false);
        db = existing?.result ? await sqlite.retrieveConnection(LOCAL_DB_NAME, false) : await sqlite.createConnection(LOCAL_DB_NAME, false, "no-encryption", 1, false);
      } catch {
        db = await sqlite.createConnection(LOCAL_DB_NAME, false, "no-encryption", 1, false);
      }
      await db.open();
      nativeDb = db;
      return db;
    })();
  }
  return connectionPromise;
};

const schema = `
CREATE TABLE IF NOT EXISTS local_meta (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_queue (
  local_id TEXT PRIMARY KEY NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  device_id TEXT NOT NULL,
  method TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  payload TEXT NOT NULL,
  sync_status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_attempt_at TEXT,
  last_error TEXT,
  failed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_local_queue_status ON local_queue(sync_status);
CREATE INDEX IF NOT EXISTS idx_local_queue_created ON local_queue(created_at);
CREATE TABLE IF NOT EXISTS local_cache (
  key TEXT PRIMARY KEY NOT NULL,
  url TEXT NOT NULL,
  data TEXT,
  cached_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_data (
  store_key TEXT PRIMARY KEY NOT NULL,
  entity TEXT NOT NULL,
  row_id TEXT,
  data TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_device (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  device_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_sync_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  state TEXT NOT NULL,
  pending_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);`;

export const initNativeSqlite = async (onProgress = () => {}) => {
  if (!isNativeSqlite()) return { mode: "web", migrated: false };
  onProgress({ percent: 10, label: "تهيئة قاعدة البيانات" });
  const db = await getNativeDb();
  await db.execute(schema, true, true);
  await setNativeMeta("schema_version", 1);
  onProgress({ percent: 15, label: "إنشاء الجداول" });
  await db.run("INSERT OR IGNORE INTO local_device(singleton, device_id, created_at) VALUES (1, ?, ?)", [deviceId(), nowIso()]);
  await db.run("INSERT OR IGNORE INTO local_sync_state(singleton, state, pending_count, updated_at) VALUES (1, 'ready', 0, ?)", [nowIso()]);
  return { mode: "native", migrated: false };
};

export const nativeMetaGet = async (key) => {
  const db = await getNativeDb();
  if (!db) return null;
  const result = await db.query("SELECT value, updated_at FROM local_meta WHERE key = ?", [key]);
  const row = result?.values?.[0];
  return row ? { key, value: parseJson(row.value, row.value), updated_at: row.updated_at } : undefined;
};

export const setNativeMeta = async (key, value) => {
  const db = await getNativeDb();
  if (!db) return value;
  await db.run("INSERT OR REPLACE INTO local_meta(key, value, updated_at) VALUES (?, ?, ?)", [key, json(value), nowIso()]);
  return value;
};

export const nativeQueueGetAll = async () => {
  const db = await getNativeDb();
  if (!db) return [];
  const result = await db.query("SELECT * FROM local_queue ORDER BY created_at ASC");
  return (result?.values || []).map((row) => ({ ...row, payload: parseJson(row.payload, {}) }));
};

export const nativeQueuePut = async (operation) => {
  const db = await getNativeDb();
  if (!db) return;
  await db.run(`INSERT OR REPLACE INTO local_queue
    (local_id, idempotency_key, device_id, method, endpoint, payload, sync_status, attempt_count, created_at, last_attempt_at, last_error, failed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, [
    operation.local_id, operation.idempotency_key, operation.device_id, operation.method, operation.endpoint,
    json(operation.payload || {}), operation.sync_status, Number(operation.attempt_count || 0), operation.created_at,
    operation.last_attempt_at || null, operation.last_error || "", operation.failed_at || null,
  ]);
};

export const nativeQueueDelete = async (localId) => {
  const db = await getNativeDb();
  if (db) await db.run("DELETE FROM local_queue WHERE local_id = ?", [localId]);
};

export const nativeCachePut = async (row) => {
  const db = await getNativeDb();
  if (db) await db.run("INSERT OR REPLACE INTO local_cache(key, url, data, cached_at) VALUES (?, ?, ?, ?)", [row.key, row.url, json(row.data), row.cached_at || nowIso()]);
};

export const nativeCacheGet = async (key) => {
  const db = await getNativeDb();
  if (!db) return undefined;
  const result = await db.query("SELECT data FROM local_cache WHERE key = ?", [key]);
  return result?.values?.[0] ? parseJson(result.values[0].data, undefined) : undefined;
};

export const nativeCacheGetAll = async () => {
  const db = await getNativeDb();
  if (!db) return [];
  const result = await db.query("SELECT key, url, data, cached_at FROM local_cache");
  return (result?.values || []).map((row) => ({ ...row, data: parseJson(row.data, null) }));
};

export const nativeDataPut = async (entity, rowId, data) => {
  const db = await getNativeDb();
  if (db) await db.run("INSERT OR REPLACE INTO local_data(store_key, entity, row_id, data, updated_at) VALUES (?, ?, ?, ?, ?)", [`${entity}:${rowId || "singleton"}`, entity, rowId || null, json(data), nowIso()]);
};

export const nativeDataGet = async (entity, rowId = "singleton") => {
  const db = await getNativeDb();
  if (!db) return undefined;
  const result = await db.query("SELECT data, updated_at FROM local_data WHERE store_key = ?", [`${entity}:${rowId}`]);
  const row = result?.values?.[0];
  if (!row) return undefined;
  return { data: parseJson(row.data, undefined), updated_at: row.updated_at };
};

export const nativeStats = async () => {
  const db = await getNativeDb();
  if (!db) return { queue: 0, cache: 0, meta: 0, data: 0, device: 0 };
  const count = async (table) => (await db.query(`SELECT COUNT(*) AS count FROM ${table}`))?.values?.[0]?.count || 0;
  return { queue: await count("local_queue"), cache: await count("local_cache"), meta: await count("local_meta"), data: await count("local_data"), device: await count("local_device") };
};

const hasLegacyDatabase = async () => {
  if (!window.indexedDB || !indexedDB.databases) return false;
  const databases = await indexedDB.databases();
  return databases.some((item) => item.name === LEGACY_DB_NAME);
};

export const migrateLegacyIndexedDb = async (onProgress = () => {}) => {
  if (!isNativeSqlite() || !(await hasLegacyDatabase())) return { migrated: false, queue: 0, cache: 0, meta: 0 };
  const db = await openDB(LEGACY_DB_NAME, LEGACY_DB_VERSION);
  const [queue, cache, meta] = await Promise.all([
    db.getAll(QUEUE_STORE), db.getAll(CACHE_STORE), db.getAll(META_STORE),
  ]);
  for (const row of meta) await setNativeMeta(row.key, row.value);
  for (const row of cache) await nativeCachePut(row);
  for (const row of queue) await nativeQueuePut(row);
  await setNativeMeta("legacy_migration", { source: LEGACY_DB_NAME, queue: queue.length, cache: cache.length, meta: meta.length, completed_at: nowIso() });
  onProgress({ percent: 20, label: "ترحيل البيانات المحلية السابقة" });
  return { migrated: true, queue: queue.length, cache: cache.length, meta: meta.length };
};

export const verifyNativeDatabase = async (expected = {}) => {
  const stats = await nativeStats();
  const required = ["queue", "cache", "meta", "data", "device"];
  const healthy = isNativeSqlite() && required.every((key) => Number(stats[key]) >= 0) && stats.device >= 1;
  const expectedOk = Object.entries(expected).every(([key, value]) => Number(value) === Number(stats[key]));
  return { healthy: healthy && expectedOk, stats, expected };
};

export const deleteLegacyIndexedDbAfterVerifiedMigration = async () => {
  // Deliberately not called automatically. A later explicit maintenance action may remove it
  // only after an operator verifies the migration counts and a backup is available.
  return false;
};

export const getNativeDatabasePathNote = () => isNativeSqlite()
  ? "/data/data/com.gawadnet.app/databases/gawad_net_local.db"
  : "browser-private storage fallback (PWA)";
