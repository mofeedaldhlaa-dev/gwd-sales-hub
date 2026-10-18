import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { CheckCircle, ChevronDown, Clock3, Copy, Landmark, WalletCards, Wifi, XCircle } from "lucide-react";
import { fmt, genUUID } from "@/lib/utils";
import PaymentAccountCard from "@/components/PaymentAccountCard";
import { fetchPortalPaymentAccounts, paymentInstructionImageUrl } from "@/lib/paymentAccounts";
import { DirectUpgradeCard, rememberDirectPurchase } from "@/components/DirectUpgradeCard";

let directPurchaseCatalogPromise = null;

const fetchDirectPurchaseCatalog = () => Promise.all([
  api.get("/public/card-order/categories"),
  fetchPortalPaymentAccounts(),
]).then(([cats, accounts]) => ({
  categories: Array.isArray(cats.data) ? cats.data : [],
  banks: accounts,
}));

export const prefetchDirectCardPurchaseCatalog = () => {
  if (!directPurchaseCatalogPromise) {
    directPurchaseCatalogPromise = fetchDirectPurchaseCatalog().catch((error) => {
      directPurchaseCatalogPromise = null;
      throw error;
    });
  }
  return directPurchaseCatalogPromise;
};

const normalizeReference = (value) => String(value || "").replace(/[\s٠-٩]/g, (char) => {
  const arabic = "٠١٢٣٤٥٦٧٨٩";
  return arabic.includes(char) ? String(arabic.indexOf(char)) : "";
}).toUpperCase();

const directErrorText = (error) => {
  const raw = String(error?.response?.data?.detail || error?.message || "").trim();
  if (/مستخدم من قبل|already used|duplicate/i.test(raw)) return "رقم العملية مستخدم من قبل";
  if (/حساب السداد غير متاح|bank account/i.test(raw)) return "حساب السداد غير متاح";
  if (/فئة الكرت غير موجودة|category/i.test(raw)) return "فئة الكرت غير متاحة";
  if (/مهلة|timeout|استجابة/i.test(raw)) return "انتهت المهلة، أعد المحاولة";
  if (/مرجع|reference/i.test(raw)) return "رقم المرجع غير صحيح";
  if (/مبلغ|amount/i.test(raw)) return "المبلغ غير مطابق";
  if (/كرت|stock|مخزون/i.test(raw)) return "الكرت غير متوفر";
  return raw.length > 72 ? `${raw.slice(0, 69)}...` : (raw || "تعذر تنفيذ العملية");
};

const directFailureText = (purchase) => {
  const code = String(purchase?.failure_code || "").toLowerCase();
  if (code === "reference_already_used") return "رقم العملية مستخدم من قبل";
  if (code === "reference_mismatch") return "رقم المرجع غير مطابق";
  if (code === "amount_mismatch") return "المبلغ غير مطابق لسعر الكرت";
  if (code === "gateway_response_timeout") return "انتهت المهلة، أعد المحاولة";
  if (code === "no_stock") return "لا يتوفر كرت من الفئة المختارة حالياً. حاول لاحقاً بنفس رقم العملية.";
  if (code === "posting_error") return "تعذر تسجيل العملية";
  if (code === "manual_review") return "العملية تحتاج مراجعة الإدارة";
  return directErrorText({ message: purchase?.failure_reason });
};

const isRetryableStockFailure = (purchase) => String(purchase?.failure_code || "").toLowerCase() === "no_stock";

const bankProviderLabel = (providerType) => providerType === "wallet" ? "محفظة إلكترونية" : "حساب بنكي";

