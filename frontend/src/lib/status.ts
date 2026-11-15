import type { Tone } from "@/components/StatusBadge";

import type { Freshness, WorkerState } from "./types";

export function freshnessTone(f: Freshness): Tone {
  switch (f) {
    case "fresh":
      return "ok";
    case "stale":
    case "unverified":
      return "warn";
    case "unavailable":
      return "bad";
  }
}

export function workerTone(s: WorkerState): Tone {
  switch (s) {
    case "running":
      return "ok";
    case "stale":
      return "bad";
    case "never_seen":
      return "neutral";
  }
}
