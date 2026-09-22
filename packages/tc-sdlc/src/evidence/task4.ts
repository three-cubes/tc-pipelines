import type { KeyObject } from "node:crypto";

import type { RunReceipt } from "./index.js";
import type { AutomaticRecoveryReceipt } from "../maintenance/index.js";
import type { InputDigest, TrustBoundary } from "../schema/types.js";

export type TreeMutation = Readonly<{
  path: string;
  kind: "add" | "delete" | "content" | "mode" | "symlink";
  before?: InputDigest;
  after?: InputDigest;
}>;

export type PreparationReceipt = Readonly<{
  schema: "tc.sdlc/preparation-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  declarationDigest: string;
  catalogueDigest: string;
  lockDigest: string;
  recovery: AutomaticRecoveryReceipt;
  finalTreeDigest: string;
  firstPass: Readonly<{
    mutations: readonly TreeMutation[];
    mutationCount: number;
    mutationsTruncated: boolean;
    scheduler?: RunReceipt;
  }>;
  secondPass: Readonly<{
    mutations: readonly TreeMutation[];
    mutationCount: number;
    mutationsTruncated: boolean;
    scheduler?: RunReceipt;
  }>;
}>;

export type EvaluationTaskEvidence = Readonly<{
  key: string;
  identity: string;
  mode: "evaluate";
  trustBoundary: TrustBoundary;
  inputs: readonly InputDigest[];
  outputs: readonly InputDigest[];
}>;

export type EvaluationReceipt = Readonly<{
  schema: "tc.sdlc/evaluation-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  source: Readonly<{ commit: string; treeDigest: string }>;
  declarationDigest: string;
  catalogueDigest: string;
  lockDigest: string;
  environmentClass: string;
  producer: string;
  recovery: AutomaticRecoveryReceipt;
  tasks: readonly EvaluationTaskEvidence[];
  scheduler?: RunReceipt;
  mutations: readonly TreeMutation[];
  mutationCount: number;
  mutationsTruncated: boolean;
}>;

export type EvaluationCandidate = Omit<
  EvaluationReceipt,
  | "scheduler"
  | "mutations"
  | "mutationCount"
  | "mutationsTruncated"
  | "status"
  | "reason"
  | "recovery"
>;

export type SignedEvaluationReceipt = Readonly<{
  receipt: EvaluationReceipt;
  signature: Readonly<{
    algorithm: "Ed25519";
    producer: string;
    keyId: string;
    signedAt: string;
    expiresAt: string;
    value: string;
  }>;
}>;

export type EvaluationSigner = Readonly<{
  producer: string;
  keyId: string;
  privateKey: KeyObject | string;
  signedAt: string;
  expiresAt: string;
}>;

export type EvidencePolicy = Readonly<{
  now: string;
  producers: Readonly<
    Record<string, Readonly<{ keyId: string; publicKey: KeyObject | string }>>
  >;
}>;
