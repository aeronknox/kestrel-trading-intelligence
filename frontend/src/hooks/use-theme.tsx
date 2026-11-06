"use client";

import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

type Theme = "dark" | "light";
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({ theme: "dark", toggle: () => {} });
const STORAGE_KEY = "ti-theme";

/** Inline script (rendered in <head>) that applies the saved theme before paint. */
export const themeInitScript = `(function(){try{var t=localStorage.getItem("${STORAGE_KEY}");var c=document.documentElement.classList;c.remove("dark","light");c.add(t==="light"?"light":"dark");}catch(e){}})();`;

// The <html> class is the source of truth (set before paint by themeInitScript).
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const getSnapshot = (): Theme => (document.documentElement.classList.contains("light") ? "light" : "dark");
const getServerSnapshot = (): Theme => "dark";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggle = useCallback(() => {
    const next: Theme = getSnapshot() === "dark" ? "light" : "dark";
    const cl = document.documentElement.classList;
    cl.remove("dark", "light");
    cl.add(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage unavailable */
    }
    listeners.forEach((l) => l());
  }, []);

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
