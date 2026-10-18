import { Button } from "@/components/ui/button";

export const PAYMENT_INSTRUCTION_STEPS = [
  { title: "الدخول إلى الحساب", body: "ادخل إلى قائمة الحساب، ثم اختر الحسابات البنكية وطرق السداد." },
  { title: "اختيار طريقة السداد", body: "اختر الحساب أو المحفظة التي ترغب في السداد عن طريقها، ثم اضغط على «نسخ رقم الحساب» من بطاقة الحساب نفسها." },
  { title: "تنفيذ عملية التحويل", body: "قم بإجراء عملية السداد باستخدام رقم الحساب الذي تم نسخه مسبقًا، وتأكد من صحة جميع بيانات التحويل قبل تأكيد العملية." },
  { title: "نسخ المرجع", body: "بعد نجاح السداد، انسخ رقم مرجع العملية الظاهر في إشعار البنك أو المحفظة." },
  { title: "تأكيد عملية الدفع", body: "ارجع إلى بطاقة الحساب نفسه، واضغط على «تأكيد عملية الدفع»، ثم أدخل المبلغ ورقم المرجع واضغط إرسال الطلب." },
];

const NET_PAYMENT_INSTRUCTION_STEPS = PAYMENT_INSTRUCTION_STEPS.filter((step) => step.title !== "الدخول إلى الحساب").map((step) => (
  step.title === "تأكيد عملية الدفع"
    ? { ...step, body: "ارجع إلى بطاقة الحساب نفسه، واضغط على «تأكيد عملية الدفع»، ثم أدخل رقم المرجع واضغط إرسال الطلب." }
    : step
));

export default function PaymentInstructions({ onClose, closeTestid = "po-close-payment-instructions", variant = "account" }) {
  const isNetPurchase = variant === "net-purchase";
  const steps = isNetPurchase ? NET_PAYMENT_INSTRUCTION_STEPS : PAYMENT_INSTRUCTION_STEPS;
  return (
    <div className="space-y-3 text-sm leading-7 text-[#243B5A]" data-testid="payment-instructions-content">
      <p className="rounded-2xl border border-[#D7E2EF] bg-[#F5F8FC] p-3 font-bold">{isNetPurchase ? "لإتمام عملية السداد والشراء بنجاح، يرجى اتباع الخطوات التالية:" : "لإتمام عملية السداد وإضافة المبلغ إلى حسابك، يرجى اتباع الخطوات التالية بالترتيب وبدقة:"}</p>
      <ol className="space-y-3" data-testid="po-payment-instructions-steps">
        {steps.map((step, index) => (
          <li key={step.title} className="flex items-start gap-3 rounded-2xl border border-[#E5EEF8] bg-white p-3 shadow-sm">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#245C9D] text-xs font-black text-white">{index + 1}</span>
            <span className="min-w-0"><strong className="block text-[#12264A]">{step.title}</strong><span className="mt-1 block">{step.body}</span></span>
          </li>
        ))}
      </ol>
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-900" data-testid="po-payment-instructions-automatic-check">
        <strong className="block">التحقق سيتم بشكل آلي</strong>
        <span>{isNetPurchase ? "سيتم التحقق من عملية السداد تلقائيًا بعد إرسال البيانات، وعند نجاح التحقق سيتم عرض الكرت مباشرة." : "سيتم التحقق من عملية السداد تلقائيًا بعد إرسال البيانات، وعند نجاح التحقق سيتم إضافة المبلغ إلى رصيد حسابك تلقائيًا."}</span>
      </div>
      {!isNetPurchase && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-amber-950" data-testid="po-payment-instructions-warning">
        <strong className="block">تنبيه مهم</strong>
        <span>احرص على إدخال المبلغ المحول والمحفظة المستخدمة ورقم المرجع كما ظهر في إشعار نجاح الإيداع، وتجنب المحاولات المتكررة ببيانات خاطئة حتى لا يتم إيقاف تأكيد الدفع مؤقتًا.</span>
      </div>}
      {onClose && <Button type="button" onClick={onClose} className="h-12 w-full rounded-2xl bg-[#245C9D] font-black text-white hover:bg-[#1D4E86]" data-testid={closeTestid}>فهمت التعليمات</Button>}
    </div>
  );
}
