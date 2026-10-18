import { useEffect, useMemo, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fmt } from "@/lib/utils";
import { printStockReport, printBalanceStockReport } from "@/lib/print";
import { AlertTriangle, Boxes, Printer, Search, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import PeriodFilter from "@/components/PeriodFilter";
import { todayIso } from "@/lib/DateService";

export default function Stock() {
  const [data, setData] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [balanceOpen, setBalanceOpen] = useState(false);
  const [balanceAmount, setBalanceAmount] = useState("");
  const [balanceDescription, setBalanceDescription] = useState("");
  const [balanceOps, setBalanceOps] = useState([]);
  const [balancePeriod, setBalancePeriod] = useState("day");
  const [balanceStart, setBalanceStart] = useState(todayIso());
  const [balanceEnd, setBalanceEnd] = useState(todayIso());
  const [savingBalance, setSavingBalance] = useState(false);

  const load = async (range = {}) => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (range.start) params.start = range.start;
      if (range.end) params.end = range.end;
      const [stockResponse, operationsResponse] = await Promise.all([
        api.get("/stock"),
        api.get("/stock/balance/operations", { params }).catch(() => ({ data: [] })),
      ]);
      setData(Array.isArray(stockResponse.data) ? stockResponse.data : []);
      setBalanceOps(Array.isArray(operationsResponse.data) ? operationsResponse.data : []);
    } catch (e) {
      setData([]);
      setError(errText(e) || "تعذر تحميل المخزون");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load({ start: balanceStart, end: balanceEnd }); }, []);

  const balanceRow = data.find((s) => s.is_balance || s.category_name === "رصيد");
  const rows = useMemo(() => data.filter((s) => !q.trim() || `${s.category_name || ""} ${s.category_id || ""}`.toLowerCase().includes(q.trim().toLowerCase())), [data, q]);
  const total = rows.filter((s) => !s.is_balance).reduce((sum, s) => sum + Number(s.available_total || 0), 0);
  const visibleBalanceOps = useMemo(() => {
    return balanceOps.filter((op) => {
      const day = String(op.created_at || "").slice(0, 10);
      return (!balanceStart || day >= balanceStart) && (!balanceEnd || day <= balanceEnd);
    });
  }, [balanceOps, balanceStart, balanceEnd]);

  const addBalance = async () => {
    const amount = Number(balanceAmount);
    if (!amount || amount <= 0) { toast.error("أدخل مبلغاً صحيحاً"); return; }
    setSavingBalance(true);
    try {
      await api.post("/stock/balance/add", { amount, description: balanceDescription || "إضافة إلى مخزون رصيد", idempotency_key: crypto.randomUUID?.() || `${Date.now()}` });
      toast.success("تمت إضافة المبلغ إلى مخزون رصيد");
      setBalanceAmount(""); setBalanceDescription(""); setBalanceOpen(false);
      await load({ start: balanceStart, end: balanceEnd });
    } catch (e) { toast.error(errText(e)); }
    finally { setSavingBalance(false); }
  };

  const applyBalancePeriod = ({ period, start, end }) => {
    setBalancePeriod(period); setBalanceStart(start || ""); setBalanceEnd(end || "");
    if (period === "custom" && (!start || !end || end < start)) { setBalanceOps([]); return; }
    load({ start, end });
  };

  const doPrint = () => {
    if (!rows.length) { toast.error("لا توجد بيانات مخزون للطباعة"); return; }
    printStockReport({ rows: rows.map((s) => ({ category_name: s.category_name, available_numbered: s.is_balance ? 0 : (s.numbered?.available || 0), available_quantity: s.quantity?.available || 0 })) });
  };

  const doPrintBalanceOps = () => {
    if (!visibleBalanceOps.length) { toast.error("لا توجد حركات رصيد ضمن الفترة المحددة"); return; }
    printBalanceStockReport({ rows: visibleBalanceOps, start: balanceStart, end: balanceEnd });
  };

  return <div className="space-y-4" data-testid="stock-page">
    <div className="flex flex-col sm:flex-row gap-2 sm:items-center justify-between">
      <div><h1 className="text-xl font-black text-[#221340] flex items-center gap-2"><Boxes size={20}/> المخزون</h1><p className="text-xs text-slate-500 mt-1">الكمية المتاحة لا تشمل مبلغ مخزون الرصيد</p></div>
      <div className="flex gap-2 flex-wrap"><Button variant="outline" onClick={() => load({ start: balanceStart, end: balanceEnd })} disabled={loading} data-testid="stock-refresh"><RefreshCw size={14} className="ml-1"/> تحديث</Button><Button onClick={() => setBalanceOpen(true)} className="bg-emerald-700" data-testid="balance-add-open">إضافة إلى رصيد</Button><Button onClick={doPrint} className="bg-[#452480]" data-testid="stock-print"><Printer size={14} className="ml-1"/> تقرير PDF</Button></div>
    </div>
    <Card className="p-3"><div className="relative"><Search size={17} className="absolute right-3 top-2.5 text-slate-400"/><Input className="pr-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="بحث باسم الفئة أو الكود..." data-testid="stock-search"/></div></Card>
    {error && <Card className="p-4 border-red-200 bg-red-50 text-red-700">{error}</Card>}
    {loading ? <Card className="p-8 text-center text-slate-500">جاري تحميل المخزون...</Card> : <>
      <Card className="p-4 bg-gradient-to-l from-[#221340] to-[#452480] text-white"><div className="text-sm text-white/75">إجمالي الكمية المتاحة</div><div className="text-3xl font-black num mt-1">{fmt(total)}</div><div className="text-xs text-white/70 mt-1">{rows.filter((s) => !s.is_balance).length} فئة كروت ظاهرة</div></Card>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{rows.map((s) => <Card key={s.category_id} className={`p-4 ${s.is_balance ? "border-emerald-300 bg-emerald-50" : s.low_stock ? "border-amber-400 bg-amber-50" : ""}`} data-testid={`stock-${s.category_id}`}><div className="flex justify-between gap-2"><div><div className="font-bold text-lg text-[#221340]">{s.category_name}</div>{s.is_balance && <div className="text-xs text-emerald-700">مخزون مالي لتحويل الرصيد — لا يدخل في إجمالي الكمية</div>}</div>{s.low_stock && <div className="text-amber-700 text-xs flex items-center gap-1"><AlertTriangle size={14}/> منخفض</div>}</div>{s.is_balance ? <div className="mt-4 rounded-lg bg-[#452480]/10 p-3 text-center"><div className="text-sm text-slate-600">الباقي المتاح المرسل — الرصيد كامل</div><div className="text-3xl font-black num text-[#452480]">{fmt(s.quantity?.available || 0)}</div></div> : <div className="mt-4 grid grid-cols-2 gap-2 text-center"><div className="rounded-lg bg-slate-50 p-2"><div className="text-[11px] text-slate-600">مرقمة</div><div className="text-lg font-bold num">{fmt(s.numbered?.available || 0)}</div></div><div className="rounded-lg bg-slate-50 p-2"><div className="text-[11px] text-slate-600">كمية</div><div className="text-lg font-bold num">{fmt(s.quantity?.available || 0)}</div></div></div>}</Card>)}{rows.length === 0 && <Card className="p-8 text-center text-slate-400 md:col-span-2">لا توجد بيانات مطابقة</Card>}</div>
      {balanceRow && <Card className="p-4 border-emerald-200"><div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3"><div className="font-bold text-[#221340]">حركات مخزون رصيد</div><Button onClick={doPrintBalanceOps} size="sm" className="bg-[#452480]" data-testid="balance-stock-print"><Printer size={14} className="ml-1"/> طباعة PDF للحركات</Button></div><div className="bg-slate-50 border rounded-lg p-3 mb-3"><PeriodFilter period={balancePeriod} start={balanceStart} end={balanceEnd} onChange={applyBalancePeriod} testidPrefix="balance-stock-period" /></div><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-right border-b"><th className="p-2">رقم العملية</th><th className="p-2">التاريخ والوقت</th><th className="p-2">المستخدم</th><th className="p-2">البيان</th><th className="p-2">الحركة</th></tr></thead><tbody>{visibleBalanceOps.map((op) => <tr key={op.id} className="border-b border-slate-100"><td className="p-2 font-mono">{op.number || "—"}</td><td className="p-2">{String(op.created_at || "").replace("T", " ").slice(0, 19)}</td><td className="p-2">{op.username || "—"}</td><td className="p-2">{op.description || "—"}</td><td className="p-2 num">{op.kind === "balance_transfer_out" ? `- ${fmt(op.amount)}` : `+ ${fmt(op.amount)}`}</td></tr>)}{!visibleBalanceOps.length && <tr><td colSpan={5} className="p-4 text-center text-slate-400">لا توجد حركات ضمن الفترة</td></tr>}</tbody></table></div></Card>}
    </>}
    <Dialog open={balanceOpen} onOpenChange={setBalanceOpen}><DialogContent><DialogHeader><DialogTitle>إضافة مبلغ إلى مخزون رصيد</DialogTitle></DialogHeader><div className="space-y-3"><div><Label>المبلغ</Label><Input type="number" min="0.01" value={balanceAmount} onChange={(e) => setBalanceAmount(e.target.value)} data-testid="balance-add-amount" /></div><div><Label>البيان</Label><Textarea value={balanceDescription} onChange={(e) => setBalanceDescription(e.target.value)} placeholder="مثال: تغذية مخزون الرصيد" /></div><Button onClick={addBalance} disabled={savingBalance} className="w-full bg-emerald-700" data-testid="balance-add-submit">{savingBalance ? "جاري الحفظ..." : "حفظ الإضافة"}</Button></div></DialogContent></Dialog>
  </div>;
}
