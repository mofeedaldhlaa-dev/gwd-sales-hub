import { Capacitor, registerPlugin } from "@capacitor/core";

const LocalDatabase = registerPlugin("LocalDatabase");

export const ensureNativeDatabaseFile = async () => {
  if (!Capacitor.isNativePlatform()) return { exists: false, mode: "web" };
  return LocalDatabase.ensureDatabase();
};

export const openNativeDatabaseFile = async () => {
  if (!Capacitor.isNativePlatform()) {
    throw new Error("فتح ملف قاعدة البيانات متاح داخل تطبيق Android فقط");
  }
  return LocalDatabase.openDatabaseFile();
};