export function DirectCardPurchaseFlow({ embedded = false, onLogin, onRegister }) {
  const [categories, setCategories] = useState([]);
  const [banks, setBanks] = useState([]);
  const [categoryId, setCategoryId] = useState("");
  const [bankId, setBankId] = useState("");
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [bankOpen, setBankOpen] = useState(false);
  const [instructionImageAccount, setInstructionImageAccount] = useState(null);
  const [paymentConfirmationOpen, setPaymentConfirmationOpen] = useState(false);
  const [reference, setReference] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [purchase, setPurchase] = useState(null);
  const [upgradeDismissed, setUpgradeDismissed] = useState(false);

  useEffect(() => {
    if (purchase?.status === "approved") rememberDirectPurchase(purchase.id);
  }, [purchase?.id, purchase?.status]);

  useEffect(() => {
    let cancelled = false;
    prefetchDirectCardPurchaseCatalog().then(({ categories: nextCategories, banks: nextBanks }) => {
      if (cancelled) return;
      setCategories(nextCategories);
      setBanks(nextBanks);
    }).catch((error) => {
      if (!cancelled) toast.error(directErrorText(error));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const refreshPurchase = async () => {
    if (!purchase?.id || refreshing) return;
    setRefreshing(true);
    try {
      const response = await api.get(`/public/net/purchase/${purchase.id}`);
      if (response.data) setPurchase(response.data);
    } catch (_) {
      toast.error("تعذر تحديث الحالة، أعد المحاولة");
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (!purchase?.id || ["approved", "rejected", "manual_review"].includes(purchase.status)) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await api.get(`/public/net/purchase/${purchase.id}`);
        if (!cancelled) {
          const next = response.data;
          if (!next) return;
          setPurchase(next);
          if (["approved", "rejected", "manual_review"].includes(next.status)) {
            toast.dismiss("direct-card-status");
            if (next.status === "approved") toast.success("تم شراء الكرت", { id: "direct-card-result-toast" });
            else toast.error(directFailureText(next), { id: "direct-card-result-toast" });
          }
        }
      } catch (_) { /* Gateway remains the source of truth. */ }
    };
    const timer = window.setInterval(poll, 3000);
    poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [purchase?.id, purchase?.status]);

  const selectedCategory = useMemo(() => categories.find((item) => item.id === categoryId), [categories, categoryId]);
  const selectedBank = useMemo(() => banks.find((item) => item.id === bankId), [banks, bankId]);
  const price = Number(selectedCategory?.sale_price_customer ?? selectedCategory?.sale_price ?? 0);

  const copy = async (value, message) => {
    try { await navigator.clipboard.writeText(String(value || "")); toast.success(message); }
    catch { toast.error("تعذر النسخ"); }
  };

  const submit = async (event) => {
    event.preventDefault();
    const normalized = normalizeReference(reference);
    if (!categoryId) { toast.error("اختر فئة الكرت"); return; }
    if (!bankId) { toast.error("اختر طريقة السداد"); return; }
    if (normalized.length < 6) { toast.error("رقم المرجع غير صحيح"); return; }
    setSubmitting(true);
    try {
      const response = await api.post("/public/net/purchase", {
        category_id: categoryId,
        bank_account_id: bankId,
        payment_reference: reference.trim(),
        idempotency_key: genUUID(),
      });
      const next = response.data || null;
      setPurchase(next);
      if (["approved", "rejected", "manual_review"].includes(next?.status)) {
        if (next.status === "approved") toast.success("تم شراء الكرت", { id: "direct-card-result-toast" });
        else toast.error(directFailureText(next), { id: "direct-card-result-toast" });
      }
    } catch (error) {
      toast.error(directErrorText(error));
    } finally { setSubmitting(false); }
  };

  const reset = () => {
    setPurchase(null);
    setReference("");
    setPaymentConfirmationOpen(false);
    setUpgradeDismissed(false);
  };
  const goLogin = () => { reset(); onLogin ? onLogin() : window.location.assign("/"); };
  const goRegister = () => { reset(); onRegister ? onRegister() : window.location.assign("/"); };
  const retryWithSameReference = () => {
    if (!isRetryableStockFailure(purchase)) return;
    setPurchase(null);
    setPaymentConfirmationOpen(true);
  };
  const chooseCategory = (id) => { setCategoryId(id); setCategoryOpen(false); };
  const chooseBank = (id) => {
    if (id !== bankId) setReference("");
    setBankId(id);
  };
  const confirmSelectedBank = (account) => {
    if (!categoryId) {
      toast.error("اختر فئة الكرت أولاً");
      return;
    }
    setBankId(account.id);
    setReference("");
    setPurchase(null);
    setPaymentConfirmationOpen(true);
    setBankOpen(false);
  };

  return (
    <div dir="rtl" className={`direct-card-purchase-flow ${embedded ? "is-embedded" : ""}`} data-testid="net-direct-flow">
      <header className="direct-card-purchase-header">
        <div className="direct-card-purchase-header-icon"><Wifi size={22} /></div>
        <div className="min-w-0 flex-1">
          <div className="direct-card-purchase-title">شراء كرت نت</div>
          <p>اختر الفئة والحساب، سدّد القيمة، ثم أدخل رقم مرجع العملية للتحقق الآلي.</p>
        </div>
      </header>
      <div className="direct-account-strip" data-testid="net-account-strip">
        <span>لديك حساب؟</span><button type="button" onClick={goLogin} data-testid="net-account-login">سجّل دخولك</button>
        <span>·</span><span>جديد؟</span><button type="button" onClick={goRegister} data-testid="net-account-register">أنشئ حساباً مجاناً</button>
      </div>

      {loading ? <div className="direct-card-purchase-loading">جارٍ تحميل الفئات وحسابات السداد...</div> : (
        <form className="direct-card-purchase-form" onSubmit={(event) => event.preventDefault()}>
          <div className="space-y-1.5">
            <Label className="font-black">اختر فئة الكرت</Label>
            <button type="button" onClick={() => setCategoryOpen(true)} className="direct-card-purchase-select" data-testid="net-category-select">
              <span className={selectedCategory ? "text-[#221340]" : "text-[#8B819A]"}>{selectedCategory ? `${selectedCategory.name} — ${fmt(price)} ريال` : "اختر فئة الكرت"}</span>
              <ChevronDown size={18} className="shrink-0 text-[#452480]" />
            </button>
          </div>

          {selectedCategory && <div className="direct-card-purchase-price" data-testid="net-selected-category"><span>المبلغ المطلوب</span><strong>{fmt(price)} ريال</strong></div>}

          <div className="space-y-1.5">
            <Label className="font-black">طريقة الدفع</Label>
            <button type="button" onClick={() => setBankOpen(true)} className="direct-card-purchase-select direct-card-payment-trigger" data-testid="net-bank-select">
              <span className={selectedBank ? "text-[#221340]" : "text-[#8B819A]"}>{selectedBank ? `${selectedBank.bank_name || "حساب السداد"} — ${bankProviderLabel(selectedBank.provider_type)}` : "اختر طريقة الدفع"}</span>
              <ChevronDown size={18} className="shrink-0 text-[#452480]" />
            </button>
          </div>

          {selectedBank && <div className="direct-card-purchase-bank" data-testid="net-selected-bank">
            <PaymentAccountCard
              account={selectedBank}
              onCopy={copy}
              onInstructionImage={(account) => { setInstructionImageAccount(account); }}
              selected
              numberCopyTestid="net-copy-account"
              showDetails
              detailsLabel="تعليمات السداد"
              testidPrefix="net-selected-bank-card"
            />
          </div>}
        </form>
      )}

      <Dialog open={categoryOpen} onOpenChange={setCategoryOpen}>
        <DialogContent dir="rtl" className="po-dialog-surface po-net-choice-dialog" data-testid="net-category-dialog">
          <DialogHeader className="po-net-choice-header"><DialogTitle className="flex items-center gap-2 text-right text-lg font-black text-[#221340]"><WalletCards size={20} className="text-[#452480]" /> اختر فئة الكرت</DialogTitle></DialogHeader>
          <div className="grid gap-2" data-testid="net-category-options">
            {categories.map((category) => {
              const categoryPrice = Number(category.sale_price_customer ?? category.sale_price ?? 0);
              const selected = category.id === categoryId;
              return <button type="button" key={category.id} onClick={() => chooseCategory(category.id)} className={`po-net-choice-option ${selected ? "is-selected" : ""}`} data-testid={`net-category-option-${category.id}`}>
                <span className="min-w-0 flex-1 text-right"><span className="block break-words whitespace-normal font-black leading-5">{category.name}</span><span className="mt-1 block break-words text-xs leading-5 text-[#6B5A80]">قيمة الكرت: {fmt(categoryPrice)} ريال</span></span>
                <span className={`po-net-choice-check ${selected ? "is-selected" : ""}`}>{selected ? "✓" : ""}</span>
              </button>;
            })}
            {!categories.length && <div className="rounded-2xl bg-[#F8F7FC] p-4 text-center text-sm text-[#6B5A80]">لا توجد فئات كروت متاحة حالياً</div>}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={bankOpen} onOpenChange={setBankOpen}>
        <DialogContent dir="rtl" className="po-dialog-surface po-net-choice-dialog" data-testid="net-bank-dialog">
          <DialogHeader className="po-net-choice-header"><DialogTitle className="flex items-center gap-2 text-right text-lg font-black text-[#221340]"><Landmark size={20} className="text-[#452480]" /> الحسابات البنكية وطرق السداد</DialogTitle></DialogHeader>
          <div className="grid gap-2" data-testid="net-bank-options">
            {banks.map((bank) => {
              const selected = bank.id === bankId;
              return <PaymentAccountCard key={bank.id} account={bank} onCopy={copy} onInstructionImage={(account) => { setBankOpen(false); setInstructionImageAccount(account); }} onCardSelect={() => chooseBank(bank.id)} onConfirm={confirmSelectedBank} selected={selected} showDetails detailsLabel="تعليمات السداد" testidPrefix="net-bank-option" confirmTestid={`net-confirm-payment-${bank.id}`} />;
            })}
            {!banks.length && <div className="rounded-2xl bg-[#F8F7FC] p-4 text-center text-sm leading-6 text-[#6B5A80]">لا توجد حسابات سداد مفعلة للشراء المباشر. فعّل «في بوابة العميل» للحساب المطلوب.</div>}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!instructionImageAccount} onOpenChange={(open) => { if (!open) setInstructionImageAccount(null); }}>
        <DialogContent dir="rtl" className="po-dialog-surface po-portal-scroll-dialog w-[calc(100vw-1rem)] max-w-2xl max-h-[calc(100dvh-1rem)] overflow-y-auto rounded-[1.5rem] bg-white p-4 sm:p-6" data-testid="net-payment-instruction-image-dialog">
          <DialogHeader>
            <DialogTitle className="text-[#221340]">تعليمات السداد — {instructionImageAccount?.bank_name || "الحساب"}</DialogTitle>
          </DialogHeader>
          {instructionImageAccount && <img src={paymentInstructionImageUrl(instructionImageAccount, "display")} alt={`تعليمات السداد ${instructionImageAccount.bank_name || ""}`} loading="eager" decoding="async" fetchPriority="high" width="800" height="800" className="max-h-[calc(100dvh-10rem)] w-full rounded-2xl border border-[#D9CBE8] bg-white object-contain p-2" data-testid="net-payment-instruction-image" />}
        </DialogContent>
      </Dialog>

      <Dialog open={paymentConfirmationOpen || !!purchase} onOpenChange={(open) => { if (!open) reset(); }}>
        <DialogContent dir="rtl" className="po-dialog-surface po-form-dialog po-portal-scroll-dialog w-[calc(100vw-1rem)] max-w-md max-h-[calc(100dvh-1rem)] overflow-y-auto rounded-[1.5rem] border-[#E5DDF0] bg-[#F8F7FC] p-4 sm:p-6" data-testid="net-payment-confirmation-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#221340]"><CheckCircle size={18} className="text-[#452480]" /> تأكيد عملية دفع</DialogTitle>
          </DialogHeader>
          <div data-testid="net-purchase-result-dialog" className="contents">
          {!purchase ? (
            <form onSubmit={submit} className="space-y-3" data-testid="net-payment-confirmation-form">
              <div className="space-y-1.5">
                <Label className="font-bold text-[#221340]">حساب السداد</Label>
                {selectedBank ? (
                  <div data-testid="net-payment-selected-bank">
                    <PaymentAccountCard
                      account={selectedBank}
                      onCopy={copy}
                      onInstructionImage={setInstructionImageAccount}
                      selected
                      showDetails
                      detailsLabel="تعليمات السداد"
                      numberCopyTestid="net-payment-selected-bank-number-copy"
                      testidPrefix="net-payment-selected-bank-card"
                    />
                  </div>
                ) : <div className="rounded-2xl border border-[#D9CBE8] bg-white px-3 py-3 text-sm font-black" data-testid="net-payment-selected-bank">لم يتم اختيار حساب السداد من بطاقته</div>}
              </div>
              <div className="space-y-1.5" data-testid="net-payment-selected-category">
                <Label className="font-bold text-[#221340]">فئة الكرت المختار</Label>
                <div className="flex items-center justify-between gap-3 rounded-2xl border border-[#DDD8E7] bg-white px-4 py-3">
                  <span className="min-w-0 break-words font-black text-[#221340]">{selectedCategory?.name || "غير محددة"}</span>
                  <strong className="shrink-0 text-[#452480]">{fmt(price)} ريال</strong>
                </div>
              </div>
              <div className="space-y-1.5" data-testid="net-payment-confirmation-fields">
                <Label className="font-bold text-[#221340]">رقم مرجع العملية</Label>
                <input value={reference} onChange={(event) => setReference(event.target.value)} inputMode="numeric" dir="ltr" maxLength={64} placeholder="ادخل رقم العملية او مرجع العملية" className="direct-card-purchase-input h-14 rounded-2xl border-[#DDD8E7] bg-white text-left shadow-none" data-testid="net-payment-reference" />
                <div className="text-[11px] leading-5 text-[#6B5A80]">أدخل رقم المرجع الظاهر في إشعار نجاح الإيداع كما هو.</div>
              </div>
              <Button type="submit" disabled={submitting || !banks.length || !categories.length} className="h-14 w-full rounded-2xl bg-[#452480] font-black text-white hover:bg-[#5A2FA0]" data-testid="net-submit">
                {submitting ? "جارٍ إرسال الطلب..." : "إرسال طلب التأكيد"}
              </Button>
            </form>
          ) : (
            <section className="space-y-3" data-testid="net-purchase-result" data-status={purchase.status}>
              {purchase.status === "approved" ? <div className="text-center"><CheckCircle size={52} className="mx-auto text-emerald-600" /><h2 className="mt-2 text-xl font-black text-emerald-800">تم الشراء بنجاح</h2><div className="mt-2 text-sm">الفئة: <strong>{purchase.category_name}</strong></div><div className="mt-1 text-sm">المبلغ: <strong>{fmt(purchase.amount)} ريال</strong></div><div className="mt-3 rounded-2xl bg-emerald-50 p-4"><div className="text-xs text-emerald-700">رقم الكرت</div><div dir="ltr" className="mt-1 break-all text-xl font-black text-emerald-900">{purchase.card_number}</div><Button type="button" onClick={() => copy(purchase.card_number, "تم نسخ رقم الكرت")} className="mt-3 h-11 w-full rounded-xl bg-emerald-600 font-black text-white hover:bg-emerald-700"><Copy size={15} className="ml-1" /> نسخ رقم الكرت</Button></div>{!upgradeDismissed && <DirectUpgradeCard onDismiss={() => setUpgradeDismissed(true)} onLogin={goLogin} />}</div>
                : ["rejected", "manual_review"].includes(purchase.status) ? <div className="text-center"><XCircle size={52} className="mx-auto text-red-600" /><h2 className="mt-2 text-xl font-black text-red-800">تعذر تنفيذ الشراء</h2><p className="mt-3 rounded-2xl bg-red-50 p-3 text-sm leading-6 text-red-800">{directFailureText(purchase)}</p>{isRetryableStockFailure(purchase) && <Button type="button" onClick={retryWithSameReference} className="mt-3 h-12 w-full rounded-2xl bg-[#452480] font-black text-white hover:bg-[#5A2FA0]" data-testid="net-purchase-retry-same-reference">إعادة المحاولة بنفس رقم العملية</Button>}</div>
                : <div className="po-payment-confirmation-pending rounded-2xl border border-[#D9CBE8] border-t-2 border-t-[#D4AF37] bg-white p-4 text-center" data-testid="net-purchase-pending" role="status" aria-live="polite"><Clock3 size={36} className="mx-auto mb-2 text-[#452480]" /><div className="font-black text-[#221340]">يرجى الانتظار، قيد التحقق</div></div>}
              {!['approved', 'rejected', 'manual_review'].includes(purchase.status) && <Button type="button" onClick={refreshPurchase} disabled={refreshing} variant="outline" className="w-full rounded-2xl border-[#3B82F6] text-[#245C9D]" data-testid="net-purchase-refresh"><Clock3 size={15} className="ml-1" /> {refreshing ? "جارٍ تحديث الحالة..." : "تحديث الحالة الآن"}</Button>}
              {["approved", "rejected", "manual_review"].includes(purchase.status) && !isRetryableStockFailure(purchase) && <Button type="button" onClick={reset} variant="outline" className="mt-4 h-11 w-full rounded-xl border-[#452480] font-black text-[#452480]" data-testid="net-purchase-new">شراء كرت آخر</Button>}
              {isRetryableStockFailure(purchase) && <Button type="button" onClick={reset} variant="outline" className="mt-2 h-11 w-full rounded-xl border-[#452480] font-black text-[#452480]" data-testid="net-purchase-new">بدء عملية أخرى</Button>}
            </section>
          )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function DirectCardPurchase() {
  return (
    <main className="min-h-screen bg-[#F8F7FC] px-3 py-5 text-[#221340] sm:px-6">
      <div className="mx-auto max-w-lg">
        <DirectCardPurchaseFlow />
      </div>
    </main>
  );
}
