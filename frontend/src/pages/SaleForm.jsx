import { useEffect, useRef, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { fmt, genUUID, deviceId } from "@/lib/utils";
import { Plus, Trash2, Save, RefreshCw, X } from "lucide-react";
import { queueOperation, isOnline } from "@/lib/offline";
import { confirmDuplicateOperation, withDuplicateApproval } from "@/lib/duplicateOperation";

const isBalanceCategory = (category) => category?.kind === "balance" || category?.name === "رصيد";
const numbersOf = (text) => String(text || "").split(/\s+/).map((n) => n.trim()).filter(Boolean);

export default function SaleForm() {
  const nav = useNavigate();
  const { id: editId } = useParams();
  const [searchParams] = useSearchParams();
  const prefillCustomer = searchParams.get("customer");
  const isEdit = !!editId;

  const [cats, setCats] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState(searchParams.get("customer") || "");
  const [customerQuery, setCustomerQuery] = useState("");
  const [saleType, setSaleType] = useState("");
  const [items, setItems] = useState([{ category_id: "", quantity: 1, price: 0, use_numbered: false, card_numbers_text: "" }]);
  const [catCards, setCatCards] = useState({});   // { category_id: { available, numbers[] } }
  const [catLoading, setCatLoading] = useState({});
  const itemsRef = useRef(items);
  useEffect(() => { itemsRef.current = items; }, [items]);
  const [discount, setDiscount] = useState(0);
  const [paid, setPaid] = useState(0);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [origNumber, setOrigNumber] = useState("");
  useEffect(() => { api.get("/categories").then((r) => setCats((r.data || []).filter((category) => !isBalanceCategory(category)))); }, []);
  useEffect(() => {
    const timer = setTimeout(() => {
      api.get("/customers", { params: { q: customerQuery.trim() || prefillCustomer || undefined, limit: 100 } })
        .then((r) => setCustomers(Array.isArray(r.data) ? r.data : []))
        .catch(() => setCustomers([]));
    }, customerQuery.trim() ? 250 : 0);
    return () => clearTimeout(timer);
  }, [customerQuery, prefillCustomer]);

  // Prefill customer from URL when adding a new invoice from within account details
  useEffect(() => {
    if (isEdit) return;
    if (prefillCustomer && customers.length && !customerId) {
      const exists = customers.find((c) => c.id === prefillCustomer);
      if (exists) {
        setCustomerId(prefillCustomer);
        setSaleType((prev) => prev || "credit");
      }
    }
  }, [prefillCustomer, customers, isEdit]);

  useEffect(() => {
    if (!isEdit) return;
    api.get(`/sales/${editId}`).then((r) => {
      const s = r.data;
      setOrigNumber(s.number || "");
      setCustomerId(s.customer_id || "");
      setSaleType(s.sale_type || "credit");
      setDiscount(s.discount || 0);
      setPaid(s.paid || 0);
      setNotes(s.notes || "");
      setItems((s.items || []).map((it) => ({
        category_id: it.category_id, quantity: it.quantity, price: it.price,
        use_numbered: !!it.use_numbered,
        card_numbers_text: (it.card_numbers || []).join("\n"),
      })));
    }).catch((e) => { toast.error(errText(e)); nav("/sales"); });
  }, [editId]);

  // Available numbered cards for one category (oldest first, ready for auto-fill).
  const loadAvailable = async (categoryId) => {
    if (!categoryId) return [];
    setCatLoading((s) => ({ ...s, [categoryId]: true }));
    try {
      const r = await api.get("/sales/available-card-numbers", { params: { category_id: categoryId } });
      const numbers = (r.data?.numbers || []).map((n) => String(n).trim()).filter(Boolean);
      const available = Number(r.data?.available ?? numbers.length) || 0;
      setCatCards((s) => ({ ...s, [categoryId]: { available, numbers } }));
      return numbers;
    } catch (e) {
      toast.error(errText(e) || "تعذر جلب الكروت المتاحة");
      return null;
    } finally {
      setCatLoading((s) => ({ ...s, [categoryId]: false }));
    }
  };

  // Fill the item with the oldest available cards of its category (quantity driven).
  const fillItem = async (index, { reset = false, refetch = true, quantity = null } = {}) => {
    const current = itemsRef.current[index];
    if (!current || !current.use_numbered || !current.category_id) return;
    const qty = Math.max(1, Number(quantity !== null && quantity !== "" ? quantity : current.quantity) || 1);
    let list = (!refetch && catCards[current.category_id]) ? catCards[current.category_id].numbers : await loadAvailable(current.category_id);
    if (!list) return;
    const snapshot = itemsRef.current;
    const others = new Set(snapshot.flatMap((x, i) => (i === index || !x.use_numbered ? [] : numbersOf(x.card_numbers_text))));
    const free = list.filter((n) => !others.has(n));
    const keep = reset ? [] : numbersOf(current.card_numbers_text).filter((n) => list.includes(n) && !others.has(n));
    const picked = Array.from(new Set([...keep, ...free])).slice(0, qty);
    setItems((prev) => {
      const next = prev.map((x, i) => (i === index ? { ...x, card_numbers_text: picked.join("\n") } : x));
      itemsRef.current = next;
      return next;
    });
    if (picked.length < qty) {
      const name = cats.find((c) => c.id === current.category_id)?.name || "الفئة";
      toast.warning(`المتاح ${picked.length} كرت فقط من ${name} — المطلوب ${qty}. عدّل الكمية أو أضف كروتاً للفئة.`);
    }
  };

  const updateItem = (i, key, val) => {
    const copy = [...items];
    copy[i] = { ...copy[i], [key]: val };
    if (key === "category_id") {
      const cat = cats.find((c) => c.id === val);
      const cust = customers.find((c) => c.id === customerId);
      if (cat) {
        const p = cust?.customer_type === "pos"
          ? (cat.sale_price_pos ?? cat.sale_price)
          : (cat.sale_price_customer ?? cat.sale_price);
        copy[i].price = p || 0;
      }
      if (copy[i].use_numbered) copy[i].card_numbers_text = "";
    }
    itemsRef.current = copy;
    setItems(copy);
    if (copy[i].use_numbered && (key === "category_id" || key === "quantity")) {
      const index = i;
      const reset = key === "category_id";
      const quantity = key === "quantity" ? val : null;
      setTimeout(() => { fillItem(index, { reset, refetch: true, quantity }); }, 0);
    }
  };
  const addItem = () => setItems([...items, { category_id: "", quantity: 1, price: 0, use_numbered: false, card_numbers_text: "" }]);
  const removeItem = (i) => setItems(items.filter((_, x) => x !== i));

  const subtotal = items.reduce((s, i) => s + (Number(i.quantity) || 0) * (Number(i.price) || 0), 0);
  const total = subtotal - (Number(discount) || 0);
  const effectivePaid = saleType === "cash" ? total : Math.min(Math.max(Number(paid) || 0, 0), total);
  const remaining = saleType === "cash" ? 0 : Math.max(total - effectivePaid, 0);
  const customer = customers.find((c) => c.id === customerId);

  const payload = () => ({
    customer_id: customerId || null,
    customer_name: customer?.name || "",
    sale_type: saleType,
    items: items.map((i) => ({
      category_id: i.category_id, quantity: Number(i.quantity), price: Number(i.price),
      category_name: cats.find(c => c.id === i.category_id)?.name || "",
      use_numbered: i.use_numbered,
      card_numbers: i.use_numbered ? numbersOf(i.card_numbers_text) : [],
    })),
    discount: Number(discount) || 0, paid: effectivePaid, notes,
  });

  const validate = () => {
    if (!customerId) { toast.error("يرجى اختيار العميل قبل حفظ الفاتورة."); return false; }
    if (!saleType) { toast.error("يرجى اختيار نوع الفاتورة: نقد أو آجل."); return false; }
    if (items.some((i) => !i.category_id || !i.quantity)) { toast.error("أكمل بيانات الأصناف"); return false; }
    for (let i = 0; i < items.length; i += 1) {
      const it = items[i];
      if (!it.use_numbered) continue;
      const nums = numbersOf(it.card_numbers_text);
      if (nums.length !== Number(it.quantity)) {
        toast.error(`البند ${i + 1}: عدد أرقام الكروت (${nums.length}) يجب أن يساوي الكمية (${it.quantity}).`);
        return false;
      }
      if (new Set(nums).size !== nums.length) {
        toast.error(`البند ${i + 1}: توجد أرقام كروت مكررة.`);
        return false;
      }
    }
    return true;
  };

  const submitCreate = async () => {
    setLoading(true);
    try {
      const body = { ...payload(), idempotency_key: genUUID(), local_operation_id: genUUID(), device_id: deviceId() };
      if (!isOnline()) {
        await queueOperation({ endpoint: "/sales", payload: body, local_id: body.local_operation_id, idempotency_key: body.idempotency_key, device_id: body.device_id });
        toast.success("تم حفظ العملية بنجاح. لا يوجد اتصال بالإنترانت حالياً، وستتم المزامنة تلقائياً عند عودة الاتصال.");
        nav(searchParams.get("returnAccount") || "/sales"); return;
      }
      let r;
      try {
        r = await api.post("/sales", body);
      } catch (e) {
        const approved = await confirmDuplicateOperation(e);
        if (approved === null) throw e;
        if (!approved) return;
        r = await api.post("/sales", withDuplicateApproval(body));
      }
      toast.success(r.status === 202 ? "تم حفظ العملية محلياً وستتم مزامنتها تلقائياً عند عودة الاتصال" : "تم الحفظ بنجاح");
      nav(searchParams.get("returnAccount") || "/sales", { state: { savedInvoice: { ...r.data, account_phone: customer?.phone || "" } } });
    } catch (e) { toast.error(errText(e)); }
    finally { setLoading(false); }
  };

  const submitEdit = async () => {
    setConfirmOpen(false);
    setLoading(true);
    try {
      const r = await api.put(`/sales/${editId}`, payload());
      toast.success("تم الحفظ بنجاح");
      nav(searchParams.get("returnAccount") || "/sales", { state: { savedInvoice: { ...r.data, account_phone: customer?.phone || "" } } });
    } catch (e) { toast.error(errText(e)); }
    setLoading(false);
  };

  const submit = () => {
    if (!validate()) return;
    if (isEdit) setConfirmOpen(true);
    else submitCreate();
  };

  return (
    <div className="space-y-4 max-w-4xl" data-testid="sale-form">
      <Card className="p-4 md:p-6 space-y-4">
        {isEdit && (
          <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm">
            وضع التعديل — الفاتورة رقم <span className="font-mono font-bold text-[#452480]" data-testid="sale-edit-number">{origNumber}</span>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <Label>العميل *</Label>
            <Input value={customerQuery} onChange={(e) => setCustomerQuery(e.target.value)} placeholder="بحث باسم العميل..." className="mb-2" data-testid="sale-customer-search" />
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger data-testid="sale-customer"><SelectValue placeholder="اختر العميل" /></SelectTrigger>
              <SelectContent>{customers.filter((c) => !customerQuery.trim() || `${c.name || ""} ${c.phone || ""}`.toLowerCase().includes(customerQuery.trim().toLowerCase())).slice(0, 100).map((c) => <SelectItem key={c.id} value={c.id}>{c.name} {c.phone ? `— ${c.phone}` : ""} {c.customer_type ? `— ${c.customer_type === "pos" ? "نقطة بيع" : "عميل"}` : ""} {c.balance !== undefined ? `— الرصيد: ${fmt(c.balance)}` : ""}</SelectItem>)}</SelectContent>
            </Select>
            {customer && <div className="text-xs text-slate-500 mt-1">المديونية: <span className="num">{fmt(customer.balance)}</span> | المتاح: <span className="num">{fmt(Math.max(0, (customer.credit_limit || 0) - (customer.balance || 0)))}</span></div>}
          </div>
          <div>
            <Label>نوع الفاتورة *</Label>
            <Select value={saleType} onValueChange={(value) => { setSaleType(value); if (value === "cash") setPaid(0); }}>
              <SelectTrigger data-testid="sale-type"><SelectValue placeholder="اختر النوع" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cash">نقد</SelectItem>
                <SelectItem value="credit">آجل</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between items-center"><div className="font-bold">الأصناف</div><Button size="sm" onClick={addItem} data-testid="add-item"><Plus size={14}/> صنف</Button></div>
          {items.map((it, i) => {
            const nums = numbersOf(it.card_numbers_text);
            const qty = Math.max(1, Number(it.quantity) || 1);
            const info = catCards[it.category_id];
            const busy = !!catLoading[it.category_id];
            return (
              <Card key={i} className="p-3 bg-slate-50">
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-2">
                  <div className="sm:col-span-2 md:col-span-1">
                    <Select value={it.category_id} onValueChange={(v) => updateItem(i, "category_id", v)}>
                      <SelectTrigger data-testid={`item-cat-${i}`}><SelectValue placeholder="الفئة" /></SelectTrigger>
                      <SelectContent>{cats.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <Input type="number" placeholder="الكمية" value={it.quantity} onChange={(e) => updateItem(i, "quantity", e.target.value)} data-testid={`item-qty-${i}`} />
                  <Input type="number" placeholder="السعر" value={it.price} onChange={(e) => updateItem(i, "price", e.target.value)} data-testid={`item-price-${i}`} />
                  <div className="text-sm num flex items-center px-2 bg-white rounded border h-10">{fmt(it.quantity * it.price)}</div>
                  <Button variant="ghost" size="sm" onClick={() => removeItem(i)} className="justify-self-start sm:justify-self-auto"><Trash2 size={16} className="text-red-500" /> <span className="sm:hidden mr-1">حذف</span></Button>
                </div>
                <div className="mt-2 text-xs space-y-2">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={it.use_numbered} onChange={(e) => {
                      const checked = e.target.checked;
                      const copy = [...items];
                      copy[i] = { ...copy[i], use_numbered: checked };
                      itemsRef.current = copy;
                      setItems(copy);
                      if (checked) setTimeout(() => { fillItem(i, { reset: true, refetch: true, quantity: copy[i].quantity }); }, 0);
                    }} data-testid={`item-numbered-${i}`} />
                    استخدام كروت مرقمة (تعبئة تلقائية من المتاح)
                  </label>
                  {it.use_numbered && (
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-slate-500">
                          المتاح: <b className="num text-[#452480]" data-testid={`item-cards-available-${i}`}>{info ? info.available : (it.category_id ? "..." : "—")}</b> كرت
                        </span>
                        <span className={nums.length === qty ? "text-emerald-600" : "text-amber-600"} data-testid={`item-cards-count-${i}`}>
                          المحدد: {nums.length} / {qty}
                        </span>
                        <Button type="button" size="sm" variant="outline" disabled={busy || !it.category_id}
                          onClick={() => fillItem(i, { reset: false, refetch: true })} data-testid={`item-cards-refresh-${i}`}>
                          <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> {busy ? "جاري التحديث" : "تحديث من المتاح"}
                        </Button>
                      </div>
                      {nums.length > 0 && (
                        <div className="flex flex-wrap gap-1" data-testid={`item-cards-chips-${i}`}>
                          {nums.map((n) => (
                            <span key={n} className="inline-flex items-center gap-1 rounded-full bg-white border border-[#D9CBE8] px-2 py-0.5 font-mono text-[11px]">
                              {n}
                              <button type="button" className="text-red-500" title="إزالة"
                                onClick={() => updateItem(i, "card_numbers_text", nums.filter((x) => x !== n).join("\n"))}>
                                <X size={11} />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      <Textarea rows={3} value={it.card_numbers_text || ""} onChange={(e) => updateItem(i, "card_numbers_text", e.target.value)}
                        placeholder="أرقام الكروت (كل رقم سطر) — تُعبّأ تلقائياً ويمكن تعديلها يدوياً" className="mt-1 font-mono text-xs" data-testid={`item-cards-text-${i}`} />
                    </>
                  )}
                </div>
              </Card>
            );
          })}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div><Label>الخصم</Label><Input type="number" value={discount} onChange={(e) => setDiscount(e.target.value)} data-testid="sale-discount" /></div>
          <div><Label>المدفوع</Label><Input type="number" value={saleType === "cash" ? total : paid} onChange={(e) => setPaid(e.target.value)} disabled={saleType === "cash"} data-testid="sale-paid" /></div>
          <div><Label>الإجمالي</Label><div className="h-10 flex items-center px-3 bg-slate-100 rounded num font-bold">{fmt(total)}</div></div>
          <div><Label>المتبقي</Label><div className="h-10 flex items-center px-3 bg-slate-100 rounded num font-bold">{fmt(remaining)}</div></div>
        </div>
        <Textarea placeholder="ملاحظات" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex gap-2 flex-wrap">
          <Button onClick={submit} disabled={loading} className="bg-[#221340] w-full sm:w-auto" data-testid="sale-save"><Save size={16} className="ml-1"/> {loading ? "جاري..." : (isEdit ? "حفظ التعديل" : "حفظ الفاتورة")}</Button>
        </div>
      </Card>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>تأكيد حفظ تعديلات الفاتورة {origNumber}</AlertDialogTitle>
            <AlertDialogDescription>
              سيؤدي حفظ التعديل إلى تحديث المخزون ورصيد الحساب والمديونية وإجمالي المبيعات
              والأرباح والتقارير المرتبطة بالفاتورة. لا يتراجع النظام تلقائياً بعد الحفظ.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="sale-edit-cancel">إلغاء</AlertDialogCancel>
            <AlertDialogAction onClick={submitEdit} className="bg-[#221340]" data-testid="sale-edit-confirm">تأكيد وحفظ</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
