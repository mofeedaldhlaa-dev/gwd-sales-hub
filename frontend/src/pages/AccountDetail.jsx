import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, Link, useLocation } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { fmt, fmtDate, genUUID, openWhatsApp, openWhatsAppUrl, buildReceiptMessage, buildInvoiceMessage } from "@/lib/utils";
import { printExpense, printStatement, printSaleInvoice } from "@/lib/print";
import InvoiceSuccessDialog from "@/components/InvoiceSuccessDialog";
import PeriodFilter from "@/components/PeriodFilter";
import { useAuth } from "@/lib/auth";
import { ArrowRight, Printer, Receipt, FilePlus, FileUp, Send, MessageCircle, Wallet, ArrowDownToLine, ShieldCheck } from "lucide-react";

import { monthStartIso, todayIso } from "@/lib/DateService";
const TYPE_LABELS = { cash: "الصندوق", cashbox: "صندوق سداد مرتبط", customer: "عميل", pos: "نقطة بيع", supplier: "مورد", expense: "حساب مصروفات" };

const hasValue = (value) => value !== null && value !== undefined && value !== "";
const transferDirectionLabel = (direction) => direction === "outgoing" ? "تحويل صادر" : direction === "incoming" ? "تحويل وارد" : "تحويل";
function TransferDetails({ entry }) {
  const d = entry?.transfer_details;
  if (!d) return null;
  const party = (name, phone) => `${hasValue(name) ? name : "غير متوفر"}${hasValue(phone) ? ` — ${phone}` : ""}`;
  return <div className="mt-2 rounded-md border border-[#452480]/15 bg-[#452480]/5 p-2 text-[11px]" data-testid="transfer-details">
    <div className="font-bold text-[#452480] mb-1">تفاصيل {transferDirectionLabel(d.direction)}</div>
    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-700">
      <div><span className="text-slate-500">المرسل: </span>{party(d.sender_name, d.sender_phone)}</div>
      <div><span className="text-slate-500">المستلم: </span>{party(d.recipient_name, d.recipient_phone)}</div>
      <div><span className="text-slate-500">المبلغ: </span><span className="num font-bold">{fmt(d.amount)}</span></div>
      {hasValue(d.commission) && <div><span className="text-slate-500">العمولة: </span><span className="num">{fmt(d.commission)}</span></div>}
      {hasValue(d.sender_debit) && <div><span className="text-slate-500">إجمالي الخصم: </span><span className="num">{fmt(d.sender_debit)}</span></div>}
      {hasValue(d.recipient_credit) && <div><span className="text-slate-500">المبلغ المستلم: </span><span className="num">{fmt(d.recipient_credit)}</span></div>}
      {hasValue(d.sender_balance_after) && <div><span className="text-slate-500">رصيد المرسل بعد العملية: </span><span className="num">{fmt(d.sender_balance_after)}</span></div>}
      {hasValue(d.recipient_balance_after) && <div><span className="text-slate-500">رصيد المستلم بعد العملية: </span><span className="num">{fmt(d.recipient_balance_after)}</span></div>}
      {hasValue(d.reference) && <div><span className="text-slate-500">المرجع: </span><span className="font-mono">{d.reference}</span></div>}
      {hasValue(d.channel) && <div><span className="text-slate-500">القناة: </span>{d.channel}</div>}
      {hasValue(d.note) && <div className="col-span-2"><span className="text-slate-500">البيان الأصلي: </span>{d.note}</div>}
    </div>
  </div>;
}
const transferPrintDescription = (entry) => {
  return entry?.description || "";
};


