import { openDB } from "idb";
import { genUUID, deviceId } from "./utils";
import { getAppNow } from "@/lib/DateService";
import {
  isNativeSqlite,
  initNativeSqlite,
  migrateLegacyIndexedDb,
  nativeMetaGet,
  setNativeMeta,
  nativeQueueGetAll,
  nativeQueuePut,
  nativeQueueDelete,
  nativeCachePut,
  nativeCacheGet,
  nativeCacheGetAll,
  nativeDataPut,
  nativeDataGet,
  nativeStats,
  verifyNativeDatabase,
  getNativeDatabasePathNote,
} from "./sqliteLocal";

const DB_NAME = "jawad_offline";
const DB_VERSION = 2;
const QUEUE_STORE = "queue";
const CACHE_STORE = "cache";
const META_STORE = "meta";
let dbp = null;
let syncPromise = null;
let cloudSyncPromise = null;
let retryTimer = null;

const nowIso = () => getAppNow().toISOString();
export const isNativeStorage = () => isNativeSqlite();

const getDB = () => {
  if (!dbp) {
    dbp = openDB(DB_NAME, DB_VERSION, {
      upgrade(db, _oldVersion, _newVersion, tx) {
        if (!db.objectStoreNames.contains(QUEUE_STORE)) {
          const store = db.createObjectStore(QUEUE_STORE, { keyPath: "local_id" });
          store.createIndex("sync_status", "sync_status");
          store.createIndex("created_at", "created_at");
        } else {
          const store = tx.objectStore(QUEUE_STORE);
          if (!store.indexNames.contains("sync_status")) store.createIndex("sync_status", "sync_status");
          if (!store.indexNames.contains("created_at")) store.createIndex("created_at", "created_at");
        }
        if (!db.objectStoreNames.contains(CACHE_STORE)) db.createObjectStore(CACHE_STORE, { keyPath: "key" });
        if (!db.objectStoreNames.contains(META_STORE)) db.createObjectStore(META_STORE, { keyPath: "key" });
      },
    });
  }
  return dbp;
};

export const initOfflineStorage = async (onProgress = () => {}) => {
  if (isNativeStorage()) {
    const native = await initNativeSqlite(onProgress);
    const migration = await migrateLegacyIndexedDb(onProgress);
    const verification = await verifyNativeDatabase();
    if (!verification.healthy) throw new Error("تعذر التحقق من قاعدة SQLite الداخلية.");
    await setNativeMeta("bootstrap_mode", "native-sqlite");
    await setNativeMeta("database_path", getNativeDatabasePathNote());
    return { ...native, migration, verification, database_path: getNativeDatabasePathNote() };
  }
  const db = await getDB();
  await db.put(META_STORE, { key: "schema_version", value: DB_VERSION, updated_at: nowIso() });
  return { mode: "web", database_path: getNativeDatabasePathNote() };
};

export const getOfflineMeta = async (key) => {
  if (isNativeStorage()) return nativeMetaGet(key);
  return (await getDB()).get(META_STORE, key);
};

export const setOfflineMeta = async (key, value) => {
  if (isNativeStorage()) return setNativeMeta(key, value);
  await (await getDB()).put(META_STORE, { key, value, updated_at: nowIso() });
  return value;
};

const normalizeUrl = (url = "") => {
  try {
    const parsed = new URL(url, window.location.origin);
    return `${parsed.pathname}${parsed.search}`;
  } catch { return String(url); }
};

const cacheKey = (config = {}) => {
  const url = normalizeUrl(config.url || "");
  const params = config.params || {};
  const query = Object.keys(params).sort().map((key) => `${key}=${params[key] ?? ""}`).join("&");
  return `${url}${query ? `?${query}` : ""}`;
};

