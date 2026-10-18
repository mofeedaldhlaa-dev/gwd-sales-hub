import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { daysInMonthIso, getCalendarDate, monthStartDate, parseDateBoundary, todayIso, dateIso, useAppDate } from "@/lib/DateService";

export { todayIso };
export const PERIOD_LABELS = { all: "الكل", day: "يومي", month: "شهري", year: "سنوي", custom: "مخصص" };
const MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
const currentYear = () => getCalendarDate().getFullYear();
const daysInMonth = (year, month) => daysInMonthIso(year, month);
const monthStartEnd = (year, month) => ({ start: `${year}-${String(month).padStart(2, "0")}-01`, end: `${year}-${String(month).padStart(2, "0")}-${String(daysInMonth(year, month)).padStart(2, "0")}` });
const yearStartEnd = (year) => ({ start: `${year}-01-01`, end: `${year}-12-31` });
export const rangeForPeriod = (period, anchor = getCalendarDate()) => {
  const date = dateIso(anchor);
  if (period === "day") return { start: date, end: date };
  if (period === "month") return monthStartEnd(anchor.getFullYear(), anchor.getMonth() + 1);
  if (period === "year") return yearStartEnd(anchor.getFullYear());
  return { start: "", end: "" };
};
export const validatePeriodRange = ({ period, start, end }) => {
  if (period !== "custom") return null;
  if (!start) return "اختر تاريخ البداية قبل التنفيذ";
  if (!end) return "اختر تاريخ النهاية قبل التنفيذ";
  if (end < start) return "تاريخ النهاية يجب أن يكون بعد أو مساويًا لتاريخ البداية";
  return null;
};
const years = () => { const year = currentYear(); return Array.from({ length: 12 }, (_, i) => year - 5 + i); };
const initialDrafts = (period, start) => {
  const current = todayIso();
  const calendar = getCalendarDate();
  const startDate = /^\d{4}-\d{2}-\d{2}$/.test(start || "") ? start : current;
  const monthPeriod = period === "month" && /^\d{4}-\d{2}-\d{2}$/.test(start || "");
  const yearPeriod = period === "year" && /^\d{4}-\d{2}-\d{2}$/.test(start || "");
  return { day: { date: period === "day" ? startDate : current }, month: { year: monthPeriod ? Number(start.slice(0, 4)) : calendar.getFullYear(), month: monthPeriod ? Number(start.slice(5, 7)) : calendar.getMonth() + 1 }, year: { year: yearPeriod ? Number(start.slice(0, 4)) : calendar.getFullYear() }, custom: { start: "", end: "" } };
};
export default function PeriodFilter({ period, start, end, onChange, testidPrefix = "period", className = "" }) {
  const { selectedDate, setSelectedDate } = useAppDate();
  const [drafts, setDrafts] = useState(() => initialDrafts(period, start));
  const activePeriod = ["day", "month", "year", "custom"].includes(period) ? period : "day";
  useEffect(() => { setDrafts((previous) => {
    if (period === "day" && /^\d{4}-\d{2}-\d{2}$/.test(start || "")) return { ...previous, day: { date: start } };
    if (period === "month" && /^\d{4}-\d{2}-\d{2}$/.test(start || "")) return { ...previous, month: { year: Number(start.slice(0, 4)), month: Number(start.slice(5, 7)) } };
    if (period === "year" && /^\d{4}-\d{2}-\d{2}$/.test(start || "")) return { ...previous, year: { year: Number(start.slice(0, 4)) } };
    return previous;
  }); }, [period, start, end]);
  useEffect(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(selectedDate || "") || activePeriod === "custom") return;
    const anchor = parseDateBoundary(selectedDate);
    const range = rangeForPeriod(activePeriod, anchor);
    if (range.start === start && range.end === end) return;
    setDrafts((previous) => ({
      ...previous,
      day: activePeriod === "day" ? { date: range.start } : previous.day,
      month: activePeriod === "month" ? { year: Number(range.start.slice(0, 4)), month: Number(range.start.slice(5, 7)) } : previous.month,
      year: activePeriod === "year" ? { year: Number(range.start.slice(0, 4)) } : previous.year,
    }));
    onChange({ period: activePeriod, ...range });
  }, [selectedDate]);
  const emit = (nextPeriod, range) => { if (range.start) setSelectedDate(range.start); onChange({ period: nextPeriod, ...range }); };
  const selectDay = (date) => { setDrafts((d) => ({ ...d, day: { date } })); emit("day", { start: date, end: date }); };
  const selectMonth = (year, month) => { const range = monthStartEnd(year, month); setDrafts((d) => ({ ...d, month: { year: Number(year), month: Number(month) } })); emit("month", range); };
  const selectYear = (year) => { const range = yearStartEnd(year); setDrafts((d) => ({ ...d, year: { year: Number(year) } })); emit("year", range); };
  const enterCustom = () => emit("custom", drafts.custom || { start: "", end: "" });
  const openCustom = () => {
    const next = { start: start || drafts.custom.start || "", end: end || drafts.custom.end || "" };
    setDrafts((d) => ({ ...d, custom: next }));
    emit("custom", next);
  };
  const updateCustom = (next) => { setDrafts((d) => ({ ...d, custom: next })); emit("custom", next); };
  return <div dir="rtl" className={`flex flex-col gap-3 ${className}`} data-testid={`${testidPrefix}-filter`}>
    <div className="flex flex-wrap gap-2">{[["day", "يومي"], ["month", "شهري"], ["year", "سنوي"], ["custom", "مخصص"]].map(([key, label]) => <button key={key} type="button" onClick={() => { if (key === "day") selectDay(drafts.day.date); else if (key === "month") selectMonth(drafts.month.year, drafts.month.month); else if (key === "year") selectYear(drafts.year.year); else { openCustom(); } }} className={`px-3 py-1.5 rounded-md border text-xs font-bold ${activePeriod === key ? "bg-[#452480] text-white border-[#452480]" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`} data-testid={`${testidPrefix}-${key}`}>{label}</button>)}</div>
    {activePeriod === "day" && <div><label className="text-xs text-slate-500 block mb-1">التاريخ</label><Input type="date" value={drafts.day.date} onChange={(e) => selectDay(e.target.value)} data-testid={`${testidPrefix}-day-input`} /></div>}
    {activePeriod === "month" && <div className="grid grid-cols-2 gap-2"><div><label className="text-xs text-slate-500 block mb-1">الشهر</label><select value={drafts.month.month} onChange={(e) => selectMonth(drafts.month.year, Number(e.target.value))} className="w-full border rounded-md p-2 text-sm" data-testid={`${testidPrefix}-month-select`}>{MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}</select></div><div><label className="text-xs text-slate-500 block mb-1">السنة</label><select value={drafts.month.year} onChange={(e) => selectMonth(Number(e.target.value), drafts.month.month)} className="w-full border rounded-md p-2 text-sm" data-testid={`${testidPrefix}-month-year`}>{years().map((y) => <option key={y} value={y}>{y}</option>)}</select></div></div>}
    {activePeriod === "year" && <div><label className="text-xs text-slate-500 block mb-1">السنة</label><select value={drafts.year.year} onChange={(e) => selectYear(Number(e.target.value))} className="w-full border rounded-md p-2 text-sm" data-testid={`${testidPrefix}-year-select`}>{years().map((y) => <option key={y} value={y}>{y}</option>)}</select></div>}
    {activePeriod === "custom" && <div className="grid grid-cols-2 gap-2"><div><label className="text-xs text-slate-500 block mb-1">من</label><Input type="date" value={drafts.custom.start} onChange={(e) => updateCustom({ ...drafts.custom, start: e.target.value })} data-testid={`${testidPrefix}-custom-start`} /></div><div><label className="text-xs text-slate-500 block mb-1">إلى</label><Input type="date" value={drafts.custom.end} onChange={(e) => updateCustom({ ...drafts.custom, end: e.target.value })} data-testid={`${testidPrefix}-custom-end`} /></div><button type="button" onClick={enterCustom} className="hidden" aria-hidden="true" tabIndex={-1} /> </div>}
  </div>;
}
