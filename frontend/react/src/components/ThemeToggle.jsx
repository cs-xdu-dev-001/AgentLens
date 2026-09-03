import { useEffect, useState } from "react";
import { Tooltip } from "./Tooltip.jsx";

const THEME_STORAGE_KEY = "knowflow-theme";
const LIGHT_THEME = "mono-light";
const DARK_THEME = "mono-dark";

function normalizeTheme(theme) {
  return theme === DARK_THEME ? DARK_THEME : LIGHT_THEME;
}

function getInitialTheme() {
  if (typeof window === "undefined") return LIGHT_THEME;
  return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
}

function SunIcon() {
  return (
    <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
      <circle cx={"12"} cy={"12"} r={"4.3"} />
      <path d={"M12 2.6v2.2M12 19.2v2.2M4.8 4.8l1.6 1.6M17.6 17.6l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.8 19.2l1.6-1.6M17.6 6.4l1.6-1.6"} />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
      <path d={"M20.1 14.7A7.7 7.7 0 0 1 9.3 3.9 8.3 8.3 0 1 0 20.1 14.7Z"} />
    </svg>
  );
}

export function ThemeToggle({ className = "" }) {
  const [theme, setTheme] = useState(getInitialTheme);
  const isDark = theme === DARK_THEME;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const handleThemeToggle = () => {
    setTheme((current) => (current === DARK_THEME ? LIGHT_THEME : DARK_THEME));
  };

  return (
    <Tooltip content={isDark ? "切换到日间模式" : "切换到夜间模式"} side={"bottom"}>
      <button
        className={["theme-toggle", className].filter(Boolean).join(" ")}
        id={"theme-toggle-btn"}
        type={"button"}
        aria-pressed={isDark}
        aria-label={isDark ? "切换到日间模式" : "切换到夜间模式"}
        onClick={handleThemeToggle}
      >
        {isDark ? <MoonIcon /> : <SunIcon />}
      </button>
    </Tooltip>
  );
}
