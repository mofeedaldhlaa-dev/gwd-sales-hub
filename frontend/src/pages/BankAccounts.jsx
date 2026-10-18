import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { apiUrl } from "@/lib/apiConfig";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Landmark, Plus, Edit, Trash2, Power, PowerOff, Search, WalletCards } from "lucide-react";

const SHOW_IN_OPTIONS = [
  { key: "portal", label: "في بوابة العميل" },
  { key: "invoices", label: "أسفل الفواتير" },
  { key: "receipts", label: "أسفل السندات" },
  { key: "payment_requests", label: "في طلبات السداد" },
  { key: "over_limit", label: "إشعارات تجاوز السقف وطلبات السداد" },
];

const PROVIDER_OPTIONS = [
  { key: "bank", label: "حساب بنكي" },
  { key: "wallet", label: "محفظة إلكترونية" },
];

const EMPTY = {
  bank_name: "",
  holder_name: "",
  account_number: "",
  provider_type: "bank",
  details: "",
  instruction_image_file_id: null,
  active: true,
  show_in: [],
  gateway_sender_ids: [],
  gateway_sender_ids_text: "",
};

const providerLabel = (value) => PROVIDER_OPTIONS.find((item) => item.key === value)?.label || "حساب بنكي";

export default function BankAccounts() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState(null);
  const [query, setQuery] = useState("");
  const [instructionImageFile, setInstructionImageFile] = useState(null);
  const [instructionImagePreview, setInstructionImagePreview] = useState("");

  const load = async () => {
    try {
      const response = await api.get("/bank-accounts");
      setItems(Array.isArray(response.data) ? response.data : []);
    } catch (e) {
      toast.error(errText(e));
    }
  };

  useEffect(() => { load(); }, []);

  const filteredItems = useMemo(() => {
    const needle = String(query || "").trim().toLocaleLowerCase("ar");
    if (!needle) return items;
    return items.filter((item) => [
      item.bank_name,
      item.holder_name,
      item.account_number,
      item.details,
      providerLabel(item.provider_type),
    ].some((value) => String(value || "").toLocaleLowerCase("ar").includes(needle)));
  }, [items, query]);

  const startEdit = (bank) => {
    setEditId(bank.id);
    setForm({ ...EMPTY, ...bank, provider_type: bank.provider_type || "bank", show_in: bank.show_in || [], gateway_sender_ids: bank.gateway_sender_ids || [], gateway_sender_ids_text: (bank.gateway_sender_ids || []).join(", ") });
    setInstructionImageFile(null);
    setInstructionImagePreview(bank.instruction_image_path ? apiUrl(bank.instruction_image_path) : "");
    setOpen(true);
  };

  const startNew = () => {
    setEditId(null);
    setForm({ ...EMPTY, show_in: [] });
    setInstructionImageFile(null);
    setInstructionImagePreview("");
    setOpen(true);
  };

  const selectInstructionImage = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!String(file.type || "").startsWith("image/")) {
      toast.error("اختر ملف صورة فقط");
      event.target.value = "";
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error("حجم الصورة يجب ألا يتجاوز 10 ميجابايت");
      event.target.value = "";
      return;
    }
    setInstructionImageFile(file);
    setInstructionImagePreview(URL.createObjectURL(file));
  };

  const toggleShow = (key) => setForm((current) => {
    const next = new Set(current.show_in || []);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return { ...current, show_in: Array.from(next) };
  });

  const save = async () => {
    if (!form.bank_name.trim() || !form.holder_name.trim() || !form.account_number.trim()) {
      toast.error("أدخل اسم الجهة واسم صاحب الحساب ورقم الحساب");
      return;
    }
    try {
      const payload = { ...form, gateway_sender_ids: String(form.gateway_sender_ids_text || "").split(",").map((value) => value.trim()).filter(Boolean).slice(0, 20) };
      delete payload.gateway_sender_ids_text;
      let saved;
      if (editId) saved = (await api.put(`/bank-accounts/${editId}`, payload)).data;
      else saved = (await api.post("/bank-accounts", payload)).data;
      if (instructionImageFile && saved?.id) {
        const body = new FormData();
        body.append("file", instructionImageFile);
        await api.post(`/bank-accounts/${saved.id}/instruction-image`, body, { __skipIdempotency: true, __skipOfflineQueue: true, timeout: 120_000 });
      }
      toast.success(instructionImageFile ? "تم حفظ الحساب وصورة تعليمات السداد" : "تم حفظ بيانات الحساب البنكي");
      setOpen(false);
      await load();
    } catch (e) {
      toast.error(errText(e));
    }
  };

  const remove = async (bank) => {
    if (!window.confirm("هل أنت متأكد من حذف هذا الحساب البنكي؟ لا يمكن التراجع عن الحذف.")) return;
    try {
      await api.delete(`/bank-accounts/${bank.id}`);
      toast.success("تم حذف الحساب البنكي");
      await load();
    } catch (e) {
      toast.error(errText(e));
    }
  };

  const toggleActive = async (bank) => {
    try {
      await api.put(`/bank-accounts/${bank.id}`, { ...bank, active: !bank.active });
      toast.success(bank.active ? "تم تعطيل الحساب البنكي" : "تم تفعيل الحساب البنكي");
      await load();
    } catch (e) {
      toast.error(errText(e));
    }
  };

  return (
    <div className="space-y-4" data-testid="banks-page">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-[#221340] font-bold text-lg">
          <Landmark size={20} /> الحسابات البنكية وطرق السداد
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-[#221340]" onClick={startNew} data-testid="bank-add">
              <Plus size={16} className="ml-1" /> إضافة حساب
            </Button>
          </DialogTrigger>
          <DialogContent dir="rtl">
            <DialogHeader>
              <DialogTitle>{editId ? "تعديل حساب بنكي" : "إضافة حساب بنكي أو محفظة"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>نوع الجهة *</Label>
                <select
                  value={form.provider_type}
                  onChange={(event) => setForm({ ...form, provider_type: event.target.value })}
                  className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-[#452480]"
                  data-testid="bank-provider-type"
                >
                  {PROVIDER_OPTIONS.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
                </select>
              </div>
              <div>
                <Label>اسم البنك أو المحفظة *</Label>
                <Input value={form.bank_name} onChange={(event) => setForm({ ...form, bank_name: event.target.value })} data-testid="bank-name" />
              </div>
              <div>
                <Label>اسم الحساب / صاحب الحساب *</Label>
                <Input value={form.holder_name} onChange={(event) => setForm({ ...form, holder_name: event.target.value })} data-testid="bank-holder" />
              </div>
              <div>
                <Label>رقم الحساب أو رقم المحفظة *</Label>
                <Input value={form.account_number} onChange={(event) => setForm({ ...form, account_number: event.target.value })} data-testid="bank-number" className="font-mono" dir="ltr" />
              </div>
              <div>
                <Label>تعليمات السداد والتفاصيل</Label>
                <Textarea value={form.details} onChange={(event) => setForm({ ...form, details: event.target.value })} placeholder="الفرع، طريقة التحويل، أو أي تعليمات تظهر للعميل..." data-testid="bank-details" />
              </div>
              <div className="space-y-2 rounded-xl border border-[#D9CBE8] bg-[#F8F7FC] p-3" data-testid="bank-instruction-image-field">
                <Label>صورة تعليمات السداد</Label>
                <input type="file" accept="image/*" onChange={selectInstructionImage} className="block w-full text-xs" data-testid="bank-instruction-image-input" />
                <div className="text-[11px] leading-5 text-slate-500">يمكن للعميل فتح الصورة من بطاقة الحساب لمعاينة خطوات السداد. الحد الأقصى 10 ميجابايت.</div>
                {instructionImagePreview && <img src={instructionImagePreview} alt="معاينة صورة تعليمات السداد" className="max-h-48 w-full rounded-xl border border-slate-200 bg-white object-contain p-1" data-testid="bank-instruction-image-preview" />}
              </div>
              <div>
                <Label>معرّفات مرسل SMS الرسمية</Label>
                <Input value={form.gateway_sender_ids_text || ""} onChange={(event) => setForm({ ...form, gateway_sender_ids_text: event.target.value })} placeholder="مثال: AlKuraimi, ONECASH" data-testid="bank-gateway-senders" dir="ltr" />
                <div className="mt-1 text-[11px] leading-5 text-slate-500">اكتب المعرفات الرسمية مفصولة بفواصل فقط. لا تضف أرقاماً شخصية؛ الرسائل غير المدرجة تُرفض.</div>
              </div>
              <div>
                <Label>أماكن ظهور بيانات الحساب</Label>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {SHOW_IN_OPTIONS.map((option) => (
                    <label key={option.key} className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${form.show_in?.includes(option.key) ? "border-[#452480] bg-[#452480]/10" : "border-slate-200"}`}>
                      <input type="checkbox" checked={form.show_in?.includes(option.key) || false} onChange={() => toggleShow(option.key)} data-testid={`bank-show-${option.key}`} />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} data-testid="bank-active" />
                <span>الحساب مفعّل</span>
              </label>
              <Button onClick={save} className="w-full bg-[#221340]" data-testid="bank-save">حفظ البيانات</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs leading-5 text-slate-500">فعّل خيار «في بوابة العميل» حتى يظهر الحساب داخل أيقونة الحساب في البوابة.</div>
        <div className="relative w-full sm:max-w-xs">
          <Search size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="بحث في الحسابات البنكية" className="pr-9" data-testid="bank-search" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {filteredItems.map((bank) => (
          <Card key={bank.id} className={`po-payment-account-card p-4 ${!bank.active ? "bg-slate-50 opacity-60" : ""}`} data-testid={`bank-row-${bank.id}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="font-bold text-[#221340] text-base">{bank.bank_name}</div>
                  <span className="inline-flex items-center gap-1 rounded-full bg-[#452480]/10 px-2 py-0.5 text-[10px] font-bold text-[#452480]"><WalletCards size={11} />{providerLabel(bank.provider_type)}</span>
                  {!bank.active && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-600">معطّل</span>}
                </div>
                <div className="mt-1 text-sm text-slate-600">{bank.holder_name}</div>
                <div className="mt-1 break-all font-mono text-sm" dir="ltr" data-testid={`bank-num-${bank.id}`}>{bank.account_number}</div>
                {bank.cashbox_id && <Link to={`/accounts/cashbox/${bank.cashbox_id}`} className="mt-2 inline-flex max-w-full items-center rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-bold text-emerald-700 hover:bg-emerald-100" data-testid={`bank-cashbox-${bank.id}`}>الصندوق المرتبط: {bank.cashbox_name || "فتح الصندوق"}</Link>}
                {bank.details && <div className="mt-1 whitespace-pre-line text-xs text-slate-500">{bank.details}</div>}
                <div className="mt-2 flex flex-wrap gap-1">
                  {(bank.show_in || []).map((showIn) => (
                    <span key={showIn} className={`rounded-full px-2 py-0.5 text-[10px] ${showIn === "portal" ? "bg-emerald-100 text-emerald-700" : "bg-[#452480]/10 text-[#452480]"}`}>
                      {SHOW_IN_OPTIONS.find((option) => option.key === showIn)?.label || showIn}
                    </span>
                  ))}
                  {(!bank.show_in || bank.show_in.length === 0) && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700">لا يظهر في أي مكان</span>}
                </div>
              </div>
              <div className="flex shrink-0 flex-col gap-1">
                <Button size="sm" variant="outline" onClick={() => startEdit(bank)} data-testid={`bank-edit-${bank.id}`}><Edit size={12} /></Button>
                <Button size="sm" variant="outline" onClick={() => toggleActive(bank)} data-testid={`bank-toggle-${bank.id}`} title={bank.active ? "تعطيل" : "تفعيل"}>
                  {bank.active ? <PowerOff size={12} className="text-red-600" /> : <Power size={12} className="text-green-600" />}
                </Button>
                <Button size="sm" variant="outline" onClick={() => remove(bank)} data-testid={`bank-delete-${bank.id}`} className="border-red-300"><Trash2 size={12} className="text-red-600" /></Button>
              </div>
            </div>
          </Card>
        ))}
        {filteredItems.length === 0 && <div className="col-span-full p-8 text-center text-slate-400">{items.length ? "لا توجد نتائج مطابقة للبحث" : "لا توجد حسابات بنكية — أضف حساباً أعلاه"}</div>}
      </div>
    </div>
  );
}

export { PROVIDER_OPTIONS, SHOW_IN_OPTIONS };
