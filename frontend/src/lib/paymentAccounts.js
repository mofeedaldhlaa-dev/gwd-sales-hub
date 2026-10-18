import api from "@/lib/api";
import { apiUrl } from "@/lib/apiConfig";

export const PORTAL_PAYMENT_ACCOUNTS_URL = "/public/card-order/banks?show_in=portal";

export const fetchPortalPaymentAccounts = async () => {
  const response = await api.get(PORTAL_PAYMENT_ACCOUNTS_URL);
  return Array.isArray(response.data) ? response.data : [];
};

export const paymentInstructionImageUrl = (account, variant = "display") => {
  const path = variant === "thumbnail"
    ? (account?.instruction_image_thumbnail_path || account?.instruction_image_path)
    : (account?.instruction_image_display_path || account?.instruction_image_path);
  return path ? apiUrl(path) : "";
};
