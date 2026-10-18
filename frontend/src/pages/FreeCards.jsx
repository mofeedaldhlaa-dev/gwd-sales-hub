import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { fmt, fmtDate, openSMS, openWhatsAppUrl } from "@/lib/utils";
import PeriodFilter, { PERIOD_LABELS } from "@/components/PeriodFilter";
import { todayIso } from "@/lib/DateService";
import { Gift, Search, Send, RefreshCw, Archive, MessageCircle, Smartphone, BellRing, CheckCircle2, Printer } from "lucide-react";
import { printReport } from "@/lib/print";
import { useAuth } from "@/lib/auth";

const METHOD_LABELS = { in_app: "إشعار داخل نافذة الحساب", sms: "رسالة نصية", whatsapp: "رسالة واتساب" };
const METHOD_ICONS = { in_app: BellRing, sms: Smartphone, whatsapp: MessageCircle };

export default function FreeCards() {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const focusId = params.get("focus") || "";
  const [tab, setTab] = useState(focusId ? "archive" : "send");

  // ---------- send form state ----------
  const [cats, setCats] = useState([]);
  const [catId, setCatId] = useState("");
  const [cards, setCards] = useState([]);
  const [cardsInfo, setCardsInfo] = useState({ available: 0, category_name: "" });
  const [cardId, setCardId] = useState("");
  const [cardQuery, setCardQuery] = useState("");
  const [loadingCards, setLoadingCards] = useState(false);
  const [recipientMode, setRecipientMode] = useState("customer");
  const [custQuery, setCustQuery] = useState("");
  const [custResults, setCustResults] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [manualName, setManualName] = useState("");
  const [manualPhone, setManualPhone] = useState("");
  const [method, setMethod] = useState("in_app");
  const [templateText, setTemplateText] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  // ---------- archive state ----------
  const [period, setPeriod] = useState("day");
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso());
  const [archiveQuery, setArchiveQuery] = useState("");
  const [archiveMethod, setArchiveMethod] = useState("all");
  const [archive, setArchive] = useState({ items: [], summary: { count: 0, in_app: 0, sms: 0, whatsapp: 0, amount: 0 } });
  const [loadingArchive, setLoadingArchive] = useState(false);

  const loadCategories = useCallback(async () => {
    try {
      const r = await api.get("/free-cards/categories");
      setCats(r.data || []);
      if (!catId && (r.data || []).length) setCatId(r.data[0].id);
    } catch (e) { toast.error(errText(e)); }
  }, [catId]);

  const loadTemplate = useCallback(async () => {
    try {
      const r = await api.get("/message-templates");
      const tpl = (r.data || []).find((t) => t.key === "free_card_send");
      setTemplateText((tpl && tpl.text) || "");
    } catch { /* template is optional */ }
  }, []);

  const loadCards = useCallback(async (categoryId, q) => {
    if (!categoryId) { setCards([]); return; }
    setLoadingCards(true);
    try {
      const r = await api.get("/free-cards/available", { params: { category_id: categoryId, q: q || undefined } });
      setCards(r.data.cards || []);
      setCardsInfo({ available: r.data.available || 0, category_name: r.data.category_name || "" });
    } catch (e) { toast.error(errText(e)); }
    finally { setLoadingCards(false); }
  }, []);

  useEffect(() => { loadCategories(); loadTemplate(); }, [loadCategories, loadTemplate]);
  useEffect(() => { setCardId(""); setCardQuery(""); loadCards(catId, ""); }, [catId, loadCards]);

  useEffect(() => {
    if (recipientMode !== "customer") return;
    const term = custQuery.trim();
    if (term.length < 2) { setCustResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await api.get("/customers", { params: { q: term, limit: 20 } });
        setCustResults(r.data || []);
      } catch { setCustResults([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [custQuery, recipientMode]);

  const loadArchive = useCallback(async () => {
    setLoadingArchive(true);
    try {
      const r = await api.get("/free-cards/archive", {
        params: {
          start, end,
          q: archiveQuery.trim() || undefined,
          method: archiveMethod === "all" ? undefined : archiveMethod,
          limit: 1000,
        },
      });
      setArchive({ items: r.data.items || [], summary: r.data.summary || { count: 0, in_app: 0, sms: 0, whatsapp: 0, amount: 0 } });
    } catch (e) { toast.error(errText(e)); }
    finally { setLoadingArchive(false); }
  }, [start, end, archiveQuery, archiveMethod]);

  useEffect(() => { if (tab === "archive") loadArchive(); }, [tab, loadArchive]);

  // Print exactly what the archive shows right now (period + search + method).
  const printArchive = () => {
    const rows = (archive.items || []).map((r) => [
      fmtDate(r.created_at), r.number || "-", r.category_name || "-", r.card_number || "-",
      r.recipient_name || "-", r.recipient_phone || "-", fmt(r.amount || 0),
      METHOD_LABELS[r.method] || r.method || "-", r.username || "-",
    ]);
    printReport({
      title: `أرشيف الكروت المجانية — ${periodLabel}${archiveQuery ? ` — بحث: ${archiveQuery}` : ""}${archiveMethod !== "all" ? ` — ${METHOD_LABELS[archiveMethod]}` : ""}`,
      headers: ["التاريخ", "رقم العملية", "الفئة", "رقم الكرت", "المستلم", "الهاتف", "قيمة الكرت", "طريقة الإرسال", "الموظف"],
      rows,
      totals: [
        { label: "عدد العمليات المطبوعة", value: rows.length },
        { label: "إجمالي مبلغ الكروت", value: fmt(archive.summary?.amount ?? 0) },
        { label: "الإجمالي", value: archive.summary?.count ?? 0 },
        { label: "إشعار حساب", value: archive.summary?.in_app ?? 0 },
        { label: "رسالة نصية", value: archive.summary?.sms ?? 0 },
        { label: "واتساب", value: archive.summary?.whatsapp ?? 0 },
      ],
      username: user?.name || user?.username || "",
    });
  };

  const selectedCategory = useMemo(() => cats.find((c) => c.id === catId) || null, [cats, catId]);
  const recipientLabel = recipientMode === "customer" ? (customer?.name || "") : (manualName || manualPhone);

  const previewText = useMemo(() => {
    const body = (message || templateText || "").trim();
    const company = "شبكة جواد نت اللاسلكية";
    const cardNumber = cards.find((c) => c.id === cardId)?.number || "—";
    return body
      .replaceAll("{{name}}", recipientLabel || "عميلنا")
      .replaceAll("{{category}}", selectedCategory?.name || "—")
      .replaceAll("{{card_number}}", cardNumber)
      .replaceAll("{{company}}", company);
  }, [message, templateText, recipientLabel, selectedCategory, cards, cardId]);

  const submit = async () => {
    if (!catId) { toast.error("اختر فئة الكرت"); return; }
    if (recipientMode === "customer" && !customer) { toast.error("اختر حساب المستلم"); return; }
    if (recipientMode === "manual" && !(manualName.trim() || manualPhone.trim())) { toast.error("أدخل اسم المستلم أو رقم هاتفه"); return; }
    setSending(true);
    try {
      const payload = {
        category_id: catId,
        method,
        recipient_type: recipientMode,
        customer_id: recipientMode === "customer" ? customer.id : null,
        recipient_name: recipientMode === "manual" ? manualName.trim() : (customer?.name || ""),
        recipient_phone: recipientMode === "manual" ? manualPhone.trim() : (customer?.phone || ""),
        message: message.trim(),
      };
      if (cardId) payload.card_id = cardId;
      const r = await api.post("/free-cards/send", payload);
      setResult(r.data);
      toast.success(`تم إرسال الكرت ${r.data?.send?.card_number || ""} وتحويل حالته إلى «مجاني»`);
      loadCards(catId, cardQuery);
      loadCategories();
    } catch (e) { toast.error(errText(e)); }
    finally { setSending(false); }
  };

  const resetForm = () => {
    setResult(null); setMessage(""); setCardId(""); setCustomer(null); setCustQuery(""); setCustResults([]);
    setManualName(""); setManualPhone("");
  };

  const periodLabel = PERIOD_LABELS?.[period] || "";

  return (
    <div className="space-y-4" data-testid="free-cards-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Gift size={22} className="text-[#221340]" />
          <h1 className="text-xl font-bold">إرسال كرت مجاني</h1>
        </div>
        <div className="flex rounded-lg border overflow-hidden" data-testid="free-cards-tabs">
          <button
            className={`px-4 py-2 text-sm flex items-center gap-1 ${tab === "send" ? "bg-[#221340] text-white" : "bg-white"}`}
            onClick={() => setTab("send")} data-testid="tab-send">
            <Send size={14} /> إرسال كرت
          </button>
          <button
            className={`px-4 py-2 text-sm flex items-center gap-1 ${tab === "archive" ? "bg-[#221340] text-white" : "bg-white"}`}
            onClick={() => setTab("archive")} data-testid="tab-archive">
            <Archive size={14} /> الأرشيف
          </button>
        </div>
      </div>

      {tab === "send" && (
        <Card className="p-4 space-y-4" data-testid="free-cards-send-form">
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>فئة الكرت</Label>
              <Select value={catId} onValueChange={setCatId}>
                <SelectTrigger data-testid="free-cat-select"><SelectValue placeholder="اختر الفئة" /></SelectTrigger>
                <SelectContent>
                  {cats.map((c) => (
                    <SelectItem key={c.id} value={c.id} data-testid={`free-cat-${c.id}`}>
                      {c.name} — المتاح: {c.available}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedCategory && (
                <div className="text-[11px] text-slate-500" data-testid="free-cat-info">
                  المتاح: {cardsInfo.available} — المجاني سابقاً: {selectedCategory.free} — المرسل: {selectedCategory.sent}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>رقم الكرت</Label>
              <div className="flex gap-2">
                <Select value={cardId} onValueChange={setCardId}>
                  <SelectTrigger data-testid="free-card-select">
                    <SelectValue placeholder={loadingCards ? "جاري التحميل..." : "تلقائي (أقدم كرت متاح)"} />
                  </SelectTrigger>
                  <SelectContent>
                    {cards.slice(0, 200).map((c) => (
                      <SelectItem key={c.id} value={c.id} data-testid={`free-card-${c.number}`}>{c.number}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input placeholder="بحث برقم الكرت" value={cardQuery} onChange={(e) => setCardQuery(e.target.value)}
                  className="max-w-[160px]" data-testid="free-card-search" />
                <Button variant="outline" onClick={() => loadCards(catId, cardQuery)} data-testid="free-card-refresh">
                  <RefreshCw size={14} />
                </Button>
              </div>
              <div className="text-[11px] text-slate-500">اتركه على «تلقائي» ليختار النظام أقدم كرت متاح في الفئة.</div>
            </div>
          </div>

          <div className="space-y-2">
            <Label>المستلم</Label>
            <div className="flex gap-2 mb-2">
              <Button size="sm" variant={recipientMode === "customer" ? "default" : "outline"} onClick={() => setRecipientMode("customer")} data-testid="free-recipient-customer">
                عميل مسجّل
              </Button>
              <Button size="sm" variant={recipientMode === "manual" ? "default" : "outline"} onClick={() => setRecipientMode("manual")} data-testid="free-recipient-manual">
                رقم / اسم يدوي
              </Button>
            </div>
            {recipientMode === "customer" ? (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <Input placeholder="ابحث بالاسم أو الهاتف" value={custQuery} onChange={(e) => setCustQuery(e.target.value)} data-testid="free-cust-search" />
                </div>
                {customer ? (
                  <div className="flex items-center justify-between rounded border bg-emerald-50 px-3 py-2 text-sm" data-testid="free-cust-selected">
                    <span>{customer.name} — {customer.phone || "بلا هاتف"}</span>
                    <Button size="sm" variant="ghost" onClick={() => setCustomer(null)}>تغيير</Button>
                  </div>
                ) : (
                  <div className="max-h-48 overflow-auto rounded border divide-y" data-testid="free-cust-results">
                    {custResults.map((c) => (
                      <button key={c.id} className="w-full text-right px-3 py-2 text-sm hover:bg-slate-50"
                        onClick={() => { setCustomer(c); setCustResults([]); }} data-testid={`free-cust-${c.id}`}>
                        {c.name} — {c.phone || "بلا هاتف"}
                      </button>
                    ))}
                    {!custResults.length && <div className="px-3 py-2 text-xs text-slate-400">اكتب حرفين على الأقل للبحث</div>}
                  </div>
                )}
              </div>
            ) : (
              <div className="grid md:grid-cols-2 gap-3">
                <Input placeholder="اسم المستلم" value={manualName} onChange={(e) => setManualName(e.target.value)} data-testid="free-manual-name" />
                <Input placeholder="رقم الهاتف" value={manualPhone} onChange={(e) => setManualPhone(e.target.value)} data-testid="free-manual-phone" />
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label>طريقة الإرسال</Label>
            <div className="grid sm:grid-cols-3 gap-2" data-testid="free-method-group">
              {["in_app", "sms", "whatsapp"].map((m) => {
                const Icon = METHOD_ICONS[m];
                const active = method === m;
                return (
                  <button key={m} onClick={() => setMethod(m)} data-testid={`free-method-${m}`}
                    className={`rounded-lg border px-3 py-2 text-sm flex items-center gap-2 ${active ? "border-[#221340] bg-[#221340] text-white" : "bg-white"}`}>
                    <Icon size={15} /> {METHOD_LABELS[m]}
                  </button>
                );
              })}
            </div>
            {method === "in_app" && recipientMode === "manual" && (
              <div className="text-[11px] text-amber-600">الإشعار داخل نافذة الحساب يظهر فقط للمستلمين المسجّلين؛ سيتم تسجيل العملية في الأرشيف.</div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>نص الرسالة</Label>
              <Button size="sm" variant="outline" onClick={() => { setMessage(templateText); }} data-testid="free-use-template">استخدام القالب</Button>
            </div>
            <Textarea rows={5} value={message} onChange={(e) => setMessage(e.target.value)} data-testid="free-message" />
            <div className="rounded bg-slate-50 border p-2 text-[12px] whitespace-pre-wrap" data-testid="free-message-preview">
              {previewText || "—"}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button onClick={submit} disabled={sending} className="bg-[#221340]" data-testid="free-send-submit">
              <Send size={15} className="ml-1" /> {sending ? "جاري الإرسال..." : "إرسال الكرت مجاناً"}
            </Button>
            <Button variant="outline" onClick={resetForm} data-testid="free-send-reset">تفريغ</Button>
          </div>

          {result && (
            <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 space-y-2" data-testid="free-send-result">
              <div className="flex items-center gap-2 font-semibold text-emerald-700">
                <CheckCircle2 size={16} /> تم الإرسال — رقم العملية {result?.send?.number}
              </div>
              <div className="text-sm">
                الكرت: <b>{result?.send?.card_number}</b> — الفئة: {result?.send?.category_name} — الحالة الجديدة: <b>مجاني</b>
              </div>
              <div className="text-sm">المستلم: {result?.send?.recipient_name || result?.send?.recipient_phone || "—"} — الطريقة: {METHOD_LABELS[result?.send?.method] || ""}</div>
              {result?.in_app_created && <div className="text-xs text-emerald-700">تم إنشاء إشعار في نافذة حساب المستلم.</div>}
              <div className="flex gap-2 pt-1">
                {result?.whatsapp_url && (
                  <Button size="sm" onClick={() => openWhatsAppUrl(result.whatsapp_url)} data-testid="free-open-whatsapp">
                    <MessageCircle size={14} className="ml-1" /> فتح واتساب
                  </Button>
                )}
                {result?.sms_phone && (
                  <Button size="sm" onClick={() => openSMS(result.sms_phone, result.message)} data-testid="free-open-sms">
                    <Smartphone size={14} className="ml-1" /> فتح الرسائل
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={() => setTab("archive")} data-testid="free-goto-archive">عرض الأرشيف</Button>
              </div>
            </div>
          )}
        </Card>
      )}

      {tab === "archive" && (
        <Card className="p-4 space-y-3" data-testid="free-cards-archive">
          <div className="flex flex-wrap items-end gap-3">
            <PeriodFilter period={period} start={start} end={end}
              onChange={({ period: p, start: s, end: e }) => { setPeriod(p); setStart(s); setEnd(e); }}
              testidPrefix="free-archive-period" />
            <div className="space-y-1">
              <Label className="text-xs">بحث</Label>
              <div className="flex gap-1">
                <Input placeholder="اسم / هاتف / رقم كرت" value={archiveQuery} onChange={(e) => setArchiveQuery(e.target.value)} data-testid="free-archive-search" />
                <Button variant="outline" onClick={loadArchive} data-testid="free-archive-filter"><Search size={14} /></Button>
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">طريقة الإرسال</Label>
              <Select value={archiveMethod} onValueChange={setArchiveMethod}>
                <SelectTrigger className="w-[190px]" data-testid="free-archive-method"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">الكل</SelectItem>
                  <SelectItem value="in_app">إشعار داخل نافذة الحساب</SelectItem>
                  <SelectItem value="sms">رسالة نصية</SelectItem>
                  <SelectItem value="whatsapp">رسالة واتساب</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button variant="outline" onClick={loadArchive} data-testid="free-archive-reload"><RefreshCw size={14} className="ml-1" /> تحديث</Button>
            <Button variant="outline" onClick={printArchive} data-testid="free-archive-print"><Printer size={14} className="ml-1" /> طباعة النتائج (PDF)</Button>
          </div>

          <div className="flex flex-wrap gap-2 text-xs" data-testid="free-archive-summary">
            <span className="rounded-full bg-slate-100 px-3 py-1">الفترة: {periodLabel}</span>
            <span className="rounded-full bg-slate-100 px-3 py-1">الإجمالي: {archive.summary.count}</span>
            <span className="rounded-full bg-slate-100 px-3 py-1">إشعار حساب: {archive.summary.in_app}</span>
            <span className="rounded-full bg-slate-100 px-3 py-1">نصية: {archive.summary.sms}</span>
            <span className="rounded-full bg-slate-100 px-3 py-1">واتساب: {archive.summary.whatsapp}</span>
            <span className="rounded-full bg-emerald-100 text-emerald-800 px-3 py-1 font-bold" data-testid="free-archive-amount-chip">إجمالي مبلغ الكروت: {fmt(archive.summary.amount || 0)}</span>
          </div>

          <div className="overflow-auto rounded border">
            <table className="w-full text-sm" data-testid="free-archive-table">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="p-2 text-right">التاريخ</th>
                  <th className="p-2 text-right">رقم العملية</th>
                  <th className="p-2 text-right">الفئة</th>
                  <th className="p-2 text-right">رقم الكرت</th>
                  <th className="p-2 text-right">المستلم</th>
                  <th className="p-2 text-right">الهاتف</th>
                  <th className="p-2 text-right">قيمة الكرت</th>
                  <th className="p-2 text-right">طريقة الإرسال</th>
                  <th className="p-2 text-right">الموظف</th>
                </tr>
              </thead>
              <tbody>
                {archive.items.map((row) => (
                  <tr key={row.id} data-testid={`free-archive-row-${row.id}`}
                    className={`border-t ${focusId && row.id === focusId ? "bg-amber-50" : ""}`}>
                    <td className="p-2">{fmtDate(row.created_at)}</td>
                    <td className="p-2">{row.number}</td>
                    <td className="p-2">{row.category_name}</td>
                    <td className="p-2 font-semibold">{row.card_number}</td>
                    <td className="p-2">{row.recipient_name || "—"}</td>
                    <td className="p-2">{row.recipient_phone || "—"}</td>
                    <td className="p-2 num">{fmt(row.amount || 0)}</td>
                    <td className="p-2">{METHOD_LABELS[row.method] || row.method}</td>
                    <td className="p-2">{row.username || "—"}</td>
                  </tr>
                ))}
                {!archive.items.length && (
                  <tr><td className="p-3 text-center text-slate-400" colSpan={9}>{loadingArchive ? "جاري التحميل..." : "لا توجد عمليات في الفترة المحددة"}</td></tr>
                )}
              </tbody>
              {archive.items.length > 0 && (
                <tfoot className="bg-slate-100 font-bold" data-testid="free-archive-totals">
                  <tr>
                    <td className="p-2" colSpan={3}>الإجمالي: {archive.summary.count} عملية</td>
                    <td className="p-2 num text-emerald-800" colSpan={3} data-testid="free-archive-amount-total">
                      إجمالي مبلغ الكروت: {fmt(archive.summary.amount || 0)}
                    </td>
                    <td className="p-2" colSpan={3}>
                      إشعار حساب: {archive.summary.in_app} • نصية: {archive.summary.sms} • واتساب: {archive.summary.whatsapp}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}