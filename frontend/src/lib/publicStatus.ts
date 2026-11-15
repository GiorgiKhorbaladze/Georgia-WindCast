import type { SiteSummary, SourceState, SystemStatus, WorkerState } from "./types";

/**
 * The status contract exposed to anonymous visitors (issue #18).
 *
 * Built from an explicit allow-list: operational details such as raw error text, retry/backoff
 * timing, failure counters, attempt times and the deployment environment stay private. Operators
 * read the full status on the host (docs/OPERATIONS.md). Adding a field here is a deliberate,
 * reviewed change that is covered by src/lib/__tests__/publicStatus.test.ts.
 */
export interface PublicStatus {
  generated_at: string;
  worker: { state: WorkerState; last_seen_at: string | null };
  sources: { id: string; state: SourceState; last_success_at: string | null }[];
  sites: SiteSummary[];
}

export function toPublicStatus(status: SystemStatus): PublicStatus {
  return {
    generated_at: status.generated_at,
    worker: { state: status.worker.state, last_seen_at: status.worker.last_seen_at },
    sources: status.sources.map((s) => ({ id: s.id, state: s.state, last_success_at: s.last_success_at })),
    sites: status.sites,
  };
}