export const cacheGetResponse = async (config, data) => {
  if ((config?.method || "get").toLowerCase() !== "get") return;
  const key = cacheKey(config);
  if (!key || key.includes("/auth/login")) return;
  const row = { key, url: normalizeUrl(config.url), data, cached_at: nowIso() };
  if (isNativeStorage()) return nativeCachePut(row);
  await (await getDB()).put(CACHE_STORE, row);
};

const asListPayload = (value, path) =>
  (path === "/notifications" && value && !Array.isArray(value) && Array.isArray(value.items) ? value.items : value);

export const getCachedResponse = async (config) => {
  const exactKey = cacheKey(config);
  const statementPath = normalizeUrl(config.url || "").split("?")[0];
  const statementMatch = statementPath.match(/^\/accounts\/([^/]+)\/([^/]+)\/statement$/);

  // Account statements are also stored as complete snapshots in SQLite during
  // cloud bootstrap. Prefer that snapshot over an older filtered cache row so
  // the offline statement and its PDF contain the latest synced operations.
  if (isNativeStorage() && statementMatch) {
    const snapshot = await nativeDataGet(`accounts/${statementMatch[1]}/${statementMatch[2]}/statement`, "snapshot");
    if (snapshot?.data !== undefined) {
      const ranged = applyStatementRange(snapshot.data, config.params || {});
      return applyPendingStatementOverlay(ranged, statementPath, config.params || {});
    }
  }

  const exact = isNativeStorage()
    ? await nativeCacheGet(exactKey)
    : (await (await getDB()).get(CACHE_STORE, exactKey))?.data;
  const exactPath = normalizeUrl(config.url || "").split("?")[0];
  if (exact !== undefined) {
    return applyPendingStatementOverlay(asListPayload(exact, exactPath), exactPath, config.params || {});
  }

  // A filtered screen may request a query that was never cached offline.
  // Reuse the newest full-list snapshot for the same endpoint instead of
  // turning a usable local database into a connection error.
  const basePath = normalizeUrl(config.url || "").split("?")[0];
  if (!basePath) return undefined;
  const rows = await readCacheRows();
  const fallback = rows
    .filter((row) => row?.url === basePath && row.data !== undefined)
    .sort((a, b) => String(b.cached_at || "").localeCompare(String(a.cached_at || "")))[0];
  if (!fallback) return undefined;
  const fallbackData = asListPayload(fallback.data, basePath);
  return applyPendingStatementOverlay(applyStatementRange(fallbackData, config.params || {}), basePath, config.params || {});
};

const listPathFor = (endpoint) => {
  const path = normalizeUrl(endpoint).split("?")[0];
  const match = path.match(/^\/(sales|purchases|receipts|expenses|transfers|customers|suppliers|categories|cards|bank-accounts|account-types|account-lists|notifications|orders)(?:\/|$)/);
  return match ? `/${match[1]}` : null;
};

const readCacheRows = async () => isNativeStorage() ? nativeCacheGetAll() : (await getDB()).getAll(CACHE_STORE);
const writeCacheRow = async (row) => isNativeStorage() ? nativeCachePut(row) : (await getDB()).put(CACHE_STORE, row);

const applyStatementRange = (data, params = {}) => {
  if (!data || !Array.isArray(data.entries) || (!params.start && !params.end)) return data;
  const start = params.start ? String(params.start) : "";
  const end = params.end ? String(params.end) : "";
  const entries = data.entries.filter((entry) => {
    const day = String(entry.created_at || "").slice(0, 10);
    return (!start || day >= start) && (!end || day <= end);
  });
  return {
    ...data,
    range: { ...(data.range || {}), start: params.start || null, end: params.end || null },
    entries,
    total_debit: entries.reduce((sum, entry) => sum + Number(entry.debit || 0), 0),
    total_credit: entries.reduce((sum, entry) => sum + Number(entry.credit || 0), 0),
  };
};

