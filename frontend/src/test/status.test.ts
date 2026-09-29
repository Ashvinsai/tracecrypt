import { describe, expect, it } from "vitest";
import { formatBaseUnits, truncate } from "../lib/format";
import {
  attributionStatus,
  capabilityStatus,
  coverageStatus,
  dataMode,
  endpointClass,
  linkageStatus,
  reviewState,
} from "../lib/status";

describe("exact amount formatting", () => {
  it("converts base units without floating point loss", () => {
    expect(formatBaseUnits("9391319", 6)).toBe("9.391319");
    expect(formatBaseUnits("1355910000", 6)).toBe("1355.910000");
    expect(formatBaseUnits("72140000", 6)).toBe("72.140000");
  });

  it("handles a full uint256-scale value exactly", () => {
    const huge = "115792089237316195423570985008687907853269984665640564039457584007913129639935";
    expect(formatBaseUnits(huge, 0)).toBe(huge);
    expect(formatBaseUnits(huge, 18)).toContain("115792089237316195423570985008687907");
  });

  it("never turns a missing amount into zero", () => {
    expect(formatBaseUnits(null, 6)).toBe("—");
    expect(formatBaseUnits("", 6)).toBe("—");
  });
});

describe("truncation keeps the full value copyable", () => {
  it("shortens long addresses but leaves short ones intact", () => {
    expect(truncate("0x38a1c011890bc95fd4b43b622e1432c859d097bc", 6, 4)).toBe("0x38a1…97bc");
    expect(truncate("TRON", 6, 4)).toBe("TRON");
    expect(truncate(null)).toBe("—");
  });
});

describe("verified VASP is never rendered like a candidate", () => {
  it("gives the two endpoint classes different tones and labels", () => {
    expect(endpointClass("known_service").tone).toBe("verified");
    expect(endpointClass("known_service").label).toMatch(/verified/i);
    expect(endpointClass("deposit_candidate").tone).toBe("candidate");
    expect(endpointClass("deposit_candidate").label).toMatch(/candidate/i);
    expect(endpointClass("known_service").tone).not.toBe(endpointClass("deposit_candidate").tone);
  });

  it("does not let a candidate look reviewed", () => {
    expect(reviewState("accepted").tone).toBe("verified");
    expect(reviewState("unreviewed").tone).toBe("candidate");
  });
});

describe("LIVE, RECORDED and SYNTHETIC are distinct", () => {
  it("assigns each mode its own label", () => {
    const labels = [dataMode("LIVE").label, dataMode("RECORDED_PUBLIC").label, dataMode("SYNTHETIC").label];
    expect(new Set(labels).size).toBe(3);
    expect(dataMode("RECORDED_PUBLIC").label).toMatch(/recorded/i);
    expect(dataMode("SYNTHETIC").label).toMatch(/synthetic/i);
  });
});

describe("coverage and capability states", () => {
  it("flags partial coverage as a warning, not success", () => {
    expect(coverageStatus("partial").tone).toBe("warning");
    expect(coverageStatus("complete_within_scope").tone).toBe("verified");
    expect(coverageStatus("failed").tone).toBe("danger");
  });

  it("keeps configured distinct from verified", () => {
    expect(capabilityStatus("configured").tone).not.toBe(capabilityStatus("available").tone);
    expect(capabilityStatus("not_built").label).toMatch(/not built/i);
    expect(capabilityStatus("not_configured").label).toMatch(/not configured/i);
  });

  it("distinguishes supported attribution from a candidate lead", () => {
    expect(attributionStatus("supported").tone).toBe("verified");
    expect(attributionStatus("candidate").tone).toBe("candidate");
  });
});

describe("CCTP linkage states", () => {
  it("renders COMPLETE, INCOMPLETE and FAILED differently", () => {
    expect(linkageStatus("COMPLETE").tone).toBe("verified");
    expect(linkageStatus("INCOMPLETE").tone).toBe("warning");
    expect(linkageStatus("FAILED").tone).toBe("danger");
    expect(linkageStatus("AMBIGUOUS").tone).toBe("warning");
  });
});
