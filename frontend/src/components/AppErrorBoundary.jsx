import React from "react";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  componentDidMount() {
    document.getElementById("root")?.setAttribute("data-react-mounted", "1");
    this.onWindowError = (event) => this.setState({ error: event.error || new Error(event.message || "Startup error") });
    this.onUnhandledRejection = (event) => this.setState({ error: event.reason || new Error("Startup promise rejected") });
    window.addEventListener("error", this.onWindowError);
    window.addEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  componentWillUnmount() {
    window.removeEventListener("error", this.onWindowError);
    window.removeEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("GAWAD NET render failure", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div dir="rtl" className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
        <div className="w-full max-w-lg rounded-2xl border border-red-200 bg-white p-6 shadow-sm text-center space-y-4">
          <h1 className="text-xl font-black text-red-700">حدث خطأ أثناء تشغيل التطبيق</h1>
          <p className="text-sm text-slate-600">تعذر تشغيل الواجهة أو تهيئة التخزين المحلي. لم يتم اعتبار أي عملية مالية ناجحة بسبب هذا الخطأ.</p>
          <div className="flex justify-center gap-2">
            <button type="button" onClick={() => window.location.reload()} className="rounded-lg bg-[#452480] px-4 py-2 text-white">إعادة المحاولة</button>
            <button type="button" onClick={() => { window.location.href = "/mof30"; }} className="rounded-lg border px-4 py-2">العودة لتسجيل الدخول</button>
          </div>
        </div>
      </div>
    );
  }
}