const pendingLedgerEffect = (operation, type, id) => {
  const p = operation?.payload || {};
  const endpoint = String(operation?.endpoint || "");
  let debit = 0;
  let credit = 0;
  let description = "عملية محفوظة محلياً";
  if (endpoint === "/sales" && type === "customer" && p.customer_id === id) {
    const total = Number(p.total || (p.items || []).reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0), 0));
    debit = Math.max(0, total - Number(p.paid || 0));
    description = `مبيعات محلية — ${p.number || operation.local_id}`;
  } else if (endpoint === "/purchases" && type === "supplier" && p.supplier_id === id) {
    const total = Number(p.total || (p.items || []).reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0), 0));
    credit = Math.max(0, total - Number(p.paid || 0));
    description = `مشتريات محلية — ${p.number || operation.local_id}`;
  } else if (endpoint === "/receipts" && ["customer", "supplier"].includes(type) && p.party_id === id) {
    if (p.kind === "receipt") credit = Number(p.amount || 0);
    else debit = Number(p.amount || 0);
    description = p.description || `سند محلي — ${p.number || operation.local_id}`;
  } else return null;
  if (!(debit || credit)) return null;
  return { debit, credit, description, created_at: operation.created_at, number: p.number || `G${String(operation.local_id).slice(0, 10)}`, id: `local-${operation.local_id}` };
};

const applyPendingStatementOverlay = async (data, url, params = {}) => {
  const match = String(url || "").match(/^\/accounts\/([^/]+)\/([^/]+)\/statement(?:\?|$)/);
  if (!match || !data || !Array.isArray(data.entries)) return data;
  const [type, id] = match.slice(1);
  const pending = (await allQueue()).filter((item) => ["pending", "syncing", "failed"].includes(item.sync_status));
  const overlays = pending.map((item) => pendingLedgerEffect(item, type, id)).filter(Boolean);
  if (!overlays.length) return data;
  const entries = [...data.entries, ...overlays].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  const ranged = applyStatementRange({ ...data, entries }, params);
  return {
    ...ranged,
    balance_after: Number(ranged.balance_before || 0) + Number(ranged.total_debit || 0) - Number(ranged.total_credit || 0),
    account: { ...(ranged.account || {}), balance: Number(ranged.account?.balance || 0) + overlays.reduce((sum, row) => sum + Number(row.debit || 0) - Number(row.credit || 0), 0) },
  };
};

const pendingPartyEffect = (op) => {
  const p = op?.payload || {};
  if (op.endpoint === "/sales" && p.customer_id) {
    const total = Number(p.total || (p.items || []).reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0), 0));
    return { id: p.customer_id, type: "customer", delta: Math.max(0, total - Number(p.paid || 0)) };
  }
  if (op.endpoint === "/purchases" && p.supplier_id) {
    const total = Number(p.total || (p.items || []).reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0), 0));
    return { id: p.supplier_id, type: "supplier", delta: -Math.max(0, total - Number(p.paid || 0)) };
  }
  if (op.endpoint === "/receipts" && p.party_id) {
    return { id: p.party_id, type: p.party_type || "customer", delta: p.kind === "receipt" ? -Number(p.amount || 0) : Number(p.amount || 0) };
  }
  return null;
};

const updateCachedLists = async (op, optimistic) => {
  const listPath = listPathFor(op.endpoint);
  const rows = await readCacheRows();
  if (listPath) {
    for (const row of rows) {
      if (row.url !== listPath && !row.url.startsWith(`${listPath}?`)) continue;
      const data = Array.isArray(row.data) ? [...row.data] : null;
      if (!data) continue;
      const method = (op.method || "post").toLowerCase();
      const id = optimistic.id || op.payload?.id;
      if (method === "post" && !data.some((item) => item?.id === id)) data.unshift(optimistic);
      if (["put", "patch"].includes(method)) {
        const index = data.findIndex((item) => item?.id === id);
        if (index >= 0) data[index] = { ...data[index], ...optimistic };
      }
      if (method === "delete") row.data = data.filter((item) => item?.id !== id);
      else row.data = data;
      row.cached_at = nowIso();
      await writeCacheRow(row);
    }
  }
  const effect = pendingPartyEffect(op);
  if (effect) {
    for (const row of rows) {
      const path = String(row.url || "").split("?")[0];
      if (!["/accounts", "/customers", "/suppliers"].includes(path) || !Array.isArray(row.data)) continue;
      row.data = row.data.map((item) => {
        const itemType = item.base_type || item.type || (path === "/customers" ? "customer" : path === "/suppliers" ? "supplier" : "");
        return item?.id === effect.id && (path !== "/accounts" || itemType === effect.type)
          ? { ...item, balance: Number(item.balance || 0) + effect.delta }
          : item;
      });
      row.cached_at = nowIso();
      await writeCacheRow(row);
    }
  }
};

