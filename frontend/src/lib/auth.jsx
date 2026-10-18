import { createContext, useContext, useEffect, useState } from "react";
import api, { errText } from "./api";
import { deviceId } from "./utils";
import { isOnline } from "./offline";

const Ctx = createContext(null);
const USER_KEY = "jwd_cached_user";

const readCachedUser = () => {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; }
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(undefined);
  const [loginEpoch, setLoginEpoch] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const restore = async () => {
      const tok = localStorage.getItem("jwd_token");
      if (!tok) { if (!cancelled) setUser(null); return; }
      const cached = readCachedUser();
      if (!isOnline() && cached) {
        if (!cancelled) setUser(cached);
        return;
      }
      try {
        const r = await api.get("/auth/me");
        if (cancelled) return;
        localStorage.setItem(USER_KEY, JSON.stringify(r.data));
        setUser(r.data);
      } catch (e) {
        if (!isOnline() && cached) {
          if (!cancelled) setUser(cached);
        } else {
          localStorage.removeItem("jwd_token");
          localStorage.removeItem(USER_KEY);
          if (!cancelled) setUser(null);
        }
      }
    };
    restore();
    return () => { cancelled = true; };
  }, []);

  const login = async (username, password) => {
    try {
      setError("");
      const r = await api.post("/auth/login", { username, password, device_id: deviceId() });
      localStorage.setItem("jwd_token", r.data.token);
      localStorage.setItem(USER_KEY, JSON.stringify(r.data.user));
      setUser(r.data.user);
      setLoginEpoch((value) => value + 1);
      return true;
    } catch (e) {
      const cached = readCachedUser();
      if (!isOnline() && cached && cached.username === username) {
        setUser(cached);
        return true;
      }
      setError(errText(e));
      return false;
    }
  };

  const logout = () => {
    localStorage.removeItem("jwd_token");
    localStorage.removeItem(USER_KEY);
    setUser(null);
    window.location.href = "/mof30";
  };

  const hasPerm = (p) => {
    if (user?.role === "admin") return true;
    const permissions = new Set(user?.permissions || []);
    const check = (value) => {
      if (!value) return false;
      if (permissions.has(value)) return true;
      const base = String(value).split(".")[0];
      return Boolean(base && permissions.has(base));
    };
    // a permission may be given as a single key or as a list of alternatives
    if (Array.isArray(p)) return p.some(check);
    return check(p);
  };

  return <Ctx.Provider value={{ user, login, logout, error, hasPerm, loginEpoch }}>{children}</Ctx.Provider>;
};

export const useAuth = () => useContext(Ctx);
