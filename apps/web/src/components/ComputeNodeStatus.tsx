"use client";

import { useEffect, useState } from "react";

/**
 * Hosted mode: keeps the owner's PC awake while this page is open, and says
 * so while the assistant is still starting there.
 *
 * Polls /api/node/status: every call counts as activity, which makes the
 * agent on the PC open its tunnel. Renders nothing when signed out, when
 * the app is not in hosted mode, or once the assistant is online.
 */

const ONLINE_POLL_MS = 30_000;
const WAKING_POLL_MS = 4_000;
// After this long without the tunnel, the PC is most likely switched off
const OFF_AFTER_MS = 90_000;

type State = "hidden" | "waking" | "off";

export default function ComputeNodeStatus() {
  const [state, setState] = useState<State>("hidden");

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let offlineSince: number | null = null;

    async function check() {
      if (stopped) return;
      if (document.visibilityState !== "visible") {
        timer = setTimeout(check, ONLINE_POLL_MS);
        return;
      }
      let next = ONLINE_POLL_MS;
      try {
        const response = await fetch("/api/node/status", { cache: "no-store" });
        if (response.status === 401) return; // signed out: nothing to keep awake
        const status = await response.json();
        if (status.mode !== "tunnel") return; // everything runs on this server
        if (status.online) {
          offlineSince = null;
          setState("hidden");
        } else {
          offlineSince ??= Date.now();
          setState(Date.now() - offlineSince > OFF_AFTER_MS ? "off" : "waking");
          next = WAKING_POLL_MS;
        }
      } catch {
        next = WAKING_POLL_MS;
      }
      if (!stopped) timer = setTimeout(check, next);
    }

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        check();
      }
    };

    check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (state === "hidden") return null;

  return (
    <div
      role="status"
      style={{
        position: "fixed",
        left: "50%",
        bottom: 16,
        transform: "translateX(-50%)",
        maxWidth: "calc(100% - 32px)",
        zIndex: 1000,
        padding: "10px 16px",
        borderRadius: 8,
        fontSize: 14,
        background: "var(--color-bg-elevated)",
        color: "var(--color-text-primary)",
        boxShadow: "0 2px 12px rgba(0, 0, 0, 0.15)",
      }}
    >
      {state === "waking"
        ? "Starting the assistant on the host computer… chat, search and the knowledge graph will be ready in a few seconds."
        : "The host computer seems to be off. Uploads are saved and will be processed when it is back."}
    </div>
  );
}