const optimisticResponse = (op) => ({
  ...(op.payload || {}),
  id: op.payload?.id || op.local_id,
  local_id: op.local_id,
  idempotency_key: op.idempotency_key,
  device_id: op.device_id,
  sync_status: "pending",
  status: "pending_sync",
  created_at: op.payload?.created_at || op.created_at,
  number: op.payload?.number || `محلي-${op.local_id.slice(0, 8)}`,
});

export const queueOperation = async (input) => {
  const operation = {
    local_id: input.local_id || genUUID(),
    idempotency_key: input.idempotency_key || genUUID(),
    device_id: input.device_id || deviceId(),
    method: (input.method || "post").toLowerCase(),
    endpoint: input.endpoint,
    payload: input.payload || {},
    sync_status: "pending",
    attempt_count: 0,
    created_at: input.created_at || nowIso(),
    last_error: "",
  };
  if (isNativeStorage()) {
    await initNativeSqlite();
    await nativeQueuePut(operation);
  } else {
    await initOfflineStorage();
    await (await getDB()).put(QUEUE_STORE, operation);
  }
  const optimistic = optimisticResponse(operation);
  await updateCachedLists(operation, optimistic);
  window.dispatchEvent(new CustomEvent("offline-queue-changed", { detail: { operation, optimistic } }));
  return { operation, response: optimistic };
};

const allQueue = async () => isNativeStorage() ? nativeQueueGetAll() : (await getDB()).getAll(QUEUE_STORE);
const saveQueue = async (row) => isNativeStorage() ? nativeQueuePut(row) : (await getDB()).put(QUEUE_STORE, row);
const deleteQueue = async (id) => isNativeStorage() ? nativeQueueDelete(id) : (await getDB()).delete(QUEUE_STORE, id);

const recoverStaleSyncing = async () => {
  const rows = await allQueue();
  const threshold = Date.now() - 120_000;
  for (const row of rows) {
    if (row.sync_status === "failed" && /مسجلة|قيد التنفيذ|قيد المراجعة|duplicate|idempot/i.test(row.last_error || "")) {
      row.sync_status = "permanent_failed";
      row.failed_at = row.failed_at || nowIso();
      await saveQueue(row);
      continue;
    }
    if (row.sync_status !== "syncing") continue;
    const at = Date.parse(row.last_attempt_at || row.created_at || "");
    if (!Number.isFinite(at) || at < threshold) {
      row.sync_status = "pending";
      row.last_error = "تمت إعادة العملية إلى الانتظار بعد انقطاع مزامنة سابق.";
      await saveQueue(row);
    }
  }
};

export const getPending = async () => {
  await recoverStaleSyncing();
  return (await allQueue())
    .filter((item) => ["pending", "syncing", "failed"].includes(item.sync_status))
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
};

export const getQueueSummary = async () => {
  const all = await allQueue();
  return {
    pending: all.filter((x) => ["pending", "syncing", "failed"].includes(x.sync_status)).length,
    failed: all.filter((x) => x.sync_status === "failed").length,
    permanent: all.filter((x) => ["failed_permanent", "permanent_failed"].includes(x.sync_status)).length,
  };
};

