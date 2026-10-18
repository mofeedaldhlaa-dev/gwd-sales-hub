import { useEffect, useMemo, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fmt } from "@/lib/utils";
import { toast } from "sonner";
import { Link, useNavigate } from "react-router-dom";
import { ShoppingCart, Users, CreditCard, FileBarChart, Wallet, Search, Zap, ArrowLeftRight, History, TrendingUp, Receipt, Boxes, Send, Store } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { genUUID } from "@/lib/utils";
import { SubscriberFavorites, ContactPickerButton } from "@/components/PhoneInputExtras";
import { saveOperationImage } from "@/lib/receiptImage";
import { Download } from "lucide-react";
import PeriodFilter from "@/components/PeriodFilter";

import { monthStartIso, todayIso, useAppDate } from "@/lib/DateService";
import { confirmDuplicateOperation, withDuplicateApproval } from "@/lib/duplicateOperation";
function QuickRechargeButton() {
  const [open, setOpen] = useState(false);
  const [recipientPhone, setRecipientPhone] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [amount, setAmount] = useState("");
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [lastOp, setLastOp] = useState(null);
  const [favoriteOffer, setFavoriteOffer] = useState(null);

  // history filters
  const [histPeriod, setHistPeriod] = useState("day");
  const [histStart, setHistStart] = useState(todayIso());
  const [histEnd, setHistEnd] = useState(todayIso());
  const [histSearch, setHistSearch] = useState("");

  const reset = () => { setRecipientPhone(""); setRecipientName(""); setAmount(""); setPreview(null); setLoading(false); setSubmitting(false); setShowHistory(false); setHistory([]); setLastOp(null); setFavoriteOffer(null); setHistPeriod("all"); setHistStart(""); setHistEnd(""); setHistSearch(""); };
  const onOpenChange = (v) => { if (!v) reset(); setOpen(v); };

  const loadHistory = async (ov) => {
    setHistoryLoading(true);
    try {
      const s = ov?.start ?? histStart;
      const e = ov?.end ?? histEnd;
      const body = {};
      if (s) body.start = s;
      if (e) body.end = e;
      const r = await api.post("/admin/quick-recharge/list", body);
      setHistory(r.data || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "تعذّر التحميل"); }
    setHistoryLoading(false);
  };
  const toggleHistory = async () => {
    const next = !showHistory;
    setShowHistory(next);
    if (next) await loadHistory();
  };

  // Live results based on selected period (re-fetch from backend with date range).
  const applyPeriod = ({ period, start, end }) => {
    setHistPeriod(period); setHistStart(start); setHistEnd(end);
    if (period === "custom" && (!start || !end || end < start)) { setHistory([]); return; }
    loadHistory({ start, end });
  };

  const historyFiltered = useMemo(() => {
    const q = (histSearch || "").trim().toLowerCase();
    if (!q) return history;
    return history.filter((op) => (op.party_name || "").toLowerCase().includes(q) || (op.number || "").toLowerCase().includes(q));
  }, [history, histSearch]);

  const doLookup = async () => {
    if (!recipientPhone.trim()) { toast.error("رقم هاتف المستلم مطلوب"); return; }
    const a = parseFloat(amount);
    if (!a || a <= 0) { toast.error("المبلغ غير صحيح"); return; }
    setLoading(true); setPreview(null);
    try {
      const r = await api.post("/admin/quick-recharge/lookup", { recipient_phone: recipientPhone.trim(), amount: a });
      setPreview(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || "تعذّر التحقق"); }
    setLoading(false);
  };
  const doConfirm = async () => {
    if (!preview) return;
    if (preview.balance_stock_sufficient === false) { toast.error("رصيد مخزون الرصيد غير كافٍ لإتمام العملية."); return; }
    setSubmitting(true);
    try {
      const body = {
        recipient_phone: recipientPhone.trim(), amount: preview.amount, idempotency_key: genUUID(),
      };
      let r;
      try {
        r = await api.post("/admin/quick-recharge/confirm", body);
      } catch (e) {
        const approved = await confirmDuplicateOperation(e);
        if (approved === null) throw e;
        if (!approved) return;
        r = await api.post("/admin/quick-recharge/confirm", withDuplicateApproval(body));
      }
      toast.success(`تم تحويل الرصيد بنجاح — عملية ${r.data.number}`);
      setLastOp({ ...r.data, recipient_phone: recipientPhone.trim(), recipient_type: preview.recipient_type });
      try {
        const favs = JSON.parse(localStorage.getItem("gwd_fav_subscribers") || "[]");
        const phone = recipientPhone.trim();
        if (phone && !favs.some((item) => item.phone === phone)) setFavoriteOffer({ phone, name: r.data.recipient_name || preview.recipient_name || recipientName || phone });
      } catch {}
      setPreview(null);
      if (showHistory) loadHistory();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل التنفيذ"); }
    setSubmitting(false);
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="quick-recharge"
        className="w-full h-[64px] flex flex-col items-center justify-center gap-1 p-1.5 bg-white border-2 border-[#D4AF37] rounded-xl hover:bg-[#D4AF37]/10 hover:shadow-md transition"
      >
        <Zap size={18} className="text-[#D4AF37]"/>
        <span className="text-xs font-bold text-[#221340] text-center leading-tight">تحويل رصيد</span>
      </button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-md" data-testid="qr-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2 text-[#221340]"><Zap size={18} className="text-[#D4AF37]"/> تحويل رصيد</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>رقم هاتف المستلم</Label>
              <div className="flex items-center gap-1">
                <Input
                  inputMode="tel"
                  value={recipientPhone}
                  onChange={(e) => { setRecipientPhone(e.target.value); setPreview(null); }}
                  placeholder="مثال: 7XXXXXXXX"
                  data-testid="qr-recipient"
                  className="flex-1"
                />
                <SubscriberFavorites
                  currentPhone={recipientPhone}
                  currentName={recipientName}
                  onPick={(f) => { setRecipientPhone(f.phone); setRecipientName(f.name); setPreview(null); }}
                  testidPrefix="qr-fav"
                />
                <ContactPickerButton
                  onPick={(c) => { setRecipientPhone(c.phone); setRecipientName(c.name || ""); setPreview(null); }}
                  testid="qr-contact-pick"
                />
              </div>
            </div>
            <div><Label>المبلغ</Label>
              <Input type="number" inputMode="decimal" value={amount} onChange={(e) => { setAmount(e.target.value); setPreview(null); }} data-testid="qr-amount"/>
            </div>
            {!preview && (
              <Button onClick={doLookup} disabled={loading} className="w-full bg-[#452480] hover:bg-[#5A2FA0]" data-testid="qr-lookup">
                <Search size={14} className="ml-1"/> {loading ? "جاري..." : "بحث"}
              </Button>
            )}
            {preview && (
              <div className="space-y-1.5 bg-emerald-50 border-2 border-emerald-300 rounded-lg p-3 text-sm" data-testid="qr-preview">
                <div className="flex justify-between"><span className="text-slate-600">المرسل:</span><span className="font-bold">{preview.sender_name}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">اسم المستلم:</span><span className="font-bold">{preview.recipient_name}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">رقم المستلم:</span><span className="font-mono">{preview.recipient_phone}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">نوع المستلم:</span><span>{preview.recipient_type === "pos" ? "نقطة بيع" : "عميل"}</span></div>
                <div className="border-t my-1"></div>
                <div className="flex justify-between font-bold"><span>مبلغ تحويل الرصيد:</span><span className="num">{fmt(preview.amount)}</span></div>
                <div className="flex justify-between text-emerald-700 font-bold"><span>المبلغ المستلم:</span><span className="num">{fmt(preview.recipient_credit)}</span></div>
                <div className="flex justify-between text-slate-500 text-xs"><span>العمولة:</span><span className="num">0</span></div>
                <div className={`flex justify-between text-xs font-bold ${preview.balance_stock_sufficient === false ? "text-red-700" : "text-slate-600"}`}><span>المتاح في مخزون رصيد:</span><span className="num">{fmt(preview.balance_stock)}</span></div>
                {preview.balance_stock_sufficient === false && <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">رصيد مخزون الرصيد غير كافٍ لإتمام العملية.</div>}
                <div className="flex justify-between font-black text-emerald-700 border-t pt-1"><span>الإضافة إلى الصندوق:</span><span className="num">{fmt(preview.amount)}</span></div>
              </div>
            )}
            <div className="pt-3 border-t">
              <button type="button" onClick={toggleHistory} className="w-full flex items-center justify-between text-sm font-bold text-[#221340]" data-testid="qr-history-toggle">
                <span className="flex items-center gap-2"><History size={14}/> العمليات السابقة</span>
                <span className="text-[#452480]">{showHistory ? "إخفاء" : "عرض"}</span>
              </button>
              {showHistory && (
                <div className="mt-2 space-y-2" data-testid="qr-history">
                  <div className="space-y-2 bg-slate-50 border rounded-lg p-2">
                    <PeriodFilter period={histPeriod} start={histStart} end={histEnd} onChange={applyPeriod} testidPrefix="qr-hist-period" />
                    <div className="relative">
                      <Search size={13} className="absolute right-2 top-3 text-slate-400"/>
                      <Input className="pr-7 h-9" placeholder="بحث بالاسم أو رقم العملية..." value={histSearch} onChange={(e) => setHistSearch(e.target.value)} data-testid="qr-hist-search"/>
                    </div>
                  </div>
                  <div className="text-[11px] text-slate-500" data-testid="qr-hist-count">عدد النتائج: <strong>{historyFiltered.length}</strong></div>
                  <div className="space-y-2 max-h-72 overflow-y-auto">
                    {historyLoading && <div className="text-center text-xs text-slate-400 py-3">جاري التحميل...</div>}
                    {!historyLoading && historyFiltered.length === 0 && <div className="text-center text-xs text-slate-400 py-3">لا توجد عمليات ضمن الفترة</div>}
                    {historyFiltered.map((op) => (
                      <div key={op.id} className="border rounded-lg p-2 bg-white text-sm" data-testid={`qr-history-${op.id}`}>
                        <div className="flex justify-between items-start gap-2">
                          <div className="min-w-0">
                            <div className="font-mono font-bold text-[#452480]">{op.number}</div>
                            <div className="text-[10px] text-slate-500">{(op.created_at || "").replace("T", " ").slice(0, 16)}</div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <Button size="sm" variant="outline" onClick={() => saveOperationImage({
                              kind: "quick-recharge",
                              number: op.number,
                              createdAt: op.created_at,
                              senderName: "شبكة جواد نت اللاسلكية",
                              recipientName: op.party_name,
                              amount: op.amount,
                              recipientCredit: op.amount,
                              description: op.description,
                            })} className="h-7 px-2 text-xs" data-testid={`qr-history-save-${op.id}`}>
                              <Download size={10} className="ml-1"/> حفظ
                            </Button>
                            <span className="text-[10px] font-bold rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-800">تحويل رصيد</span>
                          </div>
                        </div>
                        <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
                          <div><div className="text-slate-500">المستلم</div><div className="font-bold truncate">{op.party_name}</div></div>
                          <div><div className="text-slate-500">المبلغ</div><div className="num font-bold text-emerald-700">{fmt(op.amount)}</div></div>
                          {op.username && <div className="col-span-2 text-[10px] text-slate-400">بواسطة: {op.username}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          {preview && (
            <DialogFooter className="gap-2 pt-2">
              <Button onClick={() => setPreview(null)} variant="outline" data-testid="qr-back">تعديل</Button>
                <Button onClick={doConfirm} disabled={submitting || preview.balance_stock_sufficient === false} className="bg-emerald-600 hover:bg-emerald-700" data-testid="qr-confirm">
                <ArrowLeftRight size={14} className="ml-1"/> {submitting ? "جاري..." : "تأكيد تحويل الرصيد"}
              </Button>
            </DialogFooter>
          )}
          {lastOp && (
            <div className="space-y-2 bg-emerald-50 border-2 border-emerald-300 rounded-lg p-3 text-sm" data-testid="qr-success">
              <div className="text-center font-black text-emerald-800">تمت العملية بنجاح</div>
              <div className="flex justify-between text-xs"><span className="text-slate-600">رقم العملية:</span><span className="font-mono font-bold">{lastOp.number}</span></div>
              <div className="flex justify-between text-xs"><span className="text-slate-600">المستلم:</span><span className="font-bold">{lastOp.party_name}</span></div>
              <div className="flex justify-between text-xs"><span className="text-slate-600">المبلغ:</span><span className="font-bold num">{fmt(lastOp.amount)}</span></div>
              <div className="grid grid-cols-2 gap-2 pt-1">
                <Button size="sm" onClick={() => saveOperationImage({
                  kind: "quick-recharge",
                  number: lastOp.number,
                  createdAt: lastOp.created_at,
                  senderName: "شبكة جواد نت اللاسلكية",
                  recipientName: lastOp.party_name,
                  recipientPhone: lastOp.recipient_phone,
                  recipientType: lastOp.recipient_type,
                  amount: lastOp.amount,
                  recipientCredit: lastOp.amount,
                  description: lastOp.description,
                })} className="bg-[#452480] hover:bg-[#5A2FA0]" data-testid="qr-save-image">
                  <Download size={12} className="ml-1"/> حفظ الإشعار كصورة
                </Button>
                <Button size="sm" variant="outline" onClick={() => setLastOp(null)} data-testid="qr-new">عملية جديدة</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={!!favoriteOffer} onOpenChange={(value) => !value && setFavoriteOffer(null)}>
        <DialogContent className="max-w-sm" data-testid="qr-favorite-offer">
          <DialogHeader><DialogTitle>حفظ المستلم في المفضلة</DialogTitle></DialogHeader>
          <div className="space-y-3 text-center text-sm">
            <div>تم تحويل الرصيد بنجاح.</div>
            <div>هل تريد إضافة الرقم إلى المفضلة لاستخدامه لاحقاً؟</div>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="font-bold" data-testid="qr-favorite-offer-name">اسم الحساب: {favoriteOffer?.name || "غير متوفر"}</div>
              <div className="font-mono mt-1" dir="ltr">{favoriteOffer?.phone}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button onClick={() => { try { const favs = JSON.parse(localStorage.getItem("gwd_fav_subscribers") || "[]"); localStorage.setItem("gwd_fav_subscribers", JSON.stringify([...favs, favoriteOffer])); window.dispatchEvent(new Event("favorites-changed")); toast.success("تم حفظ الرقم في المفضلة"); } catch { toast.error("تعذر حفظ الرقم"); } setFavoriteOffer(null); }} className="bg-[#452480]" data-testid="qr-favorite-offer-confirm">نعم، حفظ الرقم</Button>
              <Button variant="outline" onClick={() => setFavoriteOffer(null)} data-testid="qr-favorite-offer-cancel">ليس الآن</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

const Stat = ({ label, value, sub, tone = "light", testid, icon: Icon, to }) => {
  const styles = {
    purple: "bg-[#221340] text-white",
    gold: "bg-[#D4AF37] text-[#1A0F33]",
    light: "bg-white text-[#221340] border border-slate-200",
  }[tone];
  const iconWrap = {
    purple: "bg-white/10 text-[#D4AF37]",
    gold: "bg-[#1A0F33]/15 text-[#1A0F33]",
    light: "bg-[#452480]/10 text-[#452480]",
  }[tone];
  const card = <Card className={`dash-stat-card ${styles} p-2 md:p-4 rounded-2xl shadow-sm transition duration-200 hover:shadow-md hover:-translate-y-0.5`} data-testid={testid}>
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0 flex-1"><div className="dash-stat-label text-xs font-medium opacity-80">{label}</div><div className="dash-stat-value num mt-1" dir="ltr" data-testid={testid ? `${testid}-value` : undefined}>{value}</div>{sub && <div className="text-xs opacity-70 mt-1">{sub}</div>}</div>
      {Icon && <span className={`shrink-0 w-7 h-7 rounded-xl flex items-center justify-center ${iconWrap}`}><Icon size={18} /></span>}
    </div>
  </Card>;
  return to ? <Link to={to} className="block rounded-2xl focus:outline-none focus:ring-2 focus:ring-[#D4AF37]" aria-label={label}>{card}</Link> : card;
};

const SectionTitle = ({ children, icon: Icon }) => (
  <div className="flex items-center gap-2 mb-1.5">
    {Icon && <span className="w-5 h-5 rounded-lg bg-[#452480]/10 text-[#452480] flex items-center justify-center"><Icon size={13} /></span>}
    <h2 className="text-sm md:text-base font-bold text-[#221340]">{children}</h2>
  </div>
);

// Shortcut tile — identical size/shape for every shortcut.
const Quick = ({ to, label, icon: Icon, testid, accent }) => (
  <Link to={to} data-testid={testid}
    className={`w-full h-[64px] flex flex-col items-center justify-center gap-1 p-1.5 bg-white border-2 rounded-xl hover:shadow-md transition ${accent || "border-slate-200 hover:border-[#D4AF37]"}`}>
    <Icon size={18} className="text-[#452480]" />
    <span className="text-xs font-bold text-[#221340] text-center leading-tight">{label}</span>
  </Link>
);


function QuickSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setRes(null); setBusy(false); return undefined; }
    setBusy(true);
    const timer = setTimeout(() => {
      api.get("/search", { params: { q: term } })
        .then((r) => setRes(r.data || {}))
        .catch(() => setRes(null))
        .finally(() => setBusy(false));
    }, 350);
    return () => clearTimeout(timer);
  }, [q]);

  const groups = useMemo(() => {
    if (!res) return [];
    const out = [];
    const push = (label, items, map) => {
      const mapped = (items || []).slice(0, 5).map(map);
      if (mapped.length) out.push({ label, items: mapped });
    };
    push("حسابات العملاء", res.customers, (c) => ({
      id: c.id, title: c.name, sub: c.phone,
      to: c.customer_type === "pos" ? `/accounts/pos/${c.id}` : `/accounts/customer/${c.id}`,
    }));
    push("الموردون", res.suppliers, (c) => ({ id: c.id, title: c.name, sub: c.phone, to: "/accounts?type=supplier" }));
    push("فواتير البيع", res.sales, (x) => ({ id: x.id, title: x.number, sub: `${x.customer_name || ""} • ${fmt(x.total)}`, to: `/sales/${x.id}/edit` }));
    push("فواتير المشتريات", res.purchases, (x) => ({ id: x.id, title: x.number, sub: `${x.supplier_name || ""} • ${fmt(x.total)}`, to: `/purchases/${x.id}/edit` }));
    push("السندات", res.receipts, (x) => ({ id: x.id, title: x.number, sub: `${x.party_name || ""} • ${fmt(x.amount)}`, to: `/receipts?focus=${x.id}` }));
    push("التحويلات", res.transfers, (x) => ({ id: x.id, title: x.number || x.reference || "-", sub: `${x.source_name || ""} ← ${x.dest_name || ""}`, to: `/transfers?focus=${x.id}` }));
    push("الكروت المجانية", res.free_cards, (x) => ({ id: x.id, title: x.number || "-", sub: `${x.recipient_name || x.recipient_phone || ""} • ${x.card_number || ""}`, to: `/free-cards?focus=${x.id}` }));
    push("كروت المخزون", res.cards, (x) => ({ id: x.id, title: x.number, sub: x.category_name || "", to: `/stock?category=${x.category_id || ""}` }));
    return out;
  }, [res]);

  const go = (to) => { setOpen(false); setQ(""); setRes(null); navigate(to); };
  const total = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <section data-testid="dash-quick-search" className="relative">
      <div className="flex items-center gap-2 rounded-2xl bg-white border border-slate-200 px-2.5 py-1.5 shadow-sm">
        <Search size={16} className="text-[#452480] shrink-0" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder="بحث سريع: اسم الحساب / رقم الهاتف / رقم العملية"
          className="w-full bg-transparent text-sm outline-none py-0.5"
          data-testid="quick-search-input"
        />
        {busy && <span className="text-[11px] text-slate-400 shrink-0">...</span>}
        {!!q && <button onClick={() => { setQ(""); setRes(null); }} className="text-slate-400 shrink-0" data-testid="quick-search-clear">×</button>}
      </div>
      {open && q.trim().length >= 2 && (
        <div className="absolute z-30 mt-1 w-full max-h-[60vh] overflow-auto rounded-2xl bg-white border border-slate-200 shadow-lg p-1.5" data-testid="quick-search-results">
          {!total && <div className="p-3 text-center text-xs text-slate-400">{busy ? "جاري البحث..." : "لا توجد نتائج"}</div>}
          {groups.map((g) => (
            <div key={g.label} className="mb-1">
              <div className="px-2 py-1 text-[11px] font-bold text-slate-500">{g.label}</div>
              {g.items.map((it) => (
                <button key={`${g.label}-${it.id}`} onClick={() => go(it.to)}
                  className="w-full text-right flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg hover:bg-[#452480]/5"
                  data-testid={`quick-result-${it.id}`}>
                  <span className="text-sm font-semibold text-[#221340] truncate">{it.title}</span>
                  <span className="text-[11px] text-slate-500 truncate">{it.sub}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Dashboard() {
  const [d, setD] = useState(null);
  const [loadError, setLoadError] = useState("");
  const { selectedDate } = useAppDate();
  useEffect(() => {
    let active = true;
    setD(null);
    setLoadError("");
    api.get("/reports/dashboard", { params: { date: selectedDate } })
      .then((r) => { if (active) setD(r.data); })
      .catch((error) => { if (active) setLoadError(errText(error)); });
    return () => { active = false; };
  }, [selectedDate]);

  return (
    <div className="space-y-2 sm:space-y-3" data-testid="dashboard">
      <QuickSearch />
      {/* 1) Overview KPIs — at the TOP, prominent */}
      <section data-testid="dash-overview" className="rounded-2xl bg-gradient-to-l from-[#221340] to-[#452480] p-2.5 md:p-4 shadow-md">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="w-7 h-7 rounded-lg bg-[#D4AF37] text-[#1A0F33] flex items-center justify-center"><TrendingUp size={16} /></span>
          <h2 className="text-base md:text-lg font-extrabold text-white">نظرة عامة</h2>
        </div>
        {loadError ? (
          <div className="p-6 text-center text-red-200">{loadError}</div>
        ) : !d ? (
          <div className="p-6 text-center text-white/70">جاري التحميل...</div>
        ) : (
          <div className="dash-overview-grid grid gap-2">
            <Stat to="/sales?period=day" testid="stat-sales-today" label="مبيعات اليوم" value={fmt(d.sales_today)} tone="gold" icon={ShoppingCart} />
            <Stat to="/sales?period=month" testid="stat-sales-month" label="مبيعات الشهر" value={fmt(d.sales_month)} tone="light" icon={TrendingUp} />
            <Stat to="/accounts?type=customer" testid="stat-cust-debts" label="ديون العملاء" value={fmt(d.customer_debts)} tone="light" icon={Users} />
            <Stat to="/accounts?type=pos" testid="stat-pos-debts" label="ديون نقاط البيع" value={fmt(d.pos_debts)} tone="light" icon={Store} />
          </div>
        )}
      </section>



      {/* 2) Quick shortcuts */}
      <section data-testid="dash-shortcuts">
        <SectionTitle icon={Zap}>الاختصارات السريعة</SectionTitle>
        <Card className="p-2 rounded-2xl">
          <div className="grid grid-cols-2 gap-2">
            <QuickRechargeButton />
            <Quick to="/accounts/cash/cash" label="صندوق النقدية" icon={Wallet} testid="quick-cashbox" accent="border-emerald-400 hover:border-emerald-500 hover:bg-emerald-50" />
            <Quick to="/accounts" label="الحسابات" icon={Users} testid="quick-accounts" accent="border-[#452480]/40 hover:border-[#452480] hover:bg-[#452480]/5" />
            <Quick to="/sales" label="المبيعات" icon={ShoppingCart} testid="quick-sales" />
            <Quick to="/receipts" label="السندات" icon={Receipt} testid="quick-receipts" />
            <Quick to="/stock" label="المخزون" icon={Boxes} testid="quick-stock" />
            <Quick to="/message-center" label="الرسائل والإشعارات" icon={Send} testid="quick-message-center" accent="border-[#D4AF37]/50 hover:border-[#D4AF37] hover:bg-[#D4AF37]/10" />
            <Quick to="/reports" label="التقارير" icon={FileBarChart} testid="quick-reports" />
          </div>
        </Card>
      </section>
    </div>
  );
}
