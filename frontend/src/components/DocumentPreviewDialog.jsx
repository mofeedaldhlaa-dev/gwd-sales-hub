import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { fmt, fmtDate } from "@/lib/utils";
import { ExternalLink } from "lucide-react";

// Shows the operation a notification points at: receipt/voucher, sales invoice,
// purchase invoice or transfer. Loaded on demand from the API so the preview is
// always the live document.
const ENDPOINTS = { receipt: "receipts", sale: "sales", purchase: "purchases", transfer: "transfers", free_card: "free-cards/sends" };
const LABELS = { receipt: "سند", sale: "فاتورة بيع", purchase: "فاتورة شراء", transfer: "سند تحويل", free_card: "كرت مجاني" };
const OPEN_ROUTES = {
  receipt: (doc) => `/receipts?focus=${doc.id}`,
  sale: (doc) => `/sales/${doc.id}/edit`,
  purchase: (doc) => `/purchases/${doc.id}/edit`,
  transfer: (doc) => `/transfers?focus=${doc.id}`,
  free_card: (doc) => `/free-cards?focus=${doc.id}`,
};

const documentTitle = (kind, doc) => {
  if (!doc) return LABELS[kind] || "العملية";
  if (kind === "receipt") {
    if (doc.kind === "receipt") return "سند قبض";
    if (doc.kind === "payment") return "سند صرف";
    return doc.type === "payment_voucher" ? "سند صرف" : "سند قبض";
  }
  return LABELS[kind] || "العملية";
};

const partyLabel = (kind, doc) => {
  if (!doc) return "";
  if (kind === "transfer") {
    const source = doc.source_name || "الصندوق";
    const dest = doc.dest_name || "-";
    return `${source} ← ${dest}`;
  }
  return doc.party_name || doc.customer_name || doc.account_name || doc.supplier_name
    || (doc.customer && doc.customer.name) || "";
};

const quantityOf = (item) => {
  const values = [item.quantity, item.qty, item.count, (item.card_numbers || []).length];
  const found = values.find((value) => Number(value) > 0);
  return found ? Number(found) : 1;
};

export default function DocumentPreviewDialog({ open, onOpenChange, document: kind, entityId }) {
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    if (!open || !kind || !entityId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError("");
    setDoc(null);
    api.get(`/${ENDPOINTS[kind] || "receipts"}/${entityId}`)
      .then((response) => { if (!cancelled) setDoc(response.data); })
      .catch((exc) => { if (!cancelled) setError(errText(exc)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, kind, entityId]);

  const items = Array.isArray(doc?.items) ? doc.items : [];
  const amount = doc?.amount ?? doc?.total;
  const route = doc ? OPEN_ROUTES[kind]?.(doc) : "";

  const freeCardRows = doc ? [
    ["رقم العملية", doc.number || ""],
    ["الفئة", doc.category_name || ""],
    ["رقم الكرت", doc.card_number || ""],
    ["المستلم", doc.recipient_name || doc.recipient_phone || ""],
    ["هاتف المستلم", doc.recipient_phone || ""],
    ["طريقة الإرسال", doc.channel_label || doc.method || ""],
    ["القيمة", doc.amount ? fmt(doc.amount) : ""],
    ["الحالة", doc.status === "sent" ? "تم الإرسال" : (doc.status || "")],
    ["التاريخ", fmtDate(doc.created_at)],
    ["أرسله", doc.username || ""],
  ].filter(([, value]) => value !== "" && value !== undefined && value !== null) : [];

  const rows = doc && kind === "free_card" ? freeCardRows : doc ? [
    ["التاريخ", fmtDate(doc.created_at)],
    ["الطرف", partyLabel(kind, doc)],
    ["المبلغ", amount !== undefined && amount !== null ? fmt(amount) : ""],
    ["المدفوع", doc.paid !== undefined && doc.paid !== null ? fmt(doc.paid) : ""],
    ["المتبقي", doc.remaining !== undefined && doc.remaining !== null ? fmt(doc.remaining) : ""],
    ["رصيد الحساب بعد السند", doc.balance_after !== undefined && doc.balance_after !== null ? fmt(doc.balance_after) : ""],
    ["البيان", doc.description || doc.notes || ""],
    ["أنشأه", doc.username || ""],
  ].filter(([, value]) => value !== "" && value !== undefined && value !== null && value !== "NaN") : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="document-preview-dialog">
        <DialogHeader>
          <DialogTitle>
            {loading ? "جاري تحميل العملية..." : `${documentTitle(kind, doc)}${doc?.number ? ` — ${doc.number}` : ""}`}
          </DialogTitle>
        </DialogHeader>
        {error && <div className="text-sm text-rose-600">{error}</div>}
        {!loading && doc && (
          <div className="space-y-3">
            <div className="border rounded-lg divide-y">
              {rows.map(([label, value]) => (
                <div key={label} className="flex items-start justify-between gap-3 p-2 text-sm">
                  <span className="text-slate-500">{label}</span>
                  <span className="font-semibold text-[#221340] text-left whitespace-pre-line">{value}</span>
                </div>
              ))}
            </div>
            {items.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="p-2 text-right">الصنف</th>
                      <th className="p-2 text-right">الكمية</th>
                      <th className="p-2 text-right">السعر</th>
                      <th className="p-2 text-right">الإجمالي</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, index) => (
                      <tr key={item.id || `${item.name}-${index}`} className="border-t">
                        <td className="p-2">{item.name || item.category_name || item.description || "-"}</td>
                        <td className="p-2">{quantityOf(item)}</td>
                        <td className="p-2">{item.price !== undefined ? fmt(item.price) : "-"}</td>
                        <td className="p-2">{item.total !== undefined ? fmt(item.total) : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex flex-wrap gap-2 justify-end">
              {route && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => { onOpenChange(false); navigate(route); }}
                  data-testid="document-preview-open"
                >
                  <ExternalLink size={14} className="ml-1" /> فتح في الشاشة
                </Button>
              )}
              <Button type="button" onClick={() => onOpenChange(false)}>إغلاق</Button>
            </div>
          </div>
        )}
        {!loading && !doc && !error && <div className="text-sm text-slate-500">لا توجد بيانات</div>}
      </DialogContent>
    </Dialog>
  );
}