const isPermanentFailure = (error) => {
  const status = error?.response?.status;
  // A 409 from the idempotency guard means the operation key is already
  // owned by a completed/in-review request. Retrying with the same queued
  // row forever only produces "already recorded/in progress"; keep it for
  // explicit review instead of replaying a financial mutation.
  return status >= 400 && status < 500 && ![408, 425, 429].includes(status);
};

const scheduleRetry = (delay = 15000) => {
  if (retryTimer || typeof window === "undefined") return;
  retryTimer = window.setTimeout(async () => {
    retryTimer = null;
    if (isOnline()) {
      try { await syncNow(); } catch (_) { scheduleRetry(Math.min(delay * 2, 120000)); }
    }
  }, delay);
};

const runSync = async () => {
  if (!navigator.onLine) return { ok: 0, failed: 0, permanent: 0, skipped: true };
  const { default: api, errText } = await import("./api");
  const pending = await getPending();
  let ok = 0; let failed = 0; let permanent = 0;
  window.dispatchEvent(new CustomEvent("offline-sync-state", { detail: { state: "syncing", pending: pending.length } }));
  for (const operation of pending) {
    const op = { ...operation, sync_status: "syncing", attempt_count: Number(operation.attempt_count || 0) + 1, last_attempt_at: nowIso() };
    await saveQueue(op);
    try {
      const payload = { ...(op.payload || {}) };
      if (["post", "put", "patch"].includes(op.method)) {
        payload.idempotency_key = op.idempotency_key;
        payload.local_id = op.local_id;
        payload.device_id = op.device_id;
      }
      await api.request({ url: op.endpoint, method: op.method, data: payload, __skipOfflineQueue: true, __idempotencyKey: op.idempotency_key, __localOperationId: op.local_id });
      await deleteQueue(op.local_id);
      ok += 1;
      window.dispatchEvent(new CustomEvent("offline-operation-synced", { detail: op }));
    } catch (error) {
      op.sync_status = isPermanentFailure(error) ? "permanent_failed" : "failed";
      op.last_error = errText(error);
      op.failed_at = nowIso();
      await saveQueue(op);
      if (op.sync_status === "permanent_failed") permanent += 1; else failed += 1;
      if (!error?.response) {
        scheduleRetry();
        break;
      }
    }
  }
  const refreshPaths = ["/auth/me", "/categories", "/customers", "/suppliers", "/cards", "/stock", "/stock/balance/operations", "/sales", "/purchases", "/receipts", "/expenses", "/transfers", "/accounts", "/cash/summary", "/cash/statement", "/reports/dashboard", "/reports/sales", "/reports/purchases", "/reports/customer-debts", "/reports/supplier-debts", "/reports/electronic-sales", "/reports/card-order-log", "/reports/opening-balances", "/reports/incentives", "/account-types", "/account-lists", "/bank-accounts", "/orders"];
  await Promise.allSettled(refreshPaths.map((url) => api.get(url, { __skipOfflineQueue: true })));
  const summary = await getQueueSummary();
  if (summary.pending && isOnline()) scheduleRetry();
  window.dispatchEvent(new CustomEvent("offline-sync-state", { detail: { state: summary.pending ? "pending" : "synced", ...summary } }));
  return { ok, failed, permanent };
};

export const syncNow = async () => {
  if (syncPromise) return syncPromise;
  syncPromise = runSync().finally(() => { syncPromise = null; });
  return syncPromise;
};

export const isOnline = () => typeof navigator === "undefined" || navigator.onLine;

