"use client";

import { useEffect } from "react";
import { ThemeProvider, useTheme } from "next-themes";

// enableSystem stays on only so next-themes can resolve the OS choice before paint
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
