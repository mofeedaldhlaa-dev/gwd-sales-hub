import { useEffect, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { Plus, RotateCcw, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { fmt, fmtDate } from "@/lib/utils";

export default function SalesReturns() {
  const [items, setItems] = useState([]); const [loading, setLoading] = useState(true);
  const load = async () => { setLoading(true); try { const r = await api.get("/sales-returns"); setItems(r.data || []); } catch (e) { toast.error(errText(e)); } finally { setLoading(false); } };
  useEffect(() => { load(); }, []);
  return <div className="space-y-4" data-testid="sales-returns-page"><div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><RotateCcw className="text-[#452480]" size={20}/><h1 className="text-xl font-bold text-[#221340]">مرتجع المبيعات</h1></div><div className="flex gap-2"><Button variant="outline" onClick={load}><RefreshCw size={14} className="ml-1"/> تحديث</Button><Link to="/sales-returns/new"><Button className="bg-[#221340]"><Plus size={15} className="ml-1"/> مرتجع مبيعات</Button></Link></div></div><Card className="p-3 text-sm text-slate-600">يسمح النظام بالمرتجع بدون فاتورة أصلية، مع فحص حالة الكروت أو الكمية قبل الحفظ. السجل غير قابل للحذف حفاظاً على الأثر المالي.</Card><Card className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-slate-50"><tr className="text-right"><th className="p-3">الرقم</th><th className="p-3">التاريخ</th><th className="p-3">العميل</th><th className="p-3">التسوية</th><th className="p-3">الأصناف</th><th className="p-3">الإجمالي</th><th className="p-3">المنشئ</th></tr></thead><tbody>{items.map((x) => <tr key={x.id} className="border-t border-slate-100"><td className="p-3 font-mono font-bold text-[#452480]">{x.number}</td><td className="p-3">{fmtDate(x.created_at)}</td><td className="p-3">{x.customer_name || "عميل نقدي"}</td><td className="p-3">{x.settlement_type === "cash" ? "صرف نقدي/بنكي" : "على حساب العميل"}</td><td className="p-3">{(x.items || []).map((i) => `${i.category_name} × ${i.quantity}`).join("، ")}</td><td className="p-3 num font-bold">{fmt(x.total)}</td><td className="p-3">{x.username || "—"}</td></tr>)}{!loading && items.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-slate-400">لا توجد مرتجعات مبيعات</td></tr>}{loading && <tr><td colSpan={7} className="p-8 text-center text-slate-400">جاري التحميل...</td></tr>}</tbody></table></Card></div>;
}
