import { sign, verify } from "node:crypto";

import { canonicalJson } from "../canonical.js";
import { SdlcError } from "../errors.js";
import type {
  EvaluationCandidate,
  EvaluationReceipt,
  EvaluationSigner,
  EvidencePolicy,
  SignedEvaluationReceipt,
} from "./task4.js";

export function evaluationCandidate(
  receipt: EvaluationReceipt,
): EvaluationCandidate {
  return {
    schema: receipt.schema,
    source: receipt.source,
    declarationDigest: receipt.declarationDigest,
    catalogueDigest: receipt.catalogueDigest,
    lockDigest: receipt.lockDigest,
    bootstrapContext: receipt.bootstrapContext,
    environmentClass: receipt.environmentClass,
    producer: receipt.producer,
    tasks: receipt.tasks,
  };
}

function payload(
  receipt: EvaluationReceipt,
  signature: Omit<SignedEvaluationReceipt["signature"], "value">,
): Buffer {
  return Buffer.from(canonicalJson({ receipt, signature }), "utf8");
}

export function signEvaluationReceipt(
  receipt: EvaluationReceipt,
  signer: EvaluationSigner,
): SignedEvaluationReceipt {
  if (receipt.producer !== signer.producer) {
    throw new SdlcError("EVIDENCE_PRODUCER_INVALID", "signer does not own receipt producer identity");
  }
  const metadata = {
    algorithm: "Ed25519" as const,
    producer: signer.producer,
    keyId: signer.keyId,
    signedAt: signer.signedAt,
    expiresAt: signer.expiresAt,
  };
  return {
    receipt,
    signature: {
      ...metadata,
      value: sign(null, payload(receipt, metadata), signer.privateKey).toString("base64"),
    },
  };
}

export function admitEvaluationReceipt(
  signed: SignedEvaluationReceipt,
  candidate: EvaluationCandidate,
  policy: EvidencePolicy,
): true {
  if (
    signed === undefined ||
    signed.signature === undefined ||
    signed.receipt === undefined ||
    signed.signature.algorithm !== "Ed25519"
  ) {
    throw new SdlcError("EVIDENCE_SIGNATURE_INVALID", "signed evaluation evidence is required");
  }
  const receipt = signed.receipt;
  if (receipt.status !== "succeeded" || receipt.scheduler?.status !== "succeeded") {
    throw new SdlcError("EVIDENCE_STATUS_INVALID", "only succeeded terminal evidence is admissible");
  }
  if (
    receipt.tasks.length === 0 ||
    receipt.tasks.some(
      (task) =>
        task.mode !== "evaluate" ||
        task.trustBoundary !== "portable" ||
        task.outputs.length === 0,
    )
  ) {
    throw new SdlcError("EVIDENCE_BOUNDARY_INVALID", "only portable tasks with declared outputs are reusable");
  }
  if (canonicalJson(evaluationCandidate(receipt)) !== canonicalJson(candidate)) {
    throw new SdlcError("EVIDENCE_CANDIDATE_MISMATCH", "receipt does not match the candidate bindings");
  }
  const allowed = policy.producers[signed.signature.producer];
  if (
    allowed === undefined ||
    allowed.keyId !== signed.signature.keyId ||
    receipt.producer !== signed.signature.producer
  ) {
    throw new SdlcError("EVIDENCE_PRODUCER_INVALID", "producer is not allowed by admission policy");
  }
  const now = Date.parse(policy.now);
  const signedAt = Date.parse(signed.signature.signedAt);
  const expiresAt = Date.parse(signed.signature.expiresAt);
  if (![now, signedAt, expiresAt].every(Number.isFinite) || signedAt > now) {
    throw new SdlcError("EVIDENCE_TIME_INVALID", "signature time is invalid or from the future");
  }
  if (expiresAt < now) {
    throw new SdlcError("EVIDENCE_EXPIRED", "signed evidence has expired");
  }
  const { value, ...metadata } = signed.signature;
  if (!verify(null, payload(receipt, metadata), allowed.publicKey, Buffer.from(value, "base64"))) {
    throw new SdlcError("EVIDENCE_SIGNATURE_INVALID", "evaluation signature is invalid");
  }
  return true;
}
