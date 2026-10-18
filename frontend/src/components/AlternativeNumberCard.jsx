import { useState } from "react";
import { Check, Copy, Hash } from "lucide-react";
import { toast } from "sonner";

const ALTERNATIVE_NUMBER_RE = /^[1-9][0-9]{5}$/;

function digits(value) {
  return String(value || "").replace(/[^0-9]/g, "");
}

function shortDisplayName(customer) {
  const explicit = String(customer?.short_name || "").trim();
  if (explicit) return explicit;

  const parts = String(customer?.name || "").trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).join(" ") || "الحساب";
}

export default function AlternativeNumberCard({ customer }) {
  const [copied, setCopied] = useState(false);
  const alternativeNumber = String(customer?.alternative_number || "").trim();
  if (!ALTERNATIVE_NUMBER_RE.test(alternativeNumber)) return null;

  const phoneLast2 = String(customer?.phone_last2 || digits(customer?.phone).slice(-2)).slice(-2);
  const name = shortDisplayName(customer);

  const copyAlternativeNumber = async () => {
    try {
      await navigator.clipboard.writeText(alternativeNumber);
      setCopied(true);
      toast.success("تم نسخ الرقم البديل");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      toast.error("تعذر نسخ الرقم البديل");
    }
  };

  return (
    <div
      className="rounded-lg border-2 border-[#D4AF37]/60 bg-gradient-to-l from-[#D4AF37]/10 to-[#452480]/5 p-3"
      data-testid="po-info-alternative-number"
      dir="rtl"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-bold text-[#452480]">
            <Hash size={14} aria-hidden="true" />
            <span>الرقم البديل للتحويل</span>
          </div>
          <div className="mt-1 font-mono text-2xl font-black tracking-[0.18em] text-[#221340]" dir="ltr">
            {alternativeNumber}
          </div>
          <div className="mt-1 text-[11px] font-bold text-[#d4af37]">مثال: 48291735</div>
          <div className="mt-1 text-[11px] text-slate-600">
            {name} · تأكيد الهاتف المنتهي بـ {phoneLast2 || "--"}
          </div>
        </div>
        <button
          type="button"
          onClick={copyAlternativeNumber}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-[#452480]/30 px-2.5 text-xs font-bold text-[#452480] transition hover:bg-[#452480]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#452480]/40"
          data-testid="po-info-alternative-copy"
          aria-label="نسخ الرقم البديل"
        >
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          {copied ? "تم النسخ" : "نسخ"}
        </button>
      </div>
      <div className="mt-2 border-t border-[#D4AF37]/30 pt-2 text-[11px] text-slate-600">
        استخدم هذا الرقم بدل رقم الهاتف عند تحويل الرصيد إلى حسابك.
      </div>
    </div>
  );
}
