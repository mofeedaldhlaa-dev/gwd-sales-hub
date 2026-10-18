import { useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { CheckCircle, History, Sparkles, Tag, WalletCards } from "lucide-react";

const STORAGE_KEY = "gawad_direct_purchase_ids";
const PHONE_RE = /^7[0-9]{8}$/;

export const rememberDirectPurchase = (id) => {
  if (!id) return;
  try {
    const list = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (!list.includes(id)) localStorage.setItem(STORAGE_KEY, JSON.stringify([...list, id].slice(-50)));
  } catch { /* storage unavailable */ }
};

const storedPurchaseIds = () => {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch { return []; }
};

const PERKS = [
  { icon: History, text: "سجل كامل لكل كروتك، ومنها هذا الكرت" },
  { icon: WalletCards, text: "شحن رصيد وتحويل لمشترك آخر" },
  { icon: Tag, text: "أسعار وعروض خاصة للمشتركين" },
];

export function DirectUpgradeCard({ onDismiss, onLogin }) {
  const [form, setForm] = useState({ full_name: "", phone: "", address: "" });
  const [loading, setLoading] = useState(false);
  const [state, setState] = useState("form");
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    const name = form.full_name.trim();
    const phone = form.phone.replace(/\D/g, "").replace(/^(00967|967)/, "");
    if (name.split(/\s+/).length < 2) { toast.error("الرجاء إدخال الاسم الرباعي كاملاً"); return; }
    if (!PHONE_RE.test(phone)) { toast.error("أدخل رقم هاتف يمني صحيحاً من 9 أرقام"); return; }
    if (!form.address.trim()) { toast.error("العنوان مطلوب"); return; }
    setLoading(true);
    try {
      await api.post("/public/customer/register-request", { full_name: name, phone, address: form.address.trim(), account_type: "customer", direct_purchase_ids: storedPurchaseIds() });
      setState("sent");
    } catch (error) {
      const detail = String(error?.response?.data?.detail || "");
      if (/مرتبط بحساب/.test(detail)) setState("exists");
      else toast.error(detail || "تعذر إرسال الطلب");
    } finally { setLoading(false); }
  };

  if (state === "sent") return (
    <div className="direct-upgrade-card is-done" data-testid="direct-upgrade-success">
      <CheckCircle size={30} className="mx-auto text-emerald-600" />
      <div className="mt-2 font-black text-[#221340]">تم إرسال طلب إنشاء حسابك</div>
      <p className="mt-1 text-xs leading-6 text-[#6B5A80]">ستصلك بيانات الدخول بعد موافقة الإدارة، وكروتك المشتراة ستظهر في سجلك تلقائياً.</p>
    </div>
  );

  if (state === "exists") return (
    <div className="direct-upgrade-card is-done" data-testid="direct-upgrade-exists">
      <div className="font-black text-[#221340]">هذا الرقم لديه حساب بالفعل</div>
      {onLogin && <Button type="button" onClick={onLogin} className="mt-3 h-11 w-full rounded-xl bg-[#452480] font-black text-white hover:bg-[#5A2FA0]" data-testid="direct-upgrade-login">سجّل دخولك</Button>}
    </div>
  );

  return (
    <form onSubmit={submit} className="direct-upgrade-card" data-testid="direct-upgrade-card">
      <div className="flex items-center gap-2 font-black text-[#221340]"><Sparkles size={18} className="text-[#D4AF37]" /> احفظ مشترياتك في حساب خاص بك</div>
      <p className="mt-1 text-xs text-[#6B5A80]">طلب واحد سريع، وبدون أي رسوم</p>
      <ul className="mt-3 space-y-1.5">
        {PERKS.map(({ icon: Icon, text }) => <li key={text} className="flex items-center gap-2 text-xs font-bold text-[#3B2A5C]"><Icon size={14} className="shrink-0 text-[#452480]" />{text}</li>)}
      </ul>
      <div className="mt-3 space-y-2">
        <input value={form.full_name} onChange={set("full_name")} placeholder="الاسم الرباعي" className="direct-upgrade-input" data-testid="direct-upgrade-name" />
        <input value={form.phone} onChange={set("phone")} inputMode="numeric" dir="ltr" maxLength={14} placeholder="7XXXXXXXX" className="direct-upgrade-input text-left" data-testid="direct-upgrade-phone" />
        <input value={form.address} onChange={set("address")} placeholder="العنوان: المدينة، الحي" className="direct-upgrade-input" data-testid="direct-upgrade-address" />
      </div>
      <Button type="submit" disabled={loading} className="mt-3 h-12 w-full rounded-xl bg-[#452480] font-black text-white hover:bg-[#5A2FA0]" data-testid="direct-upgrade-submit">{loading ? "جارٍ الإرسال..." : "إنشاء حسابي الآن"}</Button>
      <button type="button" onClick={onDismiss} className="mt-2 w-full text-xs font-bold text-[#8B819A] hover:text-[#452480]" data-testid="direct-upgrade-later">لاحقاً</button>
    </form>
  );
}
