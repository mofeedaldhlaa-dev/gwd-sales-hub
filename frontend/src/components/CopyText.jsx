import { useState } from "react";
import { Copy, Check, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

/** Copy text to the clipboard, with a fallback that also works inside the Android WebView. */
export async function copyToClipboard(text) {
  const value = String(text ?? "");
  if (!value.trim()) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (e) { /* fall back below */ }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch (e) {
    return false;
  }
}

/**
 * Pulls a password out of a message body, supporting both the inline form
 * ("كلمة المرور: 1234") and the two-line form ("كلمة المرور:\n1234").
 */
export function extractPassword(message) {
  const text = String(message ?? "");
  if (!text) return "";
  const match = text.match(/كلمة المرور(?:\s*الجديدة)?\s*:\s*(?:\r?\n)?\s*([^\s\n]+)/);
  return match && match[1] ? match[1].trim() : "";
}

/** Small button that copies arbitrary text (a password, a phone number, a whole message). */
export function CopyButton({
  text,
  label = "نسخ",
  copiedLabel = "تم النسخ",
  successMessage = "تم النسخ",
  failureMessage = "تعذّر النسخ",
  className = "",
  variant = "outline",
  testid,
  ...rest
}) {
  const [copied, setCopied] = useState(false);
  const disabled = !String(text ?? "").trim();
  const onClick = async () => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopied(true);
      if (successMessage) toast.success(successMessage);
      setTimeout(() => setCopied(false), 1800);
    } else if (failureMessage) {
      toast.error(failureMessage);
    }
  };
  return (
    <Button
      type="button"
      size="sm"
      variant={variant}
      onClick={onClick}
      disabled={disabled}
      className={`h-7 px-2 text-[11px] gap-1 ${className}`}
      data-testid={testid}
      {...rest}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? copiedLabel : label}
    </Button>
  );
}

/**
 * Shows a password with a copy button and an optional hide/show toggle, so the
 * value can be selected and copied easily on phones.
 */
export function PasswordValue({
  value,
  label = "كلمة المرور",
  hiddenByDefault = false,
  testid = "password-value",
  className = "",
}) {
  const [visible, setVisible] = useState(!hiddenByDefault);
  const shown = visible ? String(value ?? "") : "•".repeat(Math.max(6, Math.min(12, String(value ?? "").length || 6)));
  return (
    <span className={`flex flex-wrap items-center gap-2 ${className}`} dir="rtl">
      <span className="text-slate-700">{label}:</span>
      <span className="font-mono font-bold text-emerald-900 bg-white/70 border border-emerald-200 rounded px-2 py-0.5 select-all" dir="ltr" data-testid={testid}>
        {shown}
      </span>
      <CopyButton
        text={value}
        label="نسخ كلمة المرور"
        successMessage="تم نسخ كلمة المرور"
        testid={`${testid}-copy`}
      />
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => setVisible((v) => !v)}
        className="h-7 px-2 text-[11px] gap-1"
        data-testid={`${testid}-toggle`}
      >
        {visible ? <EyeOff size={13} /> : <Eye size={13} />}
        {visible ? "إخفاء" : "إظهار"}
      </Button>
    </span>
  );
}

/** Copies a whole message body (WhatsApp / SMS text) in one tap. */
export function CopyMessageButton({ text, label = "نسخ الرسالة كاملة", className = "", testid = "copy-message" }) {
  return (
    <CopyButton
      text={text}
      label={label}
      successMessage="تم نسخ نص الرسالة"
      className={className}
      testid={testid}
    />
  );
}

export default CopyButton;
