"use client";

import { useEffect } from "react";
import { ThemeProvider, useTheme } from "next-themes";

// The theme is only ever "light" or "dark" - there is no System option in the UI.
// On first load (nothing in localStorage) the OS preference decides which one to
// start on, and that choice is written to localStorage immediately so every later
// load is an explicit user setting rather than a live follow of the OS.
//
// enableSystem stays on purely so next-themes' pre-hydration script can resolve
// the OS preference before first paint; without it a dark-OS user would see a
// flash of light before this effect runs.
function ThemeInitializer() {
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    if (theme === "light" || theme === "dark") return;
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    setTheme(prefersDark ? "dark" : "light");
  }, [theme, setTheme]);

  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <ThemeInitializer />
      {children}
    </ThemeProvider>
  );
}
