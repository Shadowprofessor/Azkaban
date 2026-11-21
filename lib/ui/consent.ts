"use client";

import { useSyncExternalStore } from "react";

const KEY = "azk.consent.v1";
const listeners = new Set<() => void>();
let memory: boolean | null = null;

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "yes";
  } catch {
    return false;
  }
}

export function setConsent(v: boolean) {
  try {
    if (v) window.localStorage.setItem(KEY, "yes");
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: consent lasts for this page only */
    memory = v;
  }
  listeners.forEach((l) => l());
}

/** null while hydrating (server render), then the stored consent. */
export function useConsent(): boolean | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => memory ?? read(),
    () => null,
  );
}
