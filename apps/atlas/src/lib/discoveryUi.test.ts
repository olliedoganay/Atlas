import { describe, expect, it } from "vitest";

import {
  discoveryStatusLabel,
  discoveryStatusTone,
  formatDiscoveryFitLabel,
  formatDiscoveryMemory,
  formatGpuMemoryLabel,
  formatGpuSourceLabel,
  selectPrimaryGpu,
} from "./discoveryUi";

describe("discoveryUi helpers", () => {
  it("maps readiness states to status pill tones", () => {
    expect(discoveryStatusTone("ready")).toBe("online");
    expect(discoveryStatusTone("memory-degraded")).toBe("warning");
    expect(discoveryStatusTone("runtime-unavailable")).toBe("offline");
    expect(discoveryStatusTone("chat-blocked")).toBe("warning");
  });

  it("renders short labels for readiness states", () => {
    expect(discoveryStatusLabel("ready")).toBe("Atlas ready");
    expect(discoveryStatusLabel("chat-blocked")).toBe("Chat blocked");
  });

  it("formats fit and memory labels for the discovery page", () => {
    expect(formatDiscoveryFitLabel("cpu-only")).toBe("CPU only");
    expect(formatDiscoveryFitLabel("too-large")).toBe("Too large");
    expect(formatDiscoveryMemory(12)).toBe("12 GB");
    expect(formatDiscoveryMemory(7.5)).toBe("7.5 GB");
    expect(formatDiscoveryMemory(null)).toBe("Unknown");
  });

  it("prefers dedicated GPUs and renders clearer GPU labels", () => {
    const primary = selectPrimaryGpu([
      { name: "Intel UHD", memory_gb: null, kind: "integrated", memory_source: "shared" },
      { name: "RTX 4080 Laptop GPU", memory_gb: 12, kind: "dedicated", memory_source: "nvidia-smi" },
    ]);
    expect(primary?.name).toBe("RTX 4080 Laptop GPU");
    expect(formatGpuMemoryLabel(primary ?? null)).toBe("12 GB VRAM");
    expect(formatGpuSourceLabel(primary ?? null)).toBe("Measured from NVIDIA runtime.");
    expect(formatGpuMemoryLabel({ name: "Intel UHD", memory_gb: null, kind: "integrated", memory_source: "shared" })).toBe(
      "Integrated graphics",
    );
  });
});
