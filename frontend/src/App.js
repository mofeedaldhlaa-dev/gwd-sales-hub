import { BrowserRouter, Routes, Route, Navigate, Link, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import { syncNow, getPending, isOnline } from "@/lib/offline";
import { toast } from "sonner";
import { formatAppNow } from "@/lib/DateService";
import {
  LayoutDashboard, ShoppingCart, PackagePlus, Users, Truck, CreditCard,
  Boxes, Receipt, Ticket, BarChart3, UserCog, Bell, UserPlus, ScrollText, Settings,
  Menu, Wifi, WifiOff, LogOut, Search, FolderOpen, Wallet, Send, ArrowLeftRight, MessageSquare, RefreshCw, Smartphone, RotateCcw
} from "lucide-react";

import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Sales from "@/pages/Sales";
import SaleForm from "@/pages/SaleForm";
import SalesReturns from "@/pages/SalesReturns";
import SalesReturnForm from "@/pages/SalesReturnForm";
import Purchases from "@/pages/Purchases";
import PurchaseForm from "@/pages/PurchaseForm";
import PurchaseReturns from "@/pages/PurchaseReturns";
import PurchaseReturnForm from "@/pages/PurchaseReturnForm";
import Customers from "@/pages/Customers";
import CustomerStatement from "@/pages/CustomerStatement";
import Suppliers from "@/pages/Suppliers";
import Cards from "@/pages/Cards";
import FreeCards from "@/pages/FreeCards";
import { Gift } from "lucide-react";
import Categories from "@/pages/Categories";
import Stock from "@/pages/Stock";
import Receipts from "@/pages/Receipts";
import Expenses from "@/pages/Expenses";
import Transfers from "@/pages/Transfers";
import Orders from "@/pages/Orders";
import Reports from "@/pages/Reports";
import Accounts from "@/pages/Accounts";
import AccountDetail from "@/pages/AccountDetail";
import UsersPage from "@/pages/Users";
import AuditLog from "@/pages/AuditLog";
import SettingsPage from "@/pages/Settings";
import MessageNotificationCenter from "@/pages/MessageNotificationCenter";
import PublicOrder from "@/pages/PublicOrder";
import BlockedCustomers from "@/pages/BlockedCustomers";
import Files from "@/pages/Files";
import BankAccounts from "@/pages/BankAccounts";
import SmsGateway from "@/pages/SmsGateway";
import OfflineBanner from "@/components/OfflineBanner";
import StockAlertsBell from "@/components/StockAlertsBell";
import PushSetup from "@/components/PushSetup";
import AppErrorBoundary from "@/components/AppErrorBoundary";
import OfflineSetupGate from "@/components/OfflineSetupGate";
import SessionSecurityGate from "@/components/SessionSecurityGate";
import { setActiveManifest } from "@/lib/pwaInstall";
import { DuplicateOperationDialog } from "@/lib/duplicateOperation";
import "@/index.css";
import api from "@/lib/api";
import { Capacitor } from "@capacitor/core";
import { startNativeNotificationPolling, stopNativeNotificationPolling } from "@/lib/nativeNotificationPolling";
import { getPendingBackgroundRoute } from "@/lib/backgroundWatch";
import { API_BASE } from "@/lib/apiConfig";
import { startBackgroundWatch, stopBackgroundWatch, setBackgroundWatchForeground, getSafeAreaTop } from "@/lib/backgroundWatch";

const ROUTER_BASENAME = String(process.env.PUBLIC_URL || "").replace(/\/$/, "") || undefined;

function NotificationBell() {
  const [count, setCount] = useState(0);
  const [reqCount, setReqCount] = useState(0);
  const [prefs, setPrefs] = useState({ enabled: true, in_app_enabled: true, account_requests_enabled: true });
  const readPrefs = () => {
    try { setPrefs({ enabled: true, in_app_enabled: true, account_requests_enabled: true, ...(JSON.parse(localStorage.getItem("gwd_notification_settings") || "{}")) }); }
    catch { setPrefs({ enabled: true, in_app_enabled: true, account_requests_enabled: true }); }
  };
  useEffect(() => {
    const fetchSummary = async () => {
      if (!prefs.enabled || !prefs.in_app_enabled) { setCount(0); setReqCount(0); return; }
      try {
        const r = await api.get("/notifications/summary");
        setCount(r.data?.general_unread || 0);
        setReqCount(r.data?.request_unread || 0);
      } catch {}
    };
    fetchSummary();
    const id = setInterval(fetchSummary, 30000);
    const onRefresh = () => fetchSummary();
    window.addEventListener("notif-refresh", onRefresh);
    window.addEventListener("notification-settings-changed", readPrefs);
    return () => { clearInterval(id); window.removeEventListener("notif-refresh", onRefresh); window.removeEventListener("notification-settings-changed", readPrefs); };
  }, [prefs.enabled, prefs.in_app_enabled]);
  if (!prefs.enabled || !prefs.in_app_enabled) return null;
  return (
    <div className="flex items-center gap-1">
      {prefs.account_requests_enabled && <Link to="/account-requests" onClick={() => { setReqCount(0); api.post("/notifications/mark-category-read?category=account_request").catch(() => {}); }} className="relative p-2 hover:bg-amber-50 rounded" data-testid="requests-bell-btn" title="طلبات إنشاء الحساب">
        <UserPlus size={18} className="text-amber-600" />
        {reqCount > 0 && <span className="absolute -top-0.5 -left-0.5 bg-amber-500 text-white text-[10px] rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center font-bold" data-testid="req-badge">{reqCount}</span>}
      </Link>}
      <Link to="/admin-notifications" onClick={() => { setCount(0); api.post("/notifications/mark-seen").catch(() => {}); }} className="relative p-2 hover:bg-slate-100 rounded" data-testid="bell-btn" title="إشعارات النظام">
        <Bell size={18} className="text-[#452480]" />
        {count > 0 && <span className="absolute -top-0.5 -left-0.5 bg-red-500 text-white text-[10px] rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center font-bold">{count}</span>}
      </Link>
    </div>
  );
}

const menu = [
  { path: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard, perm: "dashboard.view" },
  { path: "/sales", label: "المبيعات", icon: ShoppingCart, perm: "sales.view" },
  { path: "/sales-returns", label: "مرتجع المبيعات", icon: RotateCcw, perm: "sales.view" },
  { path: "/purchases", label: "المشتريات", icon: PackagePlus, perm: "purchases.view" },
  { path: "/purchase-returns", label: "مرتجع المشتريات", icon: RotateCcw, perm: "purchases.view" },
  { path: "/customers", label: "العملاء", icon: Users, perm: "customers.view" },
  { path: "/suppliers", label: "الموردون", icon: Truck, perm: "suppliers.view" },
  { path: "/cards", label: "الكروت", icon: CreditCard, perm: "cards.view" },
  { path: "/free-cards", label: "إرسال كرت مجاني", icon: Gift, perm: "cards.view" },
  { path: "/categories", label: "الفئات", icon: Ticket, perm: "categories.view" },
  { path: "/stock", label: "المخزون", icon: Boxes, perm: "stock.view" },
  { path: "/receipts", label: "السندات", icon: Receipt, perm: "receipts.view" },
  { path: "/expenses", label: "المصروفات", icon: Wallet, perm: "expenses.view" },
  { path: "/transfers", label: "التحويلات", icon: ArrowLeftRight, perm: "transfers.view" },
  { path: "/bank-accounts", label: "الحسابات البنكية", icon: Wallet, perm: "bank_accounts.view" },
  { path: "/sms-gateway", label: "SMS Gateway", icon: Smartphone, perm: "sms_gateway.view" },
  { path: "/orders", label: "طلبات الكروت", icon: Ticket, perm: "card_orders.view" },
  { path: "/reports", label: "التقارير", icon: BarChart3, perm: "reports.view" },
  { path: "/users", label: "المستخدمون", icon: UserCog, perm: "users.view" },
  { path: "/blocked", label: "العملاء المحظورون", icon: Bell, perm: "blocked_customers.view" },
  { path: "/message-center", label: "الرسائل والإشعارات", icon: MessageSquare, perm: "settings.view" },
  { path: "/audit", label: "سجل العمليات", icon: ScrollText, perm: "audit.view" },
  { path: "/settings", label: "الإعدادات", icon: Settings, perm: "settings.view" },
  { path: "/files", label: "الملفات", icon: FolderOpen, perm: "files.view" },
];

function Shell({ children }) {
  const { user, logout, hasPerm } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [online, setOnline] = useState(isOnline());
  const [pending, setPending] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState("idle");

  useEffect(() => {
    if (!user || !Capacitor.isNativePlatform()) return undefined;
    startNativeNotificationPolling(api);
    startBackgroundWatch({ token: localStorage.getItem("jwd_token"), baseUrl: API_BASE });
    // Ask once for the system notification permission so closed-app alerts can show.
    import("@capacitor/local-notifications")
      .then(({ LocalNotifications }) => (LocalNotifications.requestPermissions ? LocalNotifications.requestPermissions() : null))
      .catch(() => {});
    // Heartbeat: while this WebView is alive the background service stays quiet;
    // the moment it stops (app closed or killed) the service raises the alerts.
    const beat = () => setBackgroundWatchForeground(true);
    beat();
    // Alerts tapped while the app was closed carry the route of the operation.
    const openPendingRoute = () => {
      getPendingBackgroundRoute()
        .then((route) => { if (route) navigate(route); })
        .catch(() => {});
    };
    openPendingRoute();
    const heartbeat = setInterval(beat, 45000);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") setBackgroundWatchForeground(false);
      else { beat(); openPendingRoute(); }
    };
    document.addEventListener("visibilitychange", onVisibility);
    let appStateHandle = null;
    let cancelled = false;
    import("@capacitor/app").then(({ App }) => {
      if (cancelled) return;
      App.addListener("appStateChange", ({ isActive }) => {
        setBackgroundWatchForeground(isActive);
        if (isActive) {
          startBackgroundWatch({ token: localStorage.getItem("jwd_token"), baseUrl: API_BASE });
          openPendingRoute();
        }
      }).then((handle) => { appStateHandle = handle; }).catch(() => {});
    }).catch(() => {});
    return () => {
      cancelled = true;
      clearInterval(heartbeat);
      document.removeEventListener("visibilitychange", onVisibility);
      stopNativeNotificationPolling();
      stopBackgroundWatch();
      if (appStateHandle?.remove) appStateHandle.remove();
    };
  }, [user]);

  useEffect(() => {
    if (!user) return undefined;
    api.get("/settings").then((r) => {
      if (r.data?.notification_settings) localStorage.setItem("gwd_notification_settings", JSON.stringify(r.data.notification_settings));
      if (r.data?.messaging_settings) localStorage.setItem("gwd_messaging_settings", JSON.stringify(r.data.messaging_settings));
      window.dispatchEvent(new Event("notification-settings-changed"));
    }).catch(() => {});
    return undefined;
  }, [user]);

  const refreshPending = async () => {
    const p = await getPending();
    setPending(p.length);
    if (!isOnline()) setSyncStatus(p.length ? "offline" : "offline_empty");
    else if (!p.length && !syncing) setSyncStatus("synced");
  };

  const handleSync = async ({ silent = false } = {}) => {
    if (!isOnline()) { setSyncStatus("offline"); await refreshPending(); return; }
    setSyncing(true);
    setSyncStatus("syncing");
    try {
      const result = await syncNow();
      const remaining = await getPending();
      setPending(remaining.length);
      if (result.failed || result.permanent) {
        setSyncStatus("pending");
        const reason = remaining.find((item) => item.last_error)?.last_error;
        if (!silent) toast.error(`تمت مزامنة ${result.ok} عملية، وفشلت ${result.failed + result.permanent}${reason ? ` — ${reason}` : ""}`);
      } else if (result.ok) {
        setSyncStatus("synced");
        if (!silent) toast.success(`تمت مزامنة ${result.ok} عملية بنجاح`);
      } else if (!pending) {
        setSyncStatus("synced");
      }
    } catch (error) {
      setSyncStatus("pending");
      if (!silent) toast.error("تعذر إكمال المزامنة. بقيت العمليات محفوظة بانتظار إعادة المحاولة.");
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    const on = () => { setOnline(true); handleSync(); };
    const off = () => { setOnline(false); setSyncStatus("offline"); };
    const onQueue = () => refreshPending();
    const onSyncState = (event) => setSyncStatus(event.detail?.state || "syncing");
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    window.addEventListener("offline-queue-changed", onQueue);
    window.addEventListener("offline-sync-state", onSyncState);
    refreshPending();
    if (isOnline()) handleSync({ silent: true });
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
      window.removeEventListener("offline-queue-changed", onQueue);
      window.removeEventListener("offline-sync-state", onSyncState);
    };
  }, []);

  useEffect(() => { setOpen(false); refreshPending(); }, [location.pathname]);

  const items = menu.filter((m) => hasPerm(m.perm));

  return (
    <div className="min-h-screen bg-[#F6F4FB] flex" data-testid="app-shell">
      {/* Print header/footer */}
      <div className="print-only print-header">
        <div className="text-xl font-bold">شبكة جواد نت اللاسلكية</div>
        <div className="text-sm">المخاء • 784225716</div>
      </div>
      <div className="print-only print-footer">
        أنشأ الملف: {user?.name || user?.username || "-"} • {formatAppNow()}
      </div>
      {/* Sidebar Desktop */}
      <aside className="app-safe-top hidden md:flex fixed top-0 right-0 h-screen w-64 flex-col brand-gradient text-white z-30">
        <div className="p-5 border-b border-white/10">
          <div className="text-xl font-extrabold gold-text">شبكة جواد نت</div>
          <div className="text-xs opacity-70">اللاسلكية • 784225716</div>
        </div>
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {items.map((m) => {
            const active = location.pathname === m.path || (m.path !== "/dashboard" && location.pathname.startsWith(m.path));
            return (
              <Link key={m.path} to={m.path}
                data-testid={`nav-${m.perm}`}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${active ? "bg-[#D4AF37] text-[#1A0F33] font-bold" : "hover:bg-white/10"}`}>
                <m.icon size={18} />
                <span>{m.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-white/10">
          <button onClick={logout} data-testid="logout-btn" className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-red-500/20 text-sm">
            <LogOut size={16} /> تسجيل الخروج
          </button>
        </div>
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/50" />
          <aside className="app-safe-top absolute top-0 right-0 h-full w-72 brand-gradient text-white overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 border-b border-white/10">
              <div className="text-xl font-extrabold gold-text">شبكة جواد نت</div>
              <div className="text-xs opacity-70">784225716</div>
            </div>
            <nav className="p-3 space-y-1">
              {items.map((m) => (
                <Link key={m.path} to={m.path} className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm hover:bg-white/10" data-testid={`mnav-${m.perm}`}>
                  <m.icon size={18} /> <span>{m.label}</span>
                </Link>
              ))}
              <button onClick={logout} className="w-full mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/20 text-sm">
                <LogOut size={16} /> تسجيل الخروج
              </button>
            </nav>
          </aside>
        </div>
      )}

      <main className="flex-1 md:mr-64 flex flex-col min-h-screen min-w-0 w-full">
        <header className="app-safe-top sticky top-0 z-20 bg-white/95 backdrop-blur border-b border-slate-200">
          <div className="flex items-center justify-between gap-2 px-3 sm:px-4 py-3">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <button className="md:hidden p-2 -mr-2 shrink-0" onClick={() => setOpen(true)} data-testid="menu-btn" aria-label="menu"><Menu /></button>
              <div className="font-bold text-[#221340] truncate text-sm sm:text-base">
                {items.find((m) => location.pathname === m.path)?.label || "لوحة التحكم"}
              </div>
              <button
                type="button"
                onClick={() => window.dispatchEvent(new Event("open-cloud-refresh"))}
                className="shrink-0 inline-flex items-center justify-center rounded-full p-2 text-[#452480] hover:bg-[#452480]/10 focus:outline-none focus:ring-2 focus:ring-[#D4AF37]"
                title="تحديث بيانات التطبيق"
                aria-label="تحديث بيانات التطبيق"
                data-testid="open-cloud-refresh-btn"
              >
                <RefreshCw size={18} />
              </button>
            </div>
            <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
              <button onClick={() => handleSync()} disabled={syncing} data-testid="sync-btn" aria-label={online ? "متصل" : "غير متصل"} title={syncStatus} className={`flex items-center gap-1 text-xs px-2 sm:px-3 py-1.5 rounded-full disabled:opacity-60 ${!online ? "bg-red-100 text-red-700" : syncing ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"}`}>
                {!online ? <WifiOff size={14} /> : <Wifi size={14} />}
                <span className="hidden sm:inline">{!online ? `غير متصل${pending ? ` — ${pending} معلقة` : ""}` : syncing ? "جاري المزامنة..." : pending ? `${pending} بانتظار المزامنة` : "متصل — تمت المزامنة"}</span>
                {pending > 0 && <span className="mr-1 bg-amber-500 text-white rounded-full px-1.5">{pending}</span>}
              </button>
              <NotificationBell />
              <StockAlertsBell />
              <PushSetup />
              <div className="text-sm text-slate-600 hidden md:block max-w-[140px] truncate">{user?.name}</div>
            </div>
          </div>
        </header>
        <div className="flex-1 p-3 sm:p-4 md:p-6 pb-24 md:pb-6 min-w-0">{children}</div>
      </main>
    </div>
  );
}

function Guard({ children, perm }) {
  const { user, hasPerm } = useAuth();
  if (user === undefined) return <div className="min-h-screen flex items-center justify-center text-slate-500">جاري التحميل...</div>;
  if (user === null) return <Navigate to="/mof30" replace />;
  if (perm && !hasPerm(perm)) return <Shell><div className="p-8 text-center text-slate-500">لا تملك صلاحية الوصول إلى هذه الصفحة</div></Shell>;
  return <Shell>{children}</Shell>;
}

function NativeAdminRedirect() {
  const location = useLocation();
  const nav = useNavigate();
  useEffect(() => {
    if (Capacitor.isNativePlatform() && location.pathname === "/") nav("/mof30", { replace: true });
  }, [location.pathname, nav]);
  return null;
}

function AdminEntry() {
  const { user } = useAuth();
  if (user === undefined) return <div className="min-h-screen flex items-center justify-center" aria-label="loading"><div className="h-7 w-7 animate-spin rounded-full border-2 border-[#D4AF37] border-t-transparent" /></div>;
  if (user === null) return <Login />;
  return <Guard perm="dashboard"><Dashboard /></Guard>;
}

function AppRoutes() {
  const location = useLocation();
  useEffect(() => {
    // Swap active manifest: admin sub-app uses its own manifest with scope=/mof30,
    // public GAWAD NET uses the root manifest with scope=/.
    const adminScope = location.pathname === "/mof30" || location.pathname.startsWith("/dashboard") ||
      location.pathname.startsWith("/sales") || location.pathname.startsWith("/sales-returns") || location.pathname.startsWith("/purchases") || location.pathname.startsWith("/purchase-returns") ||
      location.pathname.startsWith("/customers") || location.pathname.startsWith("/suppliers") ||
      location.pathname.startsWith("/cards") || location.pathname.startsWith("/categories") ||
      location.pathname.startsWith("/stock") || location.pathname.startsWith("/receipts") ||
      location.pathname.startsWith("/expenses") || location.pathname.startsWith("/accounts") ||
      location.pathname.startsWith("/orders") || location.pathname.startsWith("/reports") ||
      location.pathname.startsWith("/users") || location.pathname.startsWith("/message-center") || location.pathname.startsWith("/admin-notifications") || location.pathname.startsWith("/account-requests") ||
      location.pathname.startsWith("/audit") || location.pathname.startsWith("/blocked") ||
      location.pathname.startsWith("/settings") || location.pathname.startsWith("/files") ||
      location.pathname.startsWith("/bank-accounts") || location.pathname.startsWith("/sms-gateway") || location.pathname.startsWith("/transfers");
    setActiveManifest(adminScope ? "/manifest-mof30.json" : "/manifest.json");
  }, [location.pathname]);
  return (
    <Routes>
      <Route path="/mof30" element={<AdminEntry />} />
      <Route path="/net" element={<Navigate to="/order" replace />} />
      <Route path="/order-card" element={<PublicOrder />} />
      <Route path="/order" element={<PublicOrder />} />
      <Route path="/" element={<PublicOrder />} />
      <Route path="/dashboard" element={<Guard perm="dashboard.view"><Dashboard /></Guard>} />
      <Route path="/sales" element={<Guard perm="sales.view"><Sales /></Guard>} />
      <Route path="/sales/new" element={<Guard perm="sales.create"><SaleForm /></Guard>} />
      <Route path="/sales/:id/edit" element={<Guard perm="sales.edit"><SaleForm /></Guard>} />
      <Route path="/sales-returns" element={<Guard perm="sales.view"><SalesReturns /></Guard>} />
      <Route path="/sales-returns/new" element={<Guard perm="sales.create"><SalesReturnForm /></Guard>} />
      <Route path="/purchases" element={<Guard perm="purchases.view"><Purchases /></Guard>} />
      <Route path="/purchases/new" element={<Guard perm="purchases.create"><PurchaseForm /></Guard>} />
      <Route path="/purchases/:id/edit" element={<Guard perm="purchases.edit"><PurchaseForm /></Guard>} />
      <Route path="/purchase-returns" element={<Guard perm="purchases.view"><PurchaseReturns /></Guard>} />
      <Route path="/purchase-returns/new" element={<Guard perm="purchases.create"><PurchaseReturnForm /></Guard>} />
      <Route path="/customers" element={<Guard perm="customers.view"><Customers /></Guard>} />
      <Route path="/customers/:id" element={<Guard perm="customers.view"><CustomerStatement /></Guard>} />
      <Route path="/suppliers" element={<Guard perm="suppliers.view"><Suppliers /></Guard>} />
      <Route path="/cards" element={<Guard perm="cards.view"><Cards /></Guard>} />
      <Route path="/free-cards" element={<Guard perm="cards.view"><FreeCards /></Guard>} />
      <Route path="/categories" element={<Guard perm="categories.view"><Categories /></Guard>} />
      <Route path="/stock" element={<Guard perm="stock.view"><Stock /></Guard>} />
      <Route path="/receipts" element={<Guard perm="receipts.view"><Receipts /></Guard>} />
      <Route path="/expenses" element={<Guard perm="expenses.view"><Expenses /></Guard>} />
      <Route path="/transfers" element={<Guard perm="transfers.view"><Transfers /></Guard>} />
      <Route path="/accounts" element={<Guard perm="receipts.view"><Accounts /></Guard>} />
      <Route path="/accounts/:type/:id" element={<Guard perm="receipts.view"><AccountDetail /></Guard>} />
      <Route path="/orders" element={<Guard perm="card_orders.view"><Orders /></Guard>} />
      <Route path="/reports" element={<Guard perm="reports.view"><Reports /></Guard>} />
      <Route path="/users" element={<Guard perm="users.view"><UsersPage /></Guard>} />
      <Route path="/message-center" element={<Guard perm="settings.view"><MessageNotificationCenter /></Guard>} />
      <Route path="/admin-notifications" element={<Guard perm="settings.view"><MessageNotificationCenter initialSection="admin_inbox" /></Guard>} />
      <Route path="/account-requests" element={<Guard perm="customers.manage"><MessageNotificationCenter initialSection="account_requests" /></Guard>} />
      <Route path="/audit" element={<Guard perm="audit.view"><AuditLog /></Guard>} />
      <Route path="/blocked" element={<Guard perm="blocked_customers.view"><BlockedCustomers /></Guard>} />
      <Route path="/settings" element={<Guard perm="settings.view"><SettingsPage /></Guard>} />
      <Route path="/files" element={<Guard perm="files.view"><Files /></Guard>} />
      <Route path="/bank-accounts" element={<Guard perm="bank_accounts.view"><BankAccounts /></Guard>} />
      <Route path="/sms-gateway" element={<Guard perm="sms_gateway.view"><SmsGateway /></Guard>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  useEffect(() => {
    // Android 15+ places the web view under the status bar; keep the shell
    // header and the drawers clear of it on small screens.
    let cancelled = false;
    (async () => {
      const result = await getSafeAreaTop();
      const top = Number(result && result.cssTop) || 0;
      if (!cancelled) {
        document.documentElement.style.setProperty("--native-safe-top", `${top}px`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <AppErrorBoundary>
      <AuthProvider>
        <BrowserRouter basename={ROUTER_BASENAME}>
          <SessionSecurityGate>
            <OfflineSetupGate>
              <NativeAdminRedirect />
              <OfflineBanner />
              <AppRoutes />
              <DuplicateOperationDialog />
              <Toaster position="top-center" />
            </OfflineSetupGate>
          </SessionSecurityGate>
        </BrowserRouter>
      </AuthProvider>
    </AppErrorBoundary>
  );
}
