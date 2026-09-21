export type MaintenanceMode = "dry-run" | "apply";

export type MaintenanceOptions = Readonly<{
  stateRoot: string;
  receiptPath: string;
  mode: MaintenanceMode;
  temporaryRoot?: string;
  retentionHours?: number;
  uvExecutable?: string;
  pnpmExecutable?: string;
  buildxExecutable?: string;
  dockerBuilder?: string;
  maxEntries?: number;
  cleanupWorkers?: number;
}>;

export type FilesystemIdentity = Readonly<{
  device: string;
  inode: string;
  birthtimeNanoseconds: string;
}>;

export type MaintenanceEntry = Readonly<{
  kind: "temporary" | "bootstrap-state" | "quarantine";
  path: string;
  bytes?: number;
  identity: FilesystemIdentity;
}>;

export type MaintenanceRetainedEntry = Readonly<{
  path: string;
  reason:
    | "active"
    | "dirty_worktree"
    | "retention_window"
    | "foreign"
    | "linked"
    | "changed_during_apply"
    | "referenced"
    | "reference_metadata_absent"
    | "inspection_failed";
}>;

export type MaintenanceToolReceipt = Readonly<{
  status: "not_requested" | "planned" | "pruned" | "failed";
  reclaimedBytes: number;
  detail?: string;
}>;

export type MaintenanceReceipt = Readonly<{
  schema: "tc.sdlc/maintenance-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  mode: MaintenanceMode;
  platform: NodeJS.Platform;
  stateRoot: string;
  temporaryRoot: string;
  retentionHours: number;
  candidateCount: number;
  removedCount: number;
  reclaimedBytes: number;
  entriesTruncated: boolean;
  cleanupWorkers: number;
  peakCleanupWorkers: number;
  cleanupFailures: number;
  candidates: readonly MaintenanceEntry[];
  retained: readonly MaintenanceRetainedEntry[];
  tools: Readonly<{
    uv: MaintenanceToolReceipt;
    pnpm: MaintenanceToolReceipt;
    buildkit: MaintenanceToolReceipt;
  }>;
}>;

export type AutomaticRecoveryReceipt = Readonly<{
  schema: "tc.sdlc/automatic-recovery/v1";
  status: "succeeded" | "partial";
  boundary: "os-temporary-root";
  retentionHours: 48;
  candidateCount: number;
  removedCount: number;
  reclaimedBytes: number;
  entriesTruncated: boolean;
  cleanupFailures: number;
  peakCleanupWorkers: number;
}>;
