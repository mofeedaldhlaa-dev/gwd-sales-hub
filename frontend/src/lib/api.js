import axios from "axios";
import { cacheGetResponse, getCachedResponse, isOnline, isNativeStorage, nativeDataPut, queueAxiosRequest, shouldQueueAxiosRequest } from "./offline";
import { genUUID } from "./utils";
import { API_BASE } from "./apiConfig";

export { API_BASE } from "./apiConfig";

const api = axios.create({ baseURL: API_BASE, timeout: 30_000 });

api.interceptors.request.use(async (config) => {
  config.headers = config.headers || {};
  const token = localStorage.getItem("jwd_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const method = (config.method || "get").toLowerCase();
  if (["post", "put", "patch", "delete"].includes(method) && !config.__skipIdempotency && !(config.data instanceof FormData)) {
    let body = config.data;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { body = {}; }
    }
    // Preserve a key already created by the operation form. The request header,
    // body, and offline queue must all use exactly the same identifiers.
    const key = config.__idempotencyKey || body?.idempotency_key || genUUID();
    const localOperationId = config.__localOperationId || body?.local_operation_id || genUUID();
    config.__idempotencyKey = key;
    config.__localOperationId = localOperationId;
    config.headers["Idempotency-Key"] = key;
    if (body && typeof body === "object" && !Array.isArray(body)) {
      config.data = {
        ...body,
        idempotency_key: key,
        local_operation_id: localOperationId,
      };
    }
  }
  if (shouldQueueAxiosRequest(config) && !isOnline()) {
    const offlineError = new Error("OFFLINE_QUEUE");
    offlineError.__offlineQueue = true;
    offlineError.config = config;
    throw offlineError;
  }
  return config;
});

const isPublicRequest = (error) => {
  const url = error?.config?.url || "";
  return url.includes("/public/");
};

const isCustomerPortalPage = () => {
  const p = window.location.pathname || "";
  return p === "/net" || p === "/order" || p === "/order-card" || p.startsWith("/order/") || p.startsWith("/order-card/");
};

const makeCachedResponse = (config, data) => ({
  data,
  status: 200,
  statusText: "OK (local cache)",
  headers: { "x-offline-cache": "1" },
  config,
  request: null,
});

const makeQueuedResponse = (config, queued) => ({
  data: queued.response,
  status: 202,
  statusText: "Accepted (queued locally)",
  headers: { "x-offline-queued": "1" },
  config,
  request: null,
});

api.interceptors.response.use(
  async (response) => {
    if ((response.config?.method || "get").toLowerCase() === "get") {
      try { await cacheGetResponse(response.config, response.data); } catch (_) { /* cache is best effort */ }
      if (isNativeStorage()) {
        try {
          const rawUrl = String(response.config?.url || "").split("?")[0];
          const endpoint = rawUrl.replace(/^https?:\/\/[^/]+/, "").replace(/^\/+/, "").replace(/\/$/, "") || "root";
          await nativeDataPut(endpoint, "response", response.data);
        } catch (_) { /* local snapshot is best effort; never fail an online request */ }
      }
    }
    return response;
  },
  async (error) => {
    const config = error?.config || {};
    const method = (config.method || "get").toLowerCase();
    const hasNetworkFailure = !error?.response;

    if (shouldQueueAxiosRequest(config) && (error?.__offlineQueue || hasNetworkFailure)) {
      try {
        const queued = await queueAxiosRequest(config);
        return makeQueuedResponse(config, queued);
      } catch (_) {
        // Preserve the original error if local storage itself is unavailable.
      }
    }

    if (method === "get" && hasNetworkFailure) {
      try {
        const cached = await getCachedResponse(config);
        if (cached !== undefined) return makeCachedResponse(config, cached);
      } catch (_) { /* fall through to the normal error */ }
    }

    if (error.response?.status === 401) {
      if (!isPublicRequest(error) && !isCustomerPortalPage() && !window.location.pathname.includes("/mof30")) {
        localStorage.removeItem("jwd_token");
        window.location.href = "/mof30";
      }
    }
    return Promise.reject(error);
  },
);

export const errText = (e) => {
  if (e?.response?.status === 202 && e?.response?.headers?.["x-offline-queued"]) {
    return "تم حفظ العملية محلياً وستتم مزامنتها تلقائياً عند عودة الاتصال.";
  }
  const d = e?.response?.data?.detail;
  if (!e?.response) {
    if (!isOnline()) return "لا توجد نسخة محلية محفوظة لهذا القسم بعد. افتح التطبيق مرة واحدة مع توفر الإنترنت لمزامنة البيانات.";
    if (e?.code === "ECONNABORTED") return "انتهت مهلة الاتصال بالخادم. تحقق من الشبكة وحاول مرة أخرى.";
    return "تعذر الاتصال بالخادم. تحقق من الإنترنت ثم أعد المحاولة.";
  }
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join(" - ");
  if (d) return JSON.stringify(d);
  const status = e.response.status;
  if (status === 401) return "انتهت الجلسة أو بيانات الدخول غير صحيحة.";
  if (status === 403) return "لا تملك الصلاحية لتنفيذ هذه العملية.";
  if (status === 409) return "تعارضت العملية مع بيانات محفوظة مسبقاً. حدّث الشاشة ثم أعد المحاولة.";
  if (status === 422) return "بعض البيانات المدخلة غير صالحة.";
  if (status >= 500) return "حدث خطأ داخلي في الخادم. لم تُعتبر العملية ناجحة.";
  return e?.message || "حدث خطأ";
};

export default api;
