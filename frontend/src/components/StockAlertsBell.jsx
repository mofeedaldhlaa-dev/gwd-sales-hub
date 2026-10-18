import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertTriangle, Boxes, ChevronLeft, PackageCheck, PackageX, Search } from "lucide-react";

const alertKey = (a) => `${a.type}:${a.category_id}`;

const alertDetails = (alert) => {
  const isNumbered = alert.type === "numbered";
  const available = Number(alert.available || 0);
  const threshold = Number(alert.threshold || 0);
  const ratio = threshold > 0 ? Math.min(100, Math.round((available / threshold) * 100)) : 0;
  const empty = available <= 0;

  return {
    label: isNumbered ? "كروت مرقمة" : "كروت كمية",
    metric: isNumbered ? "المتاح المرقم" : "الكمية المتاحة",
    ratio,
    empty,
    status: empty ? "نفد المخزون" : "منخفض ويحتاج متابعة",
  };
};

// Independent stock notifications bell shown at the top of the dashboard shell.
// The badge remains live until the stock is replenished above its threshold.
export default function StockAlertsBell() {
  const [alerts, setAlerts] = useState([]);
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(true);

  const readEnabled = useCallback(() => {
    try {
      const value = JSON.parse(localStorage.getItem("gwd_notification_settings") || "{}");
      setEnabled(value.enabled !== false && value.stock_alerts_enabled !== false);
    } catch { setEnabled(true); }
  }, []);

  const fetchAlerts = useCallback(async () => {
    readEnabled();
    if (!enabled) { setAlerts([]); return; }
    try {
      const r = await api.get("/stock/alerts");
      setAlerts(r.data?.alerts || []);
    } catch {}
  }, [enabled, readEnabled]);

  useEffect(() => {
    fetchAlerts();
    const id = setInterval(fetchAlerts, 30000);
    const onRefresh = () => fetchAlerts();
    const onSettings = () => { readEnabled(); fetchAlerts(); };
    window.addEventListener("stock-refresh", onRefresh);
    window.addEventListener("notification-settings-changed", onSettings);
    return () => {
      clearInterval(id);
      window.removeEventListener("stock-refresh", onRefresh);
      window.removeEventListener("notification-settings-changed", onSettings);
    };
  }, [fetchAlerts, readEnabled]);

  if (!enabled) return null;

  const count = alerts.length;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="relative rounded-xl border border-emerald-100 bg-white/80 p-2 shadow-sm transition hover:border-emerald-300 hover:bg-emerald-50"
        data-testid="stock-alerts-bell"
        title="تنبيهات المخزون"
        aria-label="تنبيهات المخزون"
      >
        <Boxes size={18} className="text-emerald-700" />
        {count > 0 && (
          <span
            className="absolute -left-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-black text-white shadow-sm"
            data-testid="stock-alerts-badge"
          >
            {count}
          </span>
        )}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[calc(100dvh-1rem)] max-w-xl gap-0 overflow-y-auto overflow-x-hidden border-0 bg-slate-50 p-0 shadow-2xl" data-testid="stock-alerts-dialog">
          <DialogHeader className="bg-gradient-to-l from-[#221340] to-[#452480] px-3 pb-3 pt-4 text-right text-white sm:px-6 sm:pb-5 sm:pt-6">
            <DialogTitle className="flex items-center justify-between gap-2 pl-7 text-right text-white sm:gap-3">
              <span className="flex min-w-0 items-center gap-2 sm:gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15 ring-1 ring-white/20 sm:h-11 sm:w-11 sm:rounded-xl">
                  <AlertTriangle size={18} className="text-amber-300 sm:h-[22px] sm:w-[22px]" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-base font-black sm:text-lg">تنبيهات المخزون</span>
                  <span className="mt-1 hidden text-xs font-normal text-white/70 sm:block">متابعة الفئات التي اقترب مخزونها من النفاد</span>
                </span>
              </span>
              <span className="num shrink-0 rounded-full bg-amber-400 px-2.5 py-1 text-xs font-black text-[#221340] sm:px-3 sm:text-sm">{count}</span>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-3 p-3 sm:space-y-4 sm:p-5">
            <div className="grid min-w-0 grid-cols-2 gap-2 sm:gap-3">
              <div className="min-w-0 rounded-lg border border-emerald-100 bg-white p-2.5 shadow-sm sm:rounded-xl sm:p-3">
                <div className="mb-1 flex min-w-0 items-center gap-1.5 truncate text-[10px] font-bold text-slate-500 sm:gap-2 sm:text-xs">
                  <AlertTriangle size={13} className="shrink-0 text-amber-500" /> الحالة الحالية
                </div>
                <div className="num text-lg font-black text-[#221340] sm:text-xl">{count}</div>
                <div className="truncate text-[10px] text-slate-500 sm:text-[11px]">تنبيه يحتاج متابعة</div>
              </div>
              <div className="min-w-0 rounded-lg border border-purple-100 bg-white p-2.5 shadow-sm sm:rounded-xl sm:p-3">
                <div className="mb-1 flex min-w-0 items-center gap-1.5 truncate text-[10px] font-bold text-slate-500 sm:gap-2 sm:text-xs">
                  <Boxes size={13} className="shrink-0 text-[#452480]" /> الإجراء المقترح
                </div>
                <div className="truncate text-xs font-black text-[#221340] sm:text-sm">مراجعة المخزون</div>
                <div className="truncate text-[10px] text-slate-500 sm:text-[11px]">افتح الفئة لمعرفة التفاصيل</div>
              </div>
            </div>

            <div className="min-w-0 space-y-2.5 sm:space-y-3" data-testid="stock-alerts-list">
              {count === 0 && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-7 text-center text-slate-500 sm:rounded-xl sm:px-4 sm:py-10" data-testid="stock-alerts-empty">
                  <PackageCheck size={32} className="mx-auto mb-2 text-emerald-600 sm:h-[38px] sm:w-[38px]" />
                  <div className="text-sm font-bold text-[#221340] sm:text-base">المخزون بحالة جيدة</div>
                  <div className="mt-1 text-[11px] sm:text-xs">لا توجد فئات وصلت إلى حد التنبيه حالياً</div>
                </div>
              )}

              {alerts.map((alert) => {
                const details = alertDetails(alert);
                return (
                  <Link
                    key={alertKey(alert)}
                    to={`/stock?category=${alert.category_id}&type=${alert.type}`}
                    onClick={() => setOpen(false)}
                    data-testid={`stock-alert-${alert.type}-${alert.category_id}`}
                    className="group block min-w-0 rounded-lg border border-amber-200 bg-white p-3 text-right shadow-sm transition hover:-translate-y-0.5 hover:border-amber-400 hover:shadow-md sm:rounded-xl sm:p-4"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2 sm:gap-3">
                      <div className="flex min-w-0 items-start gap-2 sm:gap-3">
                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg sm:h-10 sm:w-10 sm:rounded-xl ${details.empty ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-600"}`}>
                          {details.empty ? <PackageX size={17} className="sm:h-5 sm:w-5" /> : <AlertTriangle size={17} className="sm:h-5 sm:w-5" />}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-black text-[#221340] sm:text-base">{alert.category_name || "فئة مخزون"}</div>
                          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-[10px] sm:gap-2 sm:text-[11px]">
                            <span className="max-w-full truncate rounded-full bg-slate-100 px-1.5 py-0.5 font-bold text-slate-600 sm:px-2 sm:py-1">{details.label}</span>
                            <span className={details.empty ? "font-bold text-red-600" : "font-bold text-amber-700"}>{details.status}</span>
                          </div>
                        </div>
                      </div>
                      <ChevronLeft size={16} className="mt-1 shrink-0 text-slate-300 transition group-hover:-translate-x-1 group-hover:text-[#452480] sm:h-[18px] sm:w-[18px]" />
                    </div>

                    <div className="mt-3 min-w-0 rounded-lg bg-slate-50 p-2.5 sm:mt-4 sm:rounded-xl sm:p-3">
                      <div className="flex min-w-0 items-end justify-between gap-2 sm:gap-3">
                        <div>
                          <div className="text-[10px] text-slate-500 sm:text-[11px]">{details.metric}</div>
                          <div className={`num mt-0.5 text-xl font-black sm:mt-1 sm:text-2xl ${details.empty ? "text-red-600" : "text-amber-700"}`}>{alert.available}</div>
                        </div>
                        <div className="text-left text-[10px] text-slate-500 sm:text-[11px]">
                          <div>حد التنبيه</div>
                          <div className="num mt-0.5 font-black text-[#221340] sm:mt-1">{alert.threshold}</div>
                        </div>
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 sm:mt-3 sm:h-2" aria-label={`نسبة المخزون ${details.ratio}%`}>
                        <div className={`h-full rounded-full transition-all ${details.empty ? "bg-red-500" : "bg-amber-500"}`} style={{ width: `${details.ratio}%` }} />
                      </div>
                      <div className="mt-1.5 flex min-w-0 items-start justify-between gap-2 text-[9px] text-slate-400 sm:mt-2 sm:text-[10px]">
                        <span className="min-w-0 break-words leading-4">{alert.message || `المتاح ${alert.available} — الحد ${alert.threshold}`}</span>
                        <span className="flex shrink-0 items-center gap-1 pt-0.5 font-bold text-[#452480]"><Search size={11} /> عرض</span>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>

            <Link
              to="/stock"
              onClick={() => setOpen(false)}
              className="flex items-center justify-center gap-2 rounded-lg bg-[#452480] px-3 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-[#221340] sm:rounded-xl sm:px-4 sm:py-3 sm:text-sm"
              data-testid="stock-alerts-open-stock"
            >
              <Boxes size={16} /> فتح شاشة المخزون كاملة
            </Link>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
