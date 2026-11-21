"use client";

import { useEffect } from "react";
import { useConsent } from "@/lib/ui/consent";
import { agentSocket } from "@/lib/ui/socket";
import { Toasts } from "./Toasts";
import { FlowDrawer } from "./radar/FlowDrawer";

/** Opens the agent socket only after the operator has given consent. */
export function AgentProvider({ children }: { children: React.ReactNode }) {
  const consent = useConsent();
  useEffect(() => {
    if (consent) agentSocket.start();
    else agentSocket.stop();
  }, [consent]);
  return (
    <>
      {children}
      {consent && <FlowDrawer />}
      <Toasts />
    </>
  );
}
