import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CheckCircle, Copy, Landmark, WalletCards } from "lucide-react";
import { paymentInstructionImageUrl } from "@/lib/paymentAccounts";

const providerLabel = (providerType) => providerType === "wallet" ? "محفظة إلكترونية" : "حساب بنكي";

export default function PaymentAccountCard({ account, onCopy, onConfirm, onSelect, onCardSelect, onInstructionImage, selectLabel = "اختيار طريقة الدفع", selected = false, testidPrefix = "payment-account", numberCopyTestid, confirmTestid, selectTestid, showHolder = true, showDetails = true, detailsLabel = "تعليمات السداد" }) {
  const id = account?.id || account?.account_number || account?.bank_name || "account";
  const copy = (value, message) => onCopy?.(value, message);
  const actionCount = [onConfirm, onSelect].filter(Boolean).length;
  const clickable = Boolean(onCardSelect);
  const handleCardKeyDown = (event) => {
    if (!clickable || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onCardSelect(account);
  };

  return (
    <Card
      className={`po-payment-account-card ${clickable ? "po-net-bank-account-card is-clickable" : ""} p-4 ${selected ? "is-selected" : ""}`}
      data-testid={`${testidPrefix}-${id}`}
      data-selected={selected ? "true" : "false"}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-pressed={clickable ? selected : undefined}
      onClick={clickable ? () => onCardSelect(account) : undefined}
      onKeyDown={handleCardKeyDown}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0 flex-1 text-right">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex min-w-0 items-center gap-2 font-bold text-base text-[#221340]">
              <Landmark size={16} className="shrink-0 text-[#452480]" />
              <span className="break-words whitespace-normal">{account?.bank_name || "حساب السداد"}</span>
            </div>
            <span className="inline-flex items-center gap-1 rounded-full bg-[#452480]/10 px-2 py-0.5 text-[10px] font-bold text-[#452480]">
              <WalletCards size={11} /> {providerLabel(account?.provider_type)}
            </span>
          </div>
          {showHolder && account?.holder_name && <div className="mt-1 break-words text-sm text-slate-600"><span className="font-bold text-[#221340]">اسم الحساب: </span>{account.holder_name}</div>}
        </div>
        {selected && <span className="po-net-choice-check is-selected" aria-label="تم الاختيار">✓</span>}
      </div>

      <div className="mt-2 space-y-1.5 text-xs">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <span className="text-slate-500">رقم الحساب أو المحفظة</span>
          <div className="flex min-w-0 items-center gap-2">
            <span dir="ltr" className="break-all text-left font-mono text-sm font-bold text-[#221340]">{account?.account_number || "-"}</span>
            <button type="button" onClick={(event) => { event.stopPropagation(); copy(account?.account_number, "تم نسخ رقم الحساب"); }} className="shrink-0 rounded-lg p-1 text-[#452480] hover:bg-[#F3EEF8]" aria-label="نسخ رقم الحساب" data-testid={numberCopyTestid || `${testidPrefix}-number-copy-${id}`}>
              <Copy size={13} />
            </button>
          </div>
        </div>
        {showDetails && account?.details && <div className="break-words whitespace-pre-line text-xs leading-5 text-slate-500"><span className="font-bold text-[#221340]">{detailsLabel}: </span>{account.details}</div>}
        {account?.instruction_image_path && onInstructionImage && <button type="button" onClick={(event) => { event.stopPropagation(); onInstructionImage(account); }} className="mt-2 inline-flex min-h-9 items-center gap-2 rounded-xl border border-[#452480] bg-[#F8F7FC] px-2 py-1.5 text-xs font-black text-[#452480] hover:bg-[#F3EEF8]" data-testid={`${testidPrefix}-instruction-image-${id}`}>
          <img src={paymentInstructionImageUrl(account, "thumbnail")} alt="" loading="lazy" decoding="async" width="32" height="32" className="h-8 w-8 rounded-lg border border-[#D9CBE8] bg-white object-cover" />
          <span>اضغط لمعاينة تعليمات السداد</span>
        </button>}
      </div>

      {actionCount > 0 && <div className={`mt-3 grid gap-2 ${actionCount > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
        {onConfirm && <Button type="button" onClick={(event) => { event.stopPropagation(); onConfirm(account); }} className="h-10 rounded-xl bg-[#452480] px-2 text-[11px] font-black text-white hover:bg-[#5A2FA0]" data-testid={confirmTestid || `${testidPrefix}-confirm-${id}`}>
          <CheckCircle size={14} className="ml-1" /> تأكيد عملية الدفع
        </Button>}
        {onSelect && <Button type="button" onClick={(event) => { event.stopPropagation(); onSelect(account); }} className="h-10 rounded-xl bg-[#452480] px-2 text-[11px] font-black text-white hover:bg-[#5A2FA0]" data-testid={selectTestid || `${testidPrefix}-select-${id}`}>
          {selectLabel}
        </Button>}
      </div>}
    </Card>
  );
}

export { providerLabel as paymentAccountProviderLabel };
