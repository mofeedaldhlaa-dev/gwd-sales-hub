import { useEffect, useMemo, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { fmt, genUUID } from "@/lib/utils";

const emptyItem = () => ({ category_id: "", quantity: 1, price: 0, use_numbered: false, card_numbers_text: "" });

export default function SalesReturnForm() {
  const nav = useNavigate();
  const [cats, setCats] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [banks, setBanks] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [settlementType, setSettlementType] = useState("cash");
  const [bankId, setBankId] = useState("");
  const [items, setItems] = useState([emptyItem()]);
  const [notes, setNotes] = useState("");
  const [managerApproved, setManagerApproved] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.allSettled([api.get("/categories"), api.get("/customers"), api.get("/bank-accounts")]).then(([c, u, b]) => {
      if (c.status === "fulfilled") setCats((c.value.data || []).filter((x) => x.kind !== "balance" && x.name !== "رصيد"));
      if (u.status === "fulfilled") setCustomers(u.value.data || []);
      if (b.status === "fulfilled") setBanks((b.value.data || []).filter((x) => x.active !== false));
    });
  }, []);
  const update = (index, key, value) => setItems((old) => old.map((item, i) => i === index ? { ...item, [key]: value } : item));
  const chooseCategory = (index, value) => {
    const cat = cats.find((x) => x.id === value);
    setItems((old) => old.map((item, i) => i === index ? { ...item, category_id: value, price: cat?.sale_price || cat?.sale_price_customer || cat?.value || 0 } : item));
  };
  const total = useMemo(() => items.reduce((sum, item) => {
    const quantity = item.use_numbered ? (item.card_numbers_text || "").split(/\s+/).filter(Boolean).length : Number(item.quantity || 0);
    return sum + quantity * Number(item.price || 0);
  }, 0), [items]);
  const submit = async () => {
    if (!items.every((x) => x.category_id && Number(x.price) > 0)) { toast.error("أكمل الفئة والسعر لكل بند"); return; }
    if (settlementType === "customer_balance" && !customerId) { toast.error("اختر العميل للتسوية على الحساب"); return; }
    if (settlementType === "cash" && !bankId) { toast.error("اختر الحساب النقدي أو البنكي"); return; }
    const body = {
      customer_id: customerId || null,
      settlement_type: settlementType,
      bank_account_id: settlementType === "cash" ? bankId : null,
      items: items.map((item) => {
        const nums = (item.card_numbers_text || "").split(/\s+/).map((x) => x.trim()).filter(Boolean);
        return { category_id: item.category_id, quantity: item.use_numbered ? nums.length : Number(item.quantity), price: Number(item.price), card_numbers: item.use_numbered ? nums : [], use_numbered: item.use_numbered };
      }),
      notes, manager_approved: managerApproved, idempotency_key: genUUID(),
    };
    setLoading(true);
    try { await api.post("/sales-returns", body); toast.success("تم حفظ مرتجع المبيعات وتحديث المخزون"); nav("/sales-returns"); }
    catch (e) { toast.error(errText(e)); }
    finally { setLoading(false); }
  };
  return <div className="max-w-4xl space-y-4" data-testid="sales-return-form">
    <div className="flex items-center gap-2"><Link to="/sales-returns"><Button variant="ghost" size="sm"><ArrowRight size={16}/></Button></Link><h1 className="text-xl font-bold text-[#221340]">مرتجع مبيعات</h1></div>
    <Card className="p-4 md:p-6 space-y-4">
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">يمكن تسجيل المرتجع بدون فاتورة أصلية. سيُفحص توفر الكرت أو الكمية قبل اعتماد العملية، ولا يمكن حذف المرتجع بعد حفظه.</div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div><Label>العميل (اختياري للنقدي)</Label><Select value={customerId} onValueChange={setCustomerId}><SelectTrigger data-testid="sales-return-customer"><SelectValue placeholder="اختر العميل"/></SelectTrigger><SelectContent>{customers.map((x) => <SelectItem key={x.id} value={x.id}>{x.name} {x.phone ? `— ${x.phone}` : ""}</SelectItem>)}</SelectContent></Select></div>
        <div><Label>طريقة التسوية</Label><Select value={settlementType} onValueChange={setSettlementType}><SelectTrigger data-testid="sales-return-settlement"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="cash">صرف من حساب نقدي/بنكي</SelectItem><SelectItem value="customer_balance">تسوية على حساب العميل</SelectItem></SelectContent></Select></div>
        {settlementType === "cash" && <div><Label>حساب الصرف *</Label><Select value={bankId} onValueChange={setBankId}><SelectTrigger data-testid="sales-return-bank"><SelectValue placeholder="اختر الحساب"/></SelectTrigger><SelectContent>{banks.map((x) => <SelectItem key={x.id} value={x.id}>{x.bank_name} — {x.account_number}</SelectItem>)}</SelectContent></Select></div>}
      </div>
      <div className="space-y-2"><div className="flex items-center justify-between"><div className="font-bold">الأصناف المرتجعة</div><Button size="sm" variant="outline" onClick={() => setItems((old) => [...old, emptyItem()])}><Plus size={14} className="ml-1"/> إضافة بند</Button></div>
        {items.map((item, index) => <Card key={index} className="p-3 bg-slate-50"><div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2"><Select value={item.category_id} onValueChange={(v) => chooseCategory(index, v)}><SelectTrigger data-testid={`sales-return-category-${index}`}><SelectValue placeholder="الفئة"/></SelectTrigger><SelectContent>{cats.map((x) => <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>)}</SelectContent></Select><Input type="number" min="1" value={item.quantity} disabled={item.use_numbered} onChange={(e) => update(index, "quantity", e.target.value)} placeholder="الكمية"/><Input type="number" min="0" value={item.price} onChange={(e) => update(index, "price", e.target.value)} placeholder="سعر البيع"/><Button variant="ghost" onClick={() => setItems((old) => old.length > 1 ? old.filter((_, i) => i !== index) : old)}><Trash2 size={15} className="text-red-600"/></Button></div><label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={item.use_numbered} onChange={(e) => update(index, "use_numbered", e.target.checked)}/> مرتجع كروت مرقمة</label>{item.use_numbered && <Textarea rows={3} value={item.card_numbers_text} onChange={(e) => update(index, "card_numbers_text", e.target.value)} placeholder="ألصق أرقام الكروت، كل رقم في سطر" className="mt-2 font-mono text-xs"/>}</Card>)}
      </div>
      <div className="flex items-center justify-between border-t pt-3"><span className="font-bold">إجمالي المرتجع</span><span className="num text-xl font-black text-[#452480]">{fmt(total)}</span></div>
      <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="بيان المرتجع (اختياري)"/>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={managerApproved} onChange={(e) => setManagerApproved(e.target.checked)}/> تمت مراجعة المرتجع من المدير (اختياري)</label>
      <Button onClick={submit} disabled={loading} className="bg-[#221340] w-full sm:w-auto"><RotateCcw size={16} className="ml-1"/> {loading ? "جاري الحفظ..." : "اعتماد مرتجع المبيعات"}<Save size={15} className="mr-1"/></Button>
    </Card>
  </div>;
}
