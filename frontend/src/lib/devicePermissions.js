import { Capacitor } from "@capacitor/core";
import { Contacts } from "@capacitor-community/contacts";
import { Filesystem } from "@capacitor/filesystem";

export const isNativeApp = () => Capacitor.isNativePlatform();

export async function checkDevicePermissions() {
  if (!isNativeApp()) return { contacts: "unsupported", storage: "unsupported" };
  const [contacts, storage] = await Promise.all([
    Contacts.checkPermissions().catch(() => ({ contacts: "prompt" })),
    Filesystem.checkPermissions().catch(() => ({ publicStorage: "prompt" })),
  ]);
  return { contacts: contacts.contacts, storage: storage.publicStorage || storage.storage || "prompt" };
}

export async function requestDevicePermissions() {
  if (!isNativeApp()) return { contacts: "unsupported", storage: "unsupported" };
  const contacts = await Contacts.requestPermissions().catch(() => ({ contacts: "denied" }));
  const storage = await Filesystem.requestPermissions().catch(() => ({ publicStorage: "denied" }));
  return { contacts: contacts.contacts, storage: storage.publicStorage || storage.storage || "prompt" };
}

export async function pickNativeContact() {
  if (!isNativeApp()) return null;
  const permission = await Contacts.requestPermissions();
  if (permission.contacts !== "granted" && permission.contacts !== "limited") return null;
  const result = await Contacts.pickContact({ projection: { name: true, phones: true } });
  const contact = result?.contact;
  const phone = contact?.phones?.find((item) => item?.number)?.number || "";
  const name = contact?.name?.display || [contact?.name?.given, contact?.name?.family].filter(Boolean).join(" ");
  return phone ? { phone: String(phone).replace(/[^0-9+]/g, ""), name: name || "" } : null;
}
