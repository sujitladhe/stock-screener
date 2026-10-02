import { useEffect, useState } from "react";

/**
 * Drawers in this app are mounted only while open (the parent page
 * conditionally renders them), so without this they'd just appear
 * already in their "open" position -- the CSS transition needs the
 * class to change AFTER mount to have something to animate from.
 */
export function useDrawerMount() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return mounted;
}
