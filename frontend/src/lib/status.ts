/**
 * Status vocabulary.
 *
 * One place maps backend enums and capability states onto a restrained visual
 * language. Colour is never the only signal: every consumer renders an icon
 * and a text label alongside the tone.
 */

export type Tone =
  | "verified"
  | "candidate"
  | "warning"
  | "danger"
  | "cross-chain"
  | "decision"
  | "neutral"
  | "live";

export interface StatusDescriptor {
  tone: Tone;
  label: string;
  /** Longer, plain-language meaning for tooltips. */
  meaning: string;
}

export function capabilityStatus(status: string): StatusDescriptor {
  switch (status) {
    case "available":
      return { tone: "verified", label: "Available", meaning: "Implemented and usable in this deployment." };
    case "configured":
      return { tone: "warning", label: "Configured", meaning: "Settings present; current live operation is not verified." };
    case "partial":
      return { tone: "warning", label: "Partial", meaning: "Implemented within a bounded scope; important limits remain." };
    case "not_built":
      return { tone: "neutral", label: "Not built", meaning: "No implementation exists." };
    case "not_configured":
      return { tone: "neutral", label: "Not configured", meaning: "Implementation may exist but no configuration/credentials are present." };
    case "blocked":
      return { tone: "danger", label: "Blocked", meaning: "Cannot proceed with available data or approvals." };
    default:
      return { tone: "neutral", label: status || "Unknown", meaning: "Unknown status." };
  }
}

export function implementationStatus(status: string): StatusDescriptor {
  switch (status) {
    case "implemented":
      return { tone: "verified", label: "Implemented", meaning: "Code exists and has tests." };
    case "partial":
      return { tone: "warning", label: "Partial", meaning: "Code exists for part of the scope." };
    case "not_built":
      return { tone: "neutral", label: "Not built", meaning: "No code exists." };
    default:
      return { tone: "neutral", label: status || "Unknown", meaning: "Unknown." };
  }
}

export function endpointClass(endpoint: string): StatusDescriptor {
  switch (endpoint) {
    case "known_service":
      return { tone: "verified", label: "Verified service boundary", meaning: "A reviewed service-control claim covers this address at the trace instant." };
    case "deposit_candidate":
      return { tone: "candidate", label: "Candidate lead", meaning: "An observed relationship only; not ownership, service control, or guilt." };
    case "unresolved":
      return { tone: "neutral", label: "Unresolved", meaning: "Tracing stopped here without a supported boundary." };
    case "boundary":
      return { tone: "warning", label: "Coverage boundary", meaning: "A hop, event, time, or budget limit ended this branch." };
    default:
      return { tone: "neutral", label: endpoint || "Unknown", meaning: "Unknown endpoint class." };
  }
}

export function attributionStatus(status: string | null | undefined): StatusDescriptor {
  switch (status) {
    case "supported":
      return { tone: "verified", label: "Supported", meaning: "Backed by a reviewed, dated service-control claim." };
    case "inferred":
      return { tone: "warning", label: "Inferred", meaning: "Derived under a declared policy; not a reviewed claim." };
    case "candidate":
      return { tone: "candidate", label: "Candidate", meaning: "A lead only; no ownership or service control established." };
    case "conflicted":
      return { tone: "danger", label: "Conflicted", meaning: "Two evidence-backed claims disagree; both are preserved." };
    case "unresolved":
      return { tone: "neutral", label: "Unresolved", meaning: "No attribution was established." };
    case "unsupported":
      return { tone: "neutral", label: "Unsupported", meaning: "Out of the supported scope." };
    default:
      return { tone: "neutral", label: "—", meaning: "No attribution status recorded." };
  }
}

export function executionStatus(status: string | null | undefined): StatusDescriptor {
  switch (status) {
    case "success":
      return { tone: "verified", label: "Success", meaning: "Receipt reports a successful execution." };
    case "failed":
      return { tone: "danger", label: "Failed", meaning: "The transaction did not succeed." };
    case "reverted":
      return { tone: "danger", label: "Reverted", meaning: "The transaction reverted." };
    case "unknown":
      return { tone: "neutral", label: "Unknown", meaning: "Execution status was not established." };
    default:
      return { tone: "neutral", label: status || "Not recorded", meaning: "Execution status is not recorded." };
  }
}

export function coverageStatus(status: string | null | undefined): StatusDescriptor {
  switch (status) {
    case "complete_within_scope":
      return { tone: "verified", label: "Complete within scope", meaning: "Complete for the declared window — not knowledge of the whole chain." };
    case "partial":
      return { tone: "warning", label: "Partial coverage", meaning: "Provider gaps or budget limits left part of the window unread." };
    case "failed":
      return { tone: "danger", label: "Failed", meaning: "Acquisition failed. A failure is not an empty history." };
    case "unknown":
      return { tone: "neutral", label: "Unknown", meaning: "Coverage was not established." };
    default:
      return { tone: "neutral", label: "—", meaning: "No coverage status recorded." };
  }
}

export function linkageStatus(status: string): StatusDescriptor {
  switch (status) {
    case "COMPLETE":
      return { tone: "verified", label: "Complete", meaning: "Source burn, attestation, and destination receive are reconciled." };
    case "INCOMPLETE":
      return { tone: "warning", label: "Incomplete", meaning: "The link is missing a required stage." };
    case "FAILED":
      return { tone: "danger", label: "Failed", meaning: "The protocol transition failed." };
    case "AMBIGUOUS":
      return { tone: "warning", label: "Ambiguous", meaning: "More than one candidate transition matches." };
    default:
      return { tone: "neutral", label: status || "Unknown", meaning: "Unknown linkage status." };
  }
}

export function dataMode(mode: string): StatusDescriptor {
  switch (mode) {
    case "LIVE":
      return { tone: "live", label: "LIVE", meaning: "Captured directly from a chain provider in this run." };
    case "RECORDED_PUBLIC":
      return { tone: "cross-chain", label: "RECORDED PUBLIC", meaning: "Saved public-disclosure / replay evidence, not a live connection." };
    case "SYNTHETIC":
      return { tone: "candidate", label: "SYNTHETIC", meaning: "Deliberately fictional fixture data." };
    default:
      return { tone: "neutral", label: mode || "UNKNOWN", meaning: "Unknown data mode." };
  }
}

export function reviewState(state: string | null | undefined): StatusDescriptor {
  switch (state) {
    case "accepted":
      return { tone: "verified", label: "Accepted", meaning: "Human-reviewed and accepted." };
    case "unreviewed":
      return { tone: "candidate", label: "Unreviewed", meaning: "Not yet reviewed by a human." };
    case "rejected":
      return { tone: "danger", label: "Rejected", meaning: "Human-reviewed and rejected." };
    case "quarantined":
      return { tone: "warning", label: "Quarantined", meaning: "Set aside pending more evidence." };
    case "conflicted":
      return { tone: "warning", label: "Conflicted", meaning: "Conflicting evidence exists." };
    default:
      return { tone: "neutral", label: "—", meaning: "No review state recorded." };
  }
}

export function alertSeverity(value: string): StatusDescriptor {
  switch (value.toLowerCase()) {
    case "high":
      return { tone: "danger", label: "High", meaning: "Requires prompt review." };
    case "medium":
      return { tone: "warning", label: "Medium", meaning: "Review at the next opportunity." };
    case "low":
      return { tone: "neutral", label: "Low", meaning: "Informational." };
    default:
      return { tone: "neutral", label: value, meaning: "Severity not classified." };
  }
}
