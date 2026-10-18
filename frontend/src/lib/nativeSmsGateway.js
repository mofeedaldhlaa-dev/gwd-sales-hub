import { registerPlugin } from "@capacitor/core";

/**
 * Native SMS Gateway bridge. This module is for the authenticated administration
 * app only; never import it into the public customer portal.
 */
export const SmsGateway = registerPlugin("SmsGateway");

export async function requestSmsGatewayPermission() {
  return SmsGateway.requestSmsPermission();
}

export async function getSmsGatewayStatus() {
  return SmsGateway.checkStatus();
}

export async function syncSmsGatewaySenderIds(senderIdsCsv = "") {
  return SmsGateway.syncSenderIds({ senderIdsCsv: String(senderIdsCsv || "") });
}

export async function configureSmsGateway({ baseUrl, deviceId, secret, enabled = false }) {
  if (!baseUrl || !deviceId || !secret) {
    throw new Error("بيانات إعداد SMS Gateway غير مكتملة");
  }
  return SmsGateway.configure({ baseUrl, deviceId, secret, enabled });
}

export async function setSmsGatewayEnabled(enabled) {
  return SmsGateway.setEnabled({ enabled: Boolean(enabled) });
}

export async function flushSmsGatewayQueue() {
  return SmsGateway.flushPending();
}

export async function clearSmsGatewayQueue() {
  return SmsGateway.clearPending();
}