export default function AccountDetail() {
  const { type, id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [customTypeLabel, setCustomTypeLabel] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestSeq = useRef(0);
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso());
  const [period, setPeriod] = useState("day");
  const [openVoucher, setOpenVoucher] = useState(false);
  const [voucher, setVoucher] = useState({ kind: "receipt", amount: "", description: "", date: todayIso() });
  const [openReq, setOpenReq] = useState(false);
  const [req, setReq] = useState({ amount: "", message: "", method: "sms" });
  const [payReqs, setPayReqs] = useState([]);
  const [openWithdraw, setOpenWithdraw] = useState(false);
  const [withdrawAccounts, setWithdrawAccounts] = useState([]);
  const [withdraw, setWithdraw] = useState({ amount: "", dest_type: "customer", dest_id: "", description: "", date: todayIso() });
  const [openStatementImport, setOpenStatementImport] = useState(false);
  const [openStatementImportUnlock, setOpenStatementImportUnlock] = useState(false);
  const [statementImportUnlock, setStatementImportUnlock] = useState({ username: "", password: "" });
  const [statementImportUnlockToken, setStatementImportUnlockToken] = useState("");
  const [statementImportFile, setStatementImportFile] = useState(null);
  const [statementImport, setStatementImport] = useState(null);
  const [statementImportRows, setStatementImportRows] = useState([]);
  const [statementImportConfirm, setStatementImportConfirm] = useState(false);
  const [statementImportHistory, setStatementImportHistory] = useState([]);
  const [statementImportLoading, setStatementImportLoading] = useState(false);
  const [successInvoice, setSuccessInvoice] = useState(location.state?.savedInvoice || null);

  const load = async () => {
    const requestId = ++requestSeq.current;
    setError("");
    if (period === "custom" && (!start || !end || end < start)) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params = {};
      if (start) params.start = start;
      if (end) params.end = end;
      const r = await api.get(`/accounts/${type}/${id}/statement`, { params });
      if (requestId !== requestSeq.current) return;
      setData(r.data || { account: {}, entries: [], total_debit: 0, total_credit: 0, balance_before: 0, balance_after: 0 });
      if (type !== "cash" && type !== "cashbox" && type !== "expense") {
        try {
          const paymentRequests = await api.get("/payment-requests", { params: { party_type: type, party_id: id } });
          if (requestId === requestSeq.current) setPayReqs(Array.isArray(paymentRequests.data) ? paymentRequests.data : []);
        } catch (_) {
          if (requestId === requestSeq.current) setPayReqs([]);
        }
      }
    } catch (e) {
      if (requestId === requestSeq.current) {
        setData(null);
        setError(errText(e) || "تعذر تحميل بيانات الحساب");
      }
    } finally {
      if (requestId === requestSeq.current) setLoading(false);
    }
  };
  useEffect(() => {
    if (!location.state?.savedInvoice) return;
    setSuccessInvoice(location.state.savedInvoice);
    load();
    navigate(location.pathname, { replace: true, state: {} });
  }, [location.pathname, location.state, navigate]);
  useEffect(() => { load(); }, [type, id, start, end, period]);

  const stateLabel = (b) => b > 0 ? "عليه" : b < 0 ? "له" : "متعادل";
  const stateColor = (b) => b > 0 ? "text-red-700" : b < 0 ? "text-emerald-700" : "text-slate-500";

  const viewData = data || { account: {}, entries: [], total_debit: 0, total_credit: 0, balance_before: 0, balance_after: 0 };
  const acc = viewData.account || {};
  const entries = Array.isArray(viewData.entries) ? viewData.entries : [];

  const [openLastOp, setOpenLastOp] = useState(false);
  const [lastOp, setLastOp] = useState(null);
  // lastOp shape: { kind: "receipt"|"expense"|"sale", data: {...} }

  const saveVoucher = async () => {
    if (!voucher.amount || Number(voucher.amount) <= 0) { toast.error("أدخل مبلغاً صحيحاً"); return; }
    if (type === "cash" || type === "cashbox") { toast.error("لا يمكن إنشاء سند مباشرة للصندوق؛ تتم إضافة السداد الآلي إلى صندوق الحساب تلقائياً"); return; }
    try {
      let r;
      if (type === "expense") {
        r = await api.post("/expenses", {
          account_id: id,
          amount: Number(voucher.amount),
          description: voucher.description,
          date: voucher.date,
          idempotency_key: genUUID(),
        });
        setLastOp({ kind: "expense", data: r.data });
      } else {
        r = await api.post("/receipts", {
          kind: voucher.kind,
          party_type: type === "pos" ? "customer" : type,
          party_id: id,
          party_name: acc.name || "",
          amount: Number(voucher.amount),
          description: voucher.description,
          date: voucher.date,
          idempotency_key: genUUID(),
        });
        setLastOp({ kind: "receipt", data: r.data });
      }
      toast.success(r.status === 202 ? "تم حفظ العملية محلياً وستتم مزامنتها تلقائياً عند عودة الاتصال" : "تم الحفظ وتحديث الأرصدة");
      setOpenVoucher(false);
      setVoucher({ ...voucher, amount: "", description: "" });
      setOpenLastOp(true);
      load();
    } catch (e) { toast.error(errText(e)); }
  };

  const printLastOp = async () => {
    if (!lastOp) return;
    try {
      const banks = (await api.get("/bank-accounts").catch(() => ({ data: [] }))).data || [];
      if (lastOp.kind === "receipt") {
        const { printReceipt } = await import("@/lib/print");
        printReceipt({ receipt: lastOp.data, party: acc, username: acc.name || "", banks });
      } else {
        printExpense({ expense: lastOp.data, account: acc, username: user?.name || user?.username });
      }
    } catch (e) { toast.error(errText(e)); }
  };

  const whatsappLastOp = async () => {
    if (!lastOp) return;
    const phone = acc.phone || "";
    if (!phone) { toast.error("لا يوجد رقم هاتف مسجّل لهذا العميل"); return; }
    const d = lastOp.data || {};
    let body;
    if (lastOp.kind === "receipt") {
      let company = "شبكة جواد نت اللاسلكية";
      let settings = {};
      try { const s = await api.get("/settings"); settings = s.data || {}; company = settings.company_name || company; } catch {}
      const values = { kind: d.kind === "receipt" ? "لكم" : "عليكم", number: d.number, amount: d.amount, description: d.description || "-", balance_after: d.balance_after };
      const event = settings.message_event_settings?.voucher_success_whatsapp;
      if (event?.enabled === false || (event?.channels && !event.channels.includes("whatsapp"))) { toast.error("تم تعطيل رسالة نجاح السند من مركز الرسائل."); return; }
      const custom = (settings.message_templates || []).find((t) => t.key === "voucher_success_whatsapp")?.text;
      body = custom ? custom.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key] ?? "") : buildReceiptMessage({ company, kind: d.kind, number: d.number, amount: d.amount, description: d.description, balance_after: d.balance_after });
    } else {
      body = `تم تسجيل عملية بمبلغ ${fmt(d.amount || 0)}\n${d.description || ""}\n\nشبكة جواد نت اللاسلكية`;
    }
    openWhatsApp(phone, body);
  };

  const sendInvoiceWhatsApp = async (invoice) => {
    const phone = invoice?.account_phone || acc.phone;
    if (!phone) { toast.error("لا يوجد رقم هاتف مسجل لهذا الحساب."); return; }
    const details = (invoice.items || []).map((i) => `${i.category_name} × ${i.quantity} = ${fmt(i.total)}`).join("\n");
    let settings = {};
    try { settings = (await api.get("/settings")).data || {}; } catch {}
    const event = settings.message_event_settings?.sale_success_whatsapp;
    if (event?.enabled === false || (event?.channels && !event.channels.includes("whatsapp"))) { toast.error("تم تعطيل رسالة نجاح حفظ الفاتورة من مركز الرسائل."); return; }
    const values = { number: invoice.number, account_name: invoice.customer_name || acc.name || "", details, amount: invoice.subtotal, discount: invoice.discount || 0, total: invoice.total, paid: invoice.paid, remaining: invoice.remaining, balance_after: invoice.balance_after ?? acc.balance };
    const custom = (settings.message_templates || []).find((t) => t.key === "sale_success_whatsapp")?.text;
    const msg = custom ? custom.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key] ?? "") : buildInvoiceMessage({ company: settings.company_name || "شبكة جواد نت اللاسلكية", number: invoice.number, kind: "مبيعات", details, amount: invoice.subtotal, discount: invoice.discount, total: invoice.total, paid: invoice.paid, remaining: invoice.remaining, balance_after: invoice.balance_after ?? acc.balance });
    openWhatsApp(phone, msg);
  };

  const printSuccessInvoice = (invoice) => {
    printSaleInvoice({ sale: invoice, customer: { ...acc, phone: invoice.account_phone || acc.phone }, username: user?.name || user?.username });
  };

  const sendRequest = async () => {
    if (!req.amount || Number(req.amount) <= 0) { toast.error("أدخل المبلغ المطلوب"); return; }
    try {
      const r = await api.post("/payment-requests", {
        party_type: type === "pos" ? "customer" : type,
        party_id: id, amount: Number(req.amount),
        method: req.method, message: req.message,
        idempotency_key: genUUID(),
      });
      const p = r.data;
      const phone = acc.phone || "";
      // Use server-provided message (auto-includes bank accounts flagged for payment_requests)
      const body = p.message || req.message?.trim() || `طلب تسديد بمبلغ ${p.amount} — شبكة جواد نت اللاسلكية`;
      if (req.method === "whatsapp" && phone) {
        const wa = `https://wa.me/${phone.replace(/^0/, "967")}?text=${encodeURIComponent(body)}`;
        openWhatsAppUrl(wa);
      } else if (req.method === "sms" && phone) {
        window.location.href = `sms:${phone}?body=${encodeURIComponent(body)}`;
      }
      toast.success("تم إرسال طلب التسديد");
      setOpenReq(false);
      setReq({ amount: "", message: "", method: "sms" });
      load();
    } catch (e) { toast.error(errText(e)); }
  };

  const setReqStatus = async (rid, newStatus) => {
    try {
      await api.post(`/payment-requests/${rid}/status`, null, { params: { new_status: newStatus } });
      toast.success("تم التحديث"); load();
    } catch (e) { toast.error(errText(e)); }
  };

  const openWithdrawDialog = async () => {
    try {
      const response = await api.get("/accounts");
      setWithdrawAccounts((response.data || []).filter((item) => item.id !== id && item.status !== "disabled"));
      setWithdraw({ amount: "", dest_type: "customer", dest_id: "", description: "", date: todayIso() });
      setOpenWithdraw(true);
    } catch (e) {
      toast.error(errText(e) || "تعذر تحميل الحسابات المستلمة");
    }
  };

  const isClosedAccount = ["disabled", "closed"].includes(String(acc.status || "").toLowerCase());

  const openStatementImportDialog = async (unlockToken = "") => {
    setStatementImportFile(null);
    setStatementImport(null);
    setStatementImportRows([]);
    setStatementImportConfirm(false);
    if (unlockToken) setStatementImportUnlockToken(unlockToken);
    setOpenStatementImport(true);
    try {
      const headers = unlockToken ? { "X-Statement-Import-Unlock": unlockToken } : undefined;
      const r = await api.get(`/customers/${id}/statement-imports`, { headers });
      setStatementImportHistory(Array.isArray(r.data) ? r.data : []);
    } catch (_) { setStatementImportHistory([]); }
  };

  const requestStatementImport = () => {
    if (isClosedAccount) {
      setStatementImportUnlock({ username: "", password: "" });
      setOpenStatementImportUnlock(true);
      return;
    }
    openStatementImportDialog();
  };

  const unlockStatementImport = async () => {
    if (!statementImportUnlock.username.trim() || !statementImportUnlock.password) {
      toast.error("أدخل اسم مستخدم المدير وكلمة المرور");
      return;
    }
    setStatementImportLoading(true);
    try {
      const r = await api.post(`/customers/${id}/statement-import/unlock`, {
        customer_id: id,
        username: statementImportUnlock.username.trim(),
        password: statementImportUnlock.password,
      }, { __skipIdempotency: true });
      const token = r.data?.unlock_token || "";
      setStatementImportUnlockToken(token);
      setOpenStatementImportUnlock(false);
      setStatementImportUnlock({ username: "", password: "" });
      await openStatementImportDialog(token);
    } catch (e) { toast.error(errText(e)); }
    finally { setStatementImportLoading(false); }
  };

  const deleteStatementImport = async (importDoc) => {
    if (!importDoc?.id || importDoc.status === "approved") return;
    if (!window.confirm(`حذف ملف الاستيراد السابق "${importDoc.original_filename || "كشف PDF"}"؟`)) return;
    setStatementImportLoading(true);
    try {
      await api.delete(`/customers/${id}/statement-import/${importDoc.id}`, {
        headers: statementImportUnlockToken ? { "X-Statement-Import-Unlock": statementImportUnlockToken } : undefined,
      });
      setStatementImportHistory((current) => current.filter((item) => item.id !== importDoc.id));
      toast.success("تم حذف استيراد PDF السابق");
    } catch (e) { toast.error(errText(e)); }
    finally { setStatementImportLoading(false); }
  };

  const previewStatementImport = async () => {
    if (!statementImportFile) { toast.error("اختر ملف PDF أولاً"); return; }
    setStatementImportLoading(true);
    try {
      const form = new FormData();
      form.append("file", statementImportFile);
      const headers = statementImportUnlockToken ? { "X-Statement-Import-Unlock": statementImportUnlockToken } : undefined;
      const r = await api.post(`/customers/${id}/statement-import/preview`, form, { __skipIdempotency: true, headers });
      const imported = r.data?.import;
      setStatementImport(imported || null);
      setStatementImportRows(imported?.parsed?.rows || []);
      setStatementImportConfirm(false);
      if (r.data?.duplicate) toast.warning(imported?.status === "approved" ? "هذا الملف سبق اعتماده لهذا الحساب" : "هذا الملف سبق رفعه؛ راجع المعاينة الحالية");
      else toast.success("تمت قراءة الملف. راجع المعاينة قبل الاعتماد");
    } catch (e) { toast.error(errText(e)); }
    finally { setStatementImportLoading(false); }
  };

  const approveStatementImport = async () => {
    if (!statementImport?.id || !statementImportConfirm) { toast.error("راجع البيانات ثم فعّل تأكيد الاعتماد"); return; }
    setStatementImportLoading(true);
    try {
      await api.post(`/customers/${id}/statement-import/${statementImport.id}/approve`, {
        confirm: true,
        row_fingerprints: statementImportRows.map((row) => row.fingerprint),
      }, { headers: statementImportUnlockToken ? { "X-Statement-Import-Unlock": statementImportUnlockToken } : undefined });
      toast.success("تم اعتماد الحركات وتحديث رصيد العميل");
      setOpenStatementImport(false);
      setStatementImport(null);
      setStatementImportFile(null);
      load();
    } catch (e) { toast.error(errText(e)); }
    finally { setStatementImportLoading(false); }
  };

  const saveWithdraw = async () => {
    if (!withdraw.amount || Number(withdraw.amount) <= 0) { toast.error("أدخل مبلغ السحب"); return; }
    if (withdraw.dest_type !== "cash" && !withdraw.dest_id) { toast.error("اختر الحساب الذي سيستلم المبلغ"); return; }
    try {
      const destination = withdraw.dest_type === "cash" ? null : withdrawAccounts.find((item) => item.id === withdraw.dest_id);
      await api.post("/transfers", {
        source_type: "cashbox", source_id: id, source_name: acc.name || "صندوق المحفظة",
        dest_type: withdraw.dest_type, dest_id: withdraw.dest_type === "cash" ? null : withdraw.dest_id,
        dest_name: destination?.name || "الصندوق",
        amount: Number(withdraw.amount), description: withdraw.description, date: withdraw.date,
        block_negative: true, idempotency_key: genUUID(),
      });
      toast.success("تم السحب وتحديث رصيد صندوق المحفظة والحساب المستلم");
      setOpenWithdraw(false);
      load();
    } catch (e) { toast.error(errText(e)); }
  };

  const doPrint = () => {
    if (!data || loading || error) return;
    const labelP = { all: "شامل", day: "يومي", month: "شهري", year: "سنوي", custom: "مخصص" }[period];
    const rangeTxt = start && end ? ` — من ${start} إلى ${end}` : "";
    // Same statement template/system as the customers screens (lib/print.js → printStatement):
    // identical header, info order, column titles, debit/credit/balance rendering, totals and footer.
    printStatement({
      customer: { name: acc.name || "", phone: acc.phone || "", balance: acc.balance || 0 },
      typeLabel: TYPE_LABELS[type] || type,
      entries: entries.map((e) => ({
        created_at: e.created_at,
        op_number: e.number || "-",
        description: transferPrintDescription(e),
        debit: e.debit,
        credit: e.credit,
        balance: e.balance,
      })),
      closingBalance: viewData.balance_after,
      extraInfo: [{ lbl: "الرصيد قبل الفترة", val: fmt(viewData.balance_before) }],
      rangeTitle: `كشف حساب ${acc.name || ""} (${TYPE_LABELS[type] || customTypeLabel || type}) — ${labelP}${rangeTxt}`,
      username: user?.name || user?.username,
    });
  };

  const canAddVoucher = type !== "cash" && type !== "cashbox";  // customers, POS, suppliers, and expense accounts
  const canAddInvoice = type === "customer" || type === "pos" || type === "supplier";
  const canRequestPayment = type === "customer" || type === "pos" || type === "supplier";

  return (
    <div className="space-y-4" data-testid="account-detail">
      <div className="flex items-center gap-2 no-print">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)} data-testid="acc-back"><ArrowRight size={14}/></Button>
        <div className="text-lg font-bold text-[#221340]">تفاصيل الحساب</div>
      </div>

      <Card className="p-4 md:p-6">
        <div className="flex justify-between items-start flex-wrap gap-3">
          <div>
            <h2 className="text-xl font-bold flex items-center gap-2 text-[#221340]">
              {acc.name}
              <span className="text-xs bg-[#452480]/10 text-[#452480] px-2 py-0.5 rounded-full">{TYPE_LABELS[type] || type}</span>
            </h2>
            <div className="text-slate-500 text-sm mt-0.5">{acc.phone || "—"}</div>
          </div>
          <div className="text-left">
            <div className="text-xs text-slate-500">الرصيد الحالي</div>
            <div className={`text-2xl font-black num ${stateColor(acc.balance || 0)}`}>{fmt(acc.balance || 0)}</div>
            <div className={`text-xs font-bold ${stateColor(acc.balance || 0)}`}>{stateLabel(acc.balance || 0)}</div>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          <div className="bg-slate-50 p-3 rounded-lg"><div className="text-xs text-slate-500">إجمالي المدين</div><div className="num font-bold text-emerald-700">{fmt(viewData.total_debit)}</div></div>
          <div className="bg-slate-50 p-3 rounded-lg"><div className="text-xs text-slate-500">إجمالي الدائن</div><div className="num font-bold text-red-700">{fmt(viewData.total_credit)}</div></div>
          <div className="bg-slate-50 p-3 rounded-lg"><div className="text-xs text-slate-500">الرصيد قبل الفترة</div><div className="num font-bold">{fmt(viewData.balance_before)}</div></div>
          <div className="bg-slate-50 p-3 rounded-lg"><div className="text-xs text-slate-500">الرصيد النهائي</div><div className="num font-bold">{fmt(viewData.balance_after)}</div></div>
        </div>
      </Card>

      {/* Action buttons */}
      <Card className="p-3 flex flex-wrap gap-2 no-print" data-testid="acc-actions">
        {canAddVoucher && (
          <Button onClick={() => setOpenVoucher(true)} className="bg-[#221340]" data-testid="btn-add-voucher"><Receipt size={14} className="ml-1"/> {type === "expense" ? "إضافة مصروف" : "إضافة سند"}</Button>
        )}
        {canAddInvoice && (
          <Link to={type === "supplier" ? `/purchases/new?supplier=${id}&returnAccount=/accounts/${type}/${id}` : `/sales/new?customer=${id}&returnAccount=/accounts/${type}/${id}`}>
            <Button variant="outline" className="border-[#452480] text-[#452480]" data-testid="btn-add-invoice"><FilePlus size={14} className="ml-1"/> إضافة فاتورة</Button>
          </Link>
        )}
        {(type === "customer" || type === "pos") && (
          <Button onClick={requestStatementImport} variant="outline" className="border-[#452480] text-[#452480]" data-testid="btn-import-statement-pdf"><FileUp size={14} className="ml-1"/> استيراد كشف PDF</Button>
        )}
        {canRequestPayment && (
          <Button onClick={() => { setReq({ ...req, amount: Math.max(0, acc.balance || 0) || "" }); setOpenReq(true); }} variant="outline" className="border-amber-500 text-amber-700" data-testid="btn-request-payment"><Send size={14} className="ml-1"/> طلب تسديد</Button>
        )}
        {type === "cashbox" && (
          <Button onClick={openWithdrawDialog} variant="outline" className="border-emerald-600 text-emerald-700" data-testid="btn-withdraw-cashbox"><ArrowDownToLine size={14} className="ml-1"/> سحب من الحساب</Button>
        )}
        <Button onClick={doPrint} variant="outline" data-testid="btn-print"><Printer size={14} className="ml-1"/> طباعة الحساب</Button>
      </Card>

      {/* Period filter — يومي / شهري / سنوي / مخصص */}
      <Card className="p-3 no-print">
        <PeriodFilter
          period={period}
          start={start}
          end={end}
          onChange={({ period: p, start: s, end: e }) => { setPeriod(p); setStart(s); setEnd(e); if (p === "custom" && (!s || !e || e < s)) setData(null); }}
          testidPrefix="acc-period"
        />
      </Card>

       {loading && <Card className="p-4 text-center text-slate-500" data-testid="account-loading">جاري تحميل بيانات الحساب...</Card>}
       {!loading && error && (
         <Card className="p-4 text-center border-red-200 bg-red-50" data-testid="account-error">
           <div className="font-semibold text-red-700">تعذر تحميل بيانات الحساب</div>
           <div className="mt-1 text-sm text-red-600">{error}</div>
           <Button onClick={load} variant="outline" className="mt-3 border-red-300 text-red-700" data-testid="account-retry">إعادة المحاولة</Button>
         </Card>
       )}
       {!loading && !error && period === "custom" && (!start || !end || end < start) && (
         <Card className="p-4 text-center text-amber-700 bg-amber-50" data-testid="account-custom-incomplete">اختر تاريخ البداية والنهاية لعرض كشف الحساب</Card>
       )}
       {!loading && !error && entries.length === 0 && period !== "custom" && <Card className="p-4 text-center text-slate-500" data-testid="account-empty">لا توجد حركات خلال الفترة المحددة</Card>}
       {!loading && !error && entries.length === 0 && period === "custom" && start && end && end >= start && <Card className="p-4 text-center text-slate-500" data-testid="account-empty-custom">لا توجد حركات خلال الفترة المحددة</Card>}

       {/* Statement — table on desktop, cards on mobile (same style as customers screen) */}
      <Card className="overflow-x-auto hidden md:block" data-testid="acc-statement">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-right"><th className="p-3">تاريخ السند</th><th className="p-3">رقم العملية</th><th className="p-3">البيان والطرف المقابل</th><th className="p-3">مدين</th><th className="p-3">دائن</th><th className="p-3">الرصيد</th></tr>
          </thead>
          <tbody>
            <tr className="bg-slate-50 border-t font-bold">
              <td className="p-3" colSpan={5}>الرصيد قبل الفترة</td>
              <td className="p-3 num">{fmt(viewData.balance_before)}</td>
            </tr>
            {entries.map((e, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="p-3">{fmtDate(e.operation_at || e.created_at)}<div className="text-[10px] text-slate-400">وقت الإدخال: {String(e.created_at || "").slice(11, 16)}</div></td>
                <td className="p-3 font-mono text-[#452480] text-xs">{e.number || "-"}</td>
                <td className="p-3"><div>{e.description || "-"}</div>{!e.transfer_details && e.counterparty_name && <div className="text-xs text-[#452480] mt-1">الطرف المقابل: {e.counterparty_name}{e.counterparty_phone ? ` — ${e.counterparty_phone}` : ""}</div>}{e.reference && e.reference !== e.number && <div className="text-[10px] text-slate-400">المرجع: {e.reference}</div>}<TransferDetails entry={e}/></td>
                <td className="p-3 num text-emerald-700">{fmt(e.debit)}</td>
                <td className="p-3 num text-red-700">{fmt(e.credit)}</td>
                <td className="p-3 num font-bold">{fmt(e.balance)}</td>
              </tr>
            ))}
            {entries.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-slate-400">لا توجد حركات في هذه الفترة</td></tr>}
          </tbody>
          <tfoot>
            <tr className="bg-slate-100 font-bold border-t"><td className="p-3" colSpan={3}>الإجمالي</td><td className="p-3 num text-emerald-700">{fmt(viewData.total_debit)}</td><td className="p-3 num text-red-700">{fmt(viewData.total_credit)}</td><td className="p-3 num">{fmt(viewData.balance_after)}</td></tr>
          </tfoot>
        </table>
      </Card>
      <div className="md:hidden space-y-2" data-testid="acc-statement-mobile">
        <Card className="p-3 flex justify-between items-center text-sm bg-slate-50">
          <span className="font-bold text-slate-600">الرصيد قبل الفترة</span>
          <span className="num font-bold">{fmt(viewData.balance_before)}</span>
        </Card>
        {entries.map((e, i) => (
          <Card key={i} className="p-3 text-sm">
            <div className="flex justify-between items-start gap-2">
              <div className="min-w-0">
                <div className="text-xs text-slate-500">{fmtDate(e.created_at)}</div>
                <div className="font-mono text-[#452480] text-xs">{e.number || "-"}</div>
                <div className="mt-1 break-words">{e.description || "-"}</div>{!e.transfer_details && e.counterparty_name && <div className="text-xs text-[#452480] mt-1">الطرف المقابل: {e.counterparty_name}{e.counterparty_phone ? ` — ${e.counterparty_phone}` : ""}</div>}{e.reference && e.reference !== e.number && <div className="text-[10px] text-slate-400 mt-1">المرجع: {e.reference}</div>}<TransferDetails entry={e}/>
              </div>
              <div className="text-left shrink-0">
                <div className="text-xs">الرصيد</div>
                <div className="num font-bold">{fmt(e.balance)}</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-2 text-xs">
              <div><div className="text-slate-500">مدين</div><div className="num font-bold text-emerald-700">{fmt(e.debit)}</div></div>
              <div><div className="text-slate-500">دائن</div><div className="num font-bold text-red-700">{fmt(e.credit)}</div></div>
            </div>
          </Card>
        ))}
        {entries.length === 0 && <div className="text-center text-slate-400 p-6">لا توجد حركات في هذه الفترة</div>}
        <Card className="p-3 flex justify-between items-center text-sm bg-slate-100 font-bold">
          <span>الرصيد النهائي</span>
          <span className="num">{fmt(viewData.balance_after)}</span>
        </Card>
      </div>

      {/* Payment requests list */}
      {payReqs.length > 0 && (
        <Card className="p-3 no-print" data-testid="acc-payreqs">
          <div className="font-bold text-[#221340] mb-2">طلبات التسديد</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50"><tr className="text-right"><th className="p-2">الرقم</th><th className="p-2">التاريخ</th><th className="p-2">المبلغ</th><th className="p-2">الرسالة</th><th className="p-2">الحالة</th><th className="p-2">إجراء</th></tr></thead>
              <tbody>
                {payReqs.map((p) => (
                  <tr key={p.id} className="border-t">
                    <td className="p-2 font-mono">{p.number}</td>
                    <td className="p-2">{fmtDate(p.created_at)}</td>
                    <td className="p-2 num font-bold">{fmt(p.amount)}</td>
                    <td className="p-2 text-slate-600">{p.message || "-"}</td>
                    <td className="p-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${p.status==="paid"?"bg-emerald-100 text-emerald-700":p.status==="cancelled"?"bg-red-100 text-red-700":"bg-blue-100 text-blue-700"}`}>
                        {p.status === "new" ? "جديد" : p.status === "sent" ? "تم الإرسال" : p.status === "paid" ? "تم التسديد" : "ملغي"}
                      </span>
                    </td>
                    <td className="p-2 flex gap-1">
                      {p.status !== "paid" && <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => setReqStatus(p.id, "paid")} data-testid={`pr-paid-${p.id}`}>تم التسديد</Button>}
                      {p.status !== "cancelled" && <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => setReqStatus(p.id, "cancelled")} data-testid={`pr-cancel-${p.id}`}>إلغاء</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <InvoiceSuccessDialog
        open={!!successInvoice}
        onOpenChange={(open) => { if (!open) setSuccessInvoice(null); }}
        invoice={successInvoice}
        accountName={successInvoice?.customer_name || acc.name}
        paymentType={successInvoice?.invoice_payment_label || (successInvoice?.sale_type === "cash" ? "نقدي" : "آجل")}
        onWhatsApp={() => successInvoice && sendInvoiceWhatsApp(successInvoice)}
        onPrint={() => successInvoice && printSuccessInvoice(successInvoice)}
      />

      {/* Post-save actions Dialog */}
      <Dialog open={openLastOp} onOpenChange={setOpenLastOp}>
        <DialogContent className="max-w-sm" data-testid="last-op-dialog">
          <DialogHeader><DialogTitle>تمت العملية بنجاح</DialogTitle></DialogHeader>
          <div className="space-y-2 text-sm">
            <div className="bg-emerald-50 border border-emerald-200 rounded p-2 text-center">
              <div className="font-bold text-emerald-800">
                {lastOp?.kind === "receipt" ? `سند ${lastOp?.data?.kind === "receipt" ? "قبض" : "صرف"} رقم ${lastOp?.data?.number || "-"}` : "تم تسجيل المصروف"}
              </div>
              <div className="text-lg font-black num mt-1">{fmt(lastOp?.data?.amount || 0)}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button onClick={printLastOp} variant="outline" data-testid="last-op-print"><Printer size={14} className="ml-1"/> طباعة</Button>
              <Button onClick={whatsappLastOp} className="bg-green-600 hover:bg-green-700 text-white" data-testid="last-op-wa"><MessageCircle size={14} className="ml-1"/> إرسال واتساب</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Voucher Dialog */}
      <Dialog open={openVoucher} onOpenChange={setOpenVoucher}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{type === "expense" ? "إضافة مصروف" : "إضافة سند"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {type === "expense" ? (
              <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-800">
                سيتم خصم المبلغ من الصندوق وإضافته إلى حساب المصروف: <span className="font-bold">{acc.name}</span>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>نوع السند</Label>
                  <Select value={voucher.kind} onValueChange={(v) => setVoucher({ ...voucher, kind: v })}>
                    <SelectTrigger data-testid="voucher-kind"><SelectValue/></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="receipt">قبض</SelectItem>
                      <SelectItem value="payment">صرف</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div><Label>المبلغ</Label><Input type="number" value={voucher.amount} onChange={(e) => setVoucher({ ...voucher, amount: e.target.value })} data-testid="voucher-amount"/></div>
              </div>
            )}
            {type === "expense" && (
              <div><Label>المبلغ</Label><Input type="number" value={voucher.amount} onChange={(e) => setVoucher({ ...voucher, amount: e.target.value })} data-testid="voucher-amount"/></div>
            )}
            <div><Label>التاريخ</Label><Input type="date" value={voucher.date} onChange={(e) => setVoucher({ ...voucher, date: e.target.value })} data-testid="voucher-date"/></div>
            <div><Label>البيان</Label><Textarea value={voucher.description} onChange={(e) => setVoucher({ ...voucher, description: e.target.value })} data-testid="voucher-desc"/></div>
            <Button onClick={saveVoucher} className="w-full bg-[#221340]" data-testid="voucher-save">{type === "expense" ? "حفظ المصروف" : "حفظ السند"}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Payment Request Dialog */}
      <Dialog open={openReq} onOpenChange={setOpenReq}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>طلب تسديد</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="bg-amber-50 border border-amber-200 rounded p-2 text-xs text-amber-900">
              الرصيد المستحق: <span className="font-bold num">{fmt(Math.abs(acc.balance || 0))}</span> ({stateLabel(acc.balance || 0)})
              <div className="text-[10px] mt-1">إرسال الطلب لا يعدل الرصيد. يُعدَّل الرصيد فقط عند تسجيل سند التسديد.</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>المبلغ المطلوب</Label><Input type="number" value={req.amount} onChange={(e) => setReq({ ...req, amount: e.target.value })} data-testid="req-amount"/></div>
              <div>
                <Label>الوسيلة</Label>
                <Select value={req.method} onValueChange={(v) => setReq({ ...req, method: v })}>
                  <SelectTrigger data-testid="req-method"><SelectValue/></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sms">رسالة SMS</SelectItem>
                    <SelectItem value="whatsapp">واتساب</SelectItem>
                    <SelectItem value="manual">حفظ فقط</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>ملاحظة/رسالة (اختياري)</Label><Textarea value={req.message} onChange={(e) => setReq({ ...req, message: e.target.value })} placeholder={`طلب تسديد بمبلغ ...`} data-testid="req-message"/></div>
            <Button onClick={sendRequest} className="w-full bg-amber-600 hover:bg-amber-700" data-testid="req-send"><Send size={14} className="ml-1"/> إرسال الطلب</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={openWithdraw} onOpenChange={setOpenWithdraw}>
        <DialogContent className="max-w-lg" data-testid="cashbox-withdraw-dialog">
          <DialogHeader><DialogTitle>سحب من صندوق المحفظة</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">الرصيد المتاح في الصندوق: <span className="font-bold num">{fmt(acc.balance || 0)}</span></div>
            <div><Label>المبلغ</Label><Input type="number" min="0" value={withdraw.amount} onChange={(e) => setWithdraw({ ...withdraw, amount: e.target.value })} data-testid="cashbox-withdraw-amount" /></div>
            <div><Label>الحساب الذي تريد السحب إليه</Label><select value={withdraw.dest_type} onChange={(e) => setWithdraw({ ...withdraw, dest_type: e.target.value, dest_id: "" })} className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm" data-testid="cashbox-withdraw-dest-type"><option value="customer">عميل / نقطة بيع</option><option value="supplier">مورد</option><option value="expense">حساب مصروفات</option><option value="cashbox">صندوق محفظة آخر</option><option value="cash">الصندوق العام</option></select></div>
            {withdraw.dest_type !== "cash" && <div><Label>الحساب المستلم</Label><select value={withdraw.dest_id} onChange={(e) => setWithdraw({ ...withdraw, dest_id: e.target.value })} className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm" data-testid="cashbox-withdraw-dest"><option value="">اختر الحساب</option>{withdrawAccounts.filter((item) => { const itemType = item.base_type || item.type; return itemType === withdraw.dest_type || (withdraw.dest_type === "customer" && itemType === "pos"); }).map((item) => <option key={`${item.type}-${item.id}`} value={item.id}>{item.name} — {fmt(item.balance || 0)}</option>)}</select></div>}
            {withdraw.dest_type === "cash" && (() => { const cash = withdrawAccounts.find((item) => item.type === "cash"); return <div className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900" data-testid="cashbox-withdraw-general-cash-account"><div className="font-bold">الحساب المستلم: {cash?.name || "الصندوق العام"}</div><div className="mt-1 text-xs">الرصيد الحالي: <span className="num font-bold">{fmt(cash?.balance || 0)}</span></div></div>; })()}
            <div><Label>البيان</Label><Textarea value={withdraw.description} onChange={(e) => setWithdraw({ ...withdraw, description: e.target.value })} placeholder="بيان عملية السحب" data-testid="cashbox-withdraw-description" /></div>
            <div><Label>التاريخ</Label><Input type="date" value={withdraw.date} onChange={(e) => setWithdraw({ ...withdraw, date: e.target.value })} data-testid="cashbox-withdraw-date" /></div>
            <Button onClick={saveWithdraw} className="w-full bg-emerald-700" data-testid="cashbox-withdraw-save"><ArrowDownToLine size={14} className="ml-1"/> حفظ السحب</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={openStatementImportUnlock} onOpenChange={setOpenStatementImportUnlock}>
        <DialogContent className="max-w-md" data-testid="statement-import-unlock-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><ShieldCheck size={18} className="text-[#452480]"/> تحقق المدير قبل استيراد PDF</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900" data-testid="statement-import-closed-warning">
              هذا الحساب مغلق. لا يمكن فتح استيراد كشف PDF أو قراءة ملفاته إلا بعد إدخال بيانات مدير النظام.
            </div>
            <div><Label htmlFor="statement-import-admin-username">اسم مستخدم المدير</Label><Input id="statement-import-admin-username" value={statementImportUnlock.username} onChange={(e) => setStatementImportUnlock({ ...statementImportUnlock, username: e.target.value })} autoComplete="username" data-testid="statement-import-admin-username" /></div>
            <div><Label htmlFor="statement-import-admin-password">كلمة مرور المدير</Label><Input id="statement-import-admin-password" type="password" value={statementImportUnlock.password} onChange={(e) => setStatementImportUnlock({ ...statementImportUnlock, password: e.target.value })} autoComplete="current-password" data-testid="statement-import-admin-password" /></div>
            <Button onClick={unlockStatementImport} disabled={statementImportLoading} className="w-full bg-[#221340]" data-testid="statement-import-unlock-submit">{statementImportLoading ? "جارٍ التحقق..." : "تحقق وافتح استيراد PDF"}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={openStatementImport} onOpenChange={(open) => { setOpenStatementImport(open); if (!open) setStatementImportUnlockToken(""); }}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="statement-import-dialog">
          <DialogHeader><DialogTitle>استيراد كشف حساب سابق من PDF</DialogTitle></DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="rounded-md border border-[#452480]/20 bg-[#452480]/5 p-3 text-xs text-slate-700">
              ارفع كشف هذا الحساب فقط. ستتم المعاينة أولاً، ولن يتغير الرصيد أو سجل الحركات قبل ضغط «اعتماد الاستيراد».
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[240px] flex-1"><Label>ملف كشف الحساب</Label><Input type="file" accept="application/pdf,.pdf" onChange={(e) => setStatementImportFile(e.target.files?.[0] || null)} data-testid="statement-import-file" /></div>
              <Button onClick={previewStatementImport} disabled={!statementImportFile || statementImportLoading} className="bg-[#221340]" data-testid="statement-import-preview-btn">{statementImportLoading ? "جارٍ الفحص..." : "معاينة الملف"}</Button>
            </div>
            {statementImportHistory.length > 0 && !statementImport && <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs" data-testid="statement-import-history">
              <div className="font-bold text-slate-700 mb-2">الاستيرادات السابقة</div>
              <div className="space-y-2">
                {statementImportHistory.map((item) => {
                  const approved = item.status === "approved";
                  return <div key={item.id} className="flex items-center justify-between gap-2 rounded border bg-white p-2" data-testid={`statement-import-history-${item.id}`}>
                    <div className="min-w-0"><div className="truncate font-medium" title={item.original_filename || "كشف PDF"}>{item.original_filename || "كشف PDF"}</div><div className="text-[10px] text-slate-500">{approved ? "معتمد — لا يمكن حذفه" : "غير معتمد — يمكن حذفه"}</div></div>
                    <Button type="button" size="sm" variant="outline" onClick={() => deleteStatementImport(item)} disabled={approved || statementImportLoading} className={approved ? "text-slate-400" : "border-red-300 text-red-700"} data-testid={`statement-import-delete-${item.id}`}>{approved ? "معتمد" : "حذف"}</Button>
                  </div>;
                })}
              </div>
            </div>}
            {statementImport && (() => {
              const parsed = statementImport.parsed || {};
              const warnings = parsed.warnings || [];
              const selected = new Set(statementImportRows.map((row) => row.fingerprint));
              const toggleRow = (row) => setStatementImportRows((current) => current.some((item) => item.fingerprint === row.fingerprint) ? current.filter((item) => item.fingerprint !== row.fingerprint) : [...current, row]);
              return <div className="space-y-3" data-testid="statement-import-preview">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                  <div className="rounded border bg-slate-50 p-2"><div className="text-slate-500">الحركات</div><div className="font-bold num">{parsed.row_count || 0}</div></div>
                  <div className="rounded border bg-slate-50 p-2"><div className="text-slate-500">الرصيد الافتتاحي</div><div className="font-bold num">{fmt(parsed.computed_opening || 0)}</div></div>
                  <div className="rounded border bg-slate-50 p-2"><div className="text-slate-500">الرصيد في الملف</div><div className="font-bold num">{fmt(parsed.stated_closing || 0)}</div></div>
                  <div className="rounded border bg-slate-50 p-2"><div className="text-slate-500">طريقة القراءة</div><div className="font-bold">{parsed.extraction_method || "—"}</div></div>
                </div>
                <div className="rounded-md border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900" data-testid="statement-import-balance-effect">
                  سيُضاف صافي الرصيد المستورد <span className="font-bold num">{fmt(parsed.computed_closing || 0)}</span> إلى الرصيد الحالي <span className="font-bold num">{fmt(acc.balance || 0)}</span>؛ الرصيد المتوقع بعد الاعتماد <span className="font-bold num">{fmt((acc.balance || 0) + (parsed.computed_closing || 0))}</span>.
                </div>
                {warnings.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900" data-testid="statement-import-warnings"><div className="font-bold mb-1">لا يمكن الاعتماد قبل المراجعة</div>{warnings.map((warning, index) => <div key={index}>• {warning}</div>)}</div>}
                {statementImport.status === "approved" && <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">هذا الملف معتمد مسبقاً ولا يمكن تطبيقه مرة أخرى.</div>}
                <div className="overflow-x-auto rounded border" data-testid="statement-import-rows">
                  <table className="w-full text-xs"><thead className="bg-slate-50"><tr className="text-right"><th className="p-2">اختيار</th><th className="p-2">التاريخ</th><th className="p-2">البيان</th><th className="p-2">مدين</th><th className="p-2">دائن</th></tr></thead>
                    <tbody>{(parsed.rows || []).map((row) => <tr key={row.fingerprint} className="border-t"><td className="p-2"><input type="checkbox" checked={selected.has(row.fingerprint)} onChange={() => toggleRow(row)} disabled={statementImport.status === "approved"} /></td><td className="p-2 whitespace-nowrap">{row.date}</td><td className="p-2 min-w-[220px]">{row.description}{row.op_number ? ` — ${row.op_number}` : ""}</td><td className="p-2 num text-emerald-700">{fmt(row.debit || 0)}</td><td className="p-2 num text-red-700">{fmt(row.credit || 0)}</td></tr>)}</tbody>
                  </table>
                </div>
                {statementImport.status !== "approved" && <>
                  <label className="flex items-start gap-2 text-xs cursor-pointer"><input type="checkbox" checked={statementImportConfirm} onChange={(e) => setStatementImportConfirm(e.target.checked)} data-testid="statement-import-confirm" /><span>راجعت الحركات والرصيد الظاهرين أعلاه وأتحمل مسؤولية اعتماد هذا الكشف لهذا الحساب.</span></label>
                  <Button onClick={approveStatementImport} disabled={statementImportLoading || !statementImportConfirm || !parsed.can_approve || selected.size === 0} className="w-full bg-[#221340]" data-testid="statement-import-approve">{statementImportLoading ? "جارٍ الاعتماد..." : "اعتماد الاستيراد وتحديث الرصيد"}</Button>
                </>}
              </div>;
            })()}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
