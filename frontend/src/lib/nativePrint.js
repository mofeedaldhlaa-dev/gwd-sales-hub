import { Capacitor, registerPlugin } from "@capacitor/core";

const NativePrint = registerPlugin("NativePrint");

export const isNativePrintAvailable = () => Capacitor.isNativePlatform();

export const nativePrintHtml = async (html, jobName = "GAWAD NET") => {
  if (!isNativePrintAvailable()) return false;
  await NativePrint.print({ html, jobName });
  return true;
};