export const shouldQueueAxiosRequest = (config = {}) => {
  const method = (config.method || "get").toLowerCase();
  const url = normalizeUrl(config.url || "");
  const token = typeof localStorage !== "undefined" && localStorage.getItem("jwd_token");
  if (!token || config.__skipOfflineQueue || !["post", "put", "patch", "delete"].includes(method)) return false;
  // The offline queue stores JSON only. A file request must fail visibly and be
  // retried by the user, never converted into a false local success.
  const isFormData = typeof FormData !== "undefined" && config.data instanceof FormData;
  if (isFormData) return false;
  if (/\/(auth|public|push)\//.test(`${url}/`) || url.includes("/notifications/") || url.includes("/lookup") || url.includes("/quick-recharge/list") || url.includes("/files/upload") || url.includes("/backup/") || url.includes("/settings/reset-data") || url.includes("/password")) return false;
  return true;
};

export const queueAxiosRequest = async (config) => {
  let payload = config.data;
  if (typeof payload === "string") { try { payload = JSON.parse(payload); } catch { payload = {}; } }
  const idempotencyKey = config.__idempotencyKey || payload?.idempotency_key || genUUID();
  const localId = config.__localOperationId || genUUID();
  const result = await queueOperation({ endpoint: normalizeUrl(config.url), method: config.method, payload: { ...(payload || {}), idempotency_key: idempotencyKey, local_operation_id: localId }, idempotency_key: idempotencyKey, local_id: localId, device_id: payload?.device_id });
  return result;
};

export const getLocalStorageHealth = async () => {
  if (isNativeStorage()) return { mode: "native-sqlite", path: getNativeDatabasePathNote(), ...(await nativeStats()) };
  return { mode: "web-indexeddb", path: getNativeDatabasePathNote(), queue: (await allQueue()).length, cache: (await (await getDB()).getAll(CACHE_STORE)).length };
};

const paginatedCloudEndpoints = new Set(["/sales", "/purchases", "/receipts", "/transfers", "/cards"]);

const fetchCloudSnapshot = async (api, endpoint) => {
  if (!paginatedCloudEndpoints.has(endpoint)) {
    const response = await api.get(endpoint, { __skipOfflineQueue: true });
    return response.data;
  }
  const pageSize = 5000;
  const rows = [];
  let offset = 0;
  while (true) {
    const response = await api.get(endpoint, { params: { limit: pageSize, offset }, __skipOfflineQueue: true });
    const page = Array.isArray(response.data) ? response.data : [];
    rows.push(...page);
    if (page.length < pageSize) break;
    offset += page.length;
  }
  return rows;
};

const bootstrapSteps = [
  ["/accounts", "الحسابات", "receipts"],
  ["/customers", "العملاء", "customers"],
  ["/suppliers", "الموردون", "suppliers"],
  ["/customers/blocked/list", "حظر العملاء", "customers"],
  ["/account-types", "أنواع الحسابات", "receipts"],
  ["/account-lists", "قوائم الحسابات", "receipts"],
  ["/expense-accounts", "حسابات المصروفات", "expenses"],
  ["/currencies", "العملات", null],
  ["/incentive-rules", "قواعد الحوافز", "settings"],
  ["/incentive-settings", "إعدادات الحوافز", "settings"],
  ["/categories", "الفئات", "categories"],
  ["/cards", "الكروت", "cards"],
  ["/stock", "المخزون", "stock"],
  ["/stock/balance/operations", "حركات مخزون الرصيد", "stock"],
  ["/stock/alerts", "تنبيهات المخزون", null],
  ["/sales", "المبيعات", "sales"],
  ["/purchases", "المشتريات", "purchases"],
  ["/receipts", "السندات", "receipts"],
  ["/expenses", "المصروفات", "expenses"],
  ["/transfers", "التحويلات", "receipts"],
  ["/cash/summary", "ملخص الصندوق", "receipts"],
  ["/cash/statement", "كشف حركة الصندوق", "receipts"],
  ["/reports/dashboard", "بيانات لوحة التحكم", "dashboard"],
  ["/reports/sales", "تقرير المبيعات", "reports"],
  ["/reports/purchases", "تقرير المشتريات", "reports"],
  ["/reports/customer-debts", "مديونية العملاء", "reports"],
  ["/reports/supplier-debts", "مديونية الموردين", "reports"],
  ["/reports/electronic-sales", "المبيعات الإلكترونية", "reports"],
  ["/reports/card-order-log", "سجل طلبات الكروت", "reports"],
  ["/reports/opening-balances", "الأرصدة الافتتاحية", "reports"],
  ["/reports/incentives", "تقرير الحوافز", "reports"],
  ["/orders", "الطلبات", "card_orders"],
  ["/payment-requests", "طلبات التسديد", null],
  ["/notifications", "الإشعارات", null],
  ["/notifications/summary", "ملخص الإشعارات", null],
  ["/notifications/broadcast-log", "سجل الإشعارات المرسلة", "settings"],
  ["/register-requests", "طلبات إنشاء الحساب", "customers"],
  ["/public-blocks", "قائمة الحظر", "customers"],
  ["/settings", "إعدادات التطبيق السحابية", null],
  ["/files", "ملفات التطبيق", null],
  ["/users", "المستخدمون", "users"],
  ["/users/permissions/list", "صلاحيات المستخدمين", null],
  ["/audit", "سجل العمليات", "users"],
];

export const bootstrapLocalData = async (user, onProgress = () => {}) => {
  const { default: api } = await import("./api");
  const allowed = (perm) => user?.role === "admin" || !perm || (user?.permissions || []).includes(perm);
  const steps = bootstrapSteps.filter(([, , perm]) => allowed(perm));
  const downloaded = {};
  let accountRows = [];
  let categoryRows = [];
  let completed = 0;
  onProgress({ percent: 20, label: "الاتصال بالخادم" });
  for (const [endpoint, label] of steps) {
    const raw = await fetchCloudSnapshot(api, endpoint);
    // The notifications feed is also exposed as {server_time, items} by the
    // watcher endpoint; screens expect a plain array, so store the array form.
    const data = asListPayload(raw, endpoint.split("?")[0]);
    if (endpoint === "/accounts" && Array.isArray(data)) accountRows = data;
    if (endpoint === "/categories" && Array.isArray(data)) categoryRows = data;
    const count = Array.isArray(data) ? data.length : (data && typeof data === "object" ? Object.keys(data).length : 0);
    if (isNativeStorage()) await nativeDataPut(endpoint.slice(1), "snapshot", data);
    downloaded[endpoint] = count;
    completed += 1;
    const percent = Math.min(90, 20 + Math.round((completed / Math.max(steps.length, 1)) * 70));
    onProgress({ percent, label: `تحميل ${label}`, endpoint, count });
  }
  if (allowed("receipts") && accountRows.length) {
    const statementAccounts = accountRows
      .filter((account) => account?.id && account.id !== "cash")
      .map((account) => ({
        type: account.base_type || account.type,
        id: account.id,
      }))
      .filter((account) => ["customer", "pos", "supplier", "expense"].includes(account.type));
    const targets = [{ type: "cash", id: "cash" }, ...statementAccounts];
    let completedStatements = 0;
    for (let offset = 0; offset < targets.length; offset += 8) {
      const batch = targets.slice(offset, offset + 8);
      const statementResults = await Promise.allSettled(batch.map(async ({ type, id }) => {
        const endpoint = `/accounts/${type}/${id}/statement`;
        const response = await api.get(endpoint, { __skipOfflineQueue: true });
        if (isNativeStorage()) await nativeDataPut(endpoint.slice(1), "snapshot", response.data);
        downloaded[endpoint] = Array.isArray(response.data?.entries) ? response.data.entries.length : 0;
        completedStatements += 1;
        onProgress({ percent: Math.min(92, 75 + Math.round((completedStatements / Math.max(targets.length, 1)) * 17)), label: "تحميل كشوف الحسابات والصندوق", endpoint, count: downloaded[endpoint] });
      }));
      const failedStatement = statementResults.find((result) => result.status === "rejected");
      if (failedStatement) throw failedStatement.reason || new Error("تعذر تنزيل أحد كشوف الحسابات");
    }
  }
  if (allowed("reports") && categoryRows.length) {
    let completedMovements = 0;
    for (let offset = 0; offset < categoryRows.length; offset += 8) {
      const batch = categoryRows.slice(offset, offset + 8).filter((category) => category?.id);
      const results = await Promise.allSettled(batch.map(async (category) => {
        const endpoint = `/reports/item-movement?category_id=${encodeURIComponent(category.id)}`;
        const response = await api.get(endpoint, { __skipOfflineQueue: true });
        if (isNativeStorage()) await nativeDataPut(endpoint.split("?")[0].slice(1), category.id, response.data);
        downloaded[endpoint] = Array.isArray(response.data?.entries) ? response.data.entries.length : 0;
        completedMovements += 1;
        onProgress({ percent: Math.min(96, 92 + Math.round((completedMovements / Math.max(categoryRows.length, 1)) * 4)), label: "تحميل حركات المخزون", endpoint, count: downloaded[endpoint] });
      }));
      const failedMovement = results.find((result) => result.status === "rejected");
      if (failedMovement) throw failedMovement.reason || new Error("تعذر تنزيل حركة أحد أصناف المخزون");
    }
  }
  onProgress({ percent: 95, label: "التحقق من البيانات" });
  const health = await getLocalStorageHealth();
  if (isNativeStorage() && (!health.device || health.data < steps.length)) throw new Error("لم تكتمل كتابة البيانات الأساسية في SQLite.");
  await setOfflineMeta("bootstrap_counts", downloaded);
  await setOfflineMeta("bootstrap_verified", { completed_at: nowIso(), endpoints: Object.keys(downloaded).length, health });
  onProgress({ percent: 100, label: "اكتملت التهيئة" });
  return { downloaded, health };
};

/**
 * Full cloud-to-device synchronization.
 *
 * The cloud API remains the source of truth. Every successful GET in the
 * bootstrap is cached by api.js and, on Android, written as a replaceable
 * snapshot into local_data in gawad_net_local.db. A single promise prevents
 * launch/resume/manual refresh from running two SQLite writes concurrently.
 */
export const syncCloudDataToLocal = async (user, onProgress = () => {}) => {
  if (!user) return { skipped: true, reason: "no-user" };
  if (!isOnline()) return { skipped: true, reason: "offline" };
  if (cloudSyncPromise) return cloudSyncPromise;

  cloudSyncPromise = (async () => {
    const startedAt = nowIso();
    await initOfflineStorage(onProgress);
    await setOfflineMeta("cloud_sync_state", { state: "syncing", started_at: startedAt, user_id: user?.id || user?.username || null });
    try {
      const result = await bootstrapLocalData(user, onProgress);
      const completedAt = nowIso();
      const state = {
        state: "completed",
        started_at: startedAt,
        completed_at: completedAt,
        user_id: user?.id || user?.username || null,
        endpoints: Object.keys(result.downloaded || {}).length,
        records: Object.values(result.downloaded || {}).reduce((sum, count) => sum + Number(count || 0), 0),
      };
      await setOfflineMeta("cloud_sync_state", state);
      await setOfflineMeta("last_cloud_sync", state);
      window.dispatchEvent(new CustomEvent("cloud-data-synced", { detail: { ...state, result } }));
      return { ...result, state };
    } catch (error) {
      await setOfflineMeta("cloud_sync_state", { state: "failed", started_at: startedAt, failed_at: nowIso(), error: error?.message || String(error) });
      window.dispatchEvent(new CustomEvent("cloud-data-sync-failed", { detail: { error } }));
      throw error;
    }
  })().finally(() => { cloudSyncPromise = null; });

  return cloudSyncPromise;
};

export { nativeDataPut, verifyNativeDatabase };
