import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Clock3 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const DUPLICATE_EVENT = "gwd:duplicate-operation";
let duplicateRequestId = 0;

export function duplicateOperationMessage(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status !== 409 || typeof detail !== "string") return "";
  return /عملية سابقة|هل تريد المتابعة/.test(detail) ? detail : "";
}

export function confirmDuplicateOperation(error) {
  const message = duplicateOperationMessage(error);
  if (!message || typeof window === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    window.dispatchEvent(new CustomEvent(DUPLICATE_EVENT, {
      detail: { id: ++duplicateRequestId, message, resolve },
    }));
  });
}

export function withDuplicateApproval(payload) {
  return { ...payload, allow_duplicate: true };
}

export function DuplicateOperationDialog() {
  const [request, setRequest] = useState(null);
  const pendingRef = useRef(null);

  useEffect(() => {
    const onDuplicate = (event) => {
      const next = event.detail;
      if (!next?.resolve) return;
      if (pendingRef.current?.resolve) pendingRef.current.resolve(false);
      pendingRef.current = next;
      setRequest(next);
    };
    window.addEventListener(DUPLICATE_EVENT, onDuplicate);
    return () => {
      window.removeEventListener(DUPLICATE_EVENT, onDuplicate);
      if (pendingRef.current?.resolve) pendingRef.current.resolve(false);
      pendingRef.current = null;
    };
  }, []);

  const finish = (approved) => {
    const current = pendingRef.current;
    pendingRef.current = null;
    setRequest(null);
    current?.resolve(Boolean(approved));
  };

  return (
    <AlertDialog open={Boolean(request)} onOpenChange={(open) => { if (!open) finish(false); }}>
      <AlertDialogContent dir="rtl" className="max-w-md overflow-hidden rounded-2xl border-amber-200 bg-white p-0 shadow-2xl">
        <div className="h-1.5 bg-gradient-to-l from-[#452480] via-[#D4AF37] to-[#452480]" />
        <div className="space-y-5 p-6">
          <AlertDialogHeader className="text-right">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-600 ring-1 ring-amber-200">
                <AlertTriangle size={22} />
              </div>
              <div>
                <AlertDialogTitle className="text-xl font-black text-[#221340]">تأكيد العملية</AlertDialogTitle>
                <p className="mt-1 text-xs font-semibold text-amber-700">تنبيه إلى عملية مشابهة خلال آخر دقيقتين</p>
              </div>
            </div>
          </AlertDialogHeader>

          <AlertDialogDescription asChild>
            <div className="rounded-xl border border-amber-100 bg-amber-50/70 p-4 text-right text-sm leading-7 text-slate-700">
              <div className="mb-2 flex items-center gap-2 font-bold text-[#221340]"><Clock3 size={16} className="text-amber-600" /> مراجعة العملية السابقة</div>
              <p>{request?.message}</p>
              <p className="mt-2 text-xs text-slate-500">لن يتم إنشاء أي قيد جديد إذا اخترت الإلغاء.</p>
            </div>
          </AlertDialogDescription>

          <AlertDialogFooter className="grid grid-cols-2 gap-3 sm:flex sm:flex-row-reverse">
            <AlertDialogAction
              onClick={() => finish(true)}
              className="h-11 rounded-xl bg-[#452480] font-bold text-white hover:bg-[#321862]"
              data-testid="duplicate-confirm-button"
            >
              تأكيد العملية
            </AlertDialogAction>
            <AlertDialogCancel
              onClick={() => finish(false)}
              className="mt-0 h-11 rounded-xl border-slate-200 font-bold text-slate-700 hover:bg-slate-50"
              data-testid="duplicate-cancel-button"
            >
              إلغاء العملية
            </AlertDialogCancel>
          </AlertDialogFooter>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default duplicateOperationMessage;

// duplicate-operation-confirmation-contract
