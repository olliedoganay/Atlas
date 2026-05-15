export type DesktopPlatform = "windows" | "macos" | "linux" | "unknown";

export function detectDesktopPlatform(platform = navigator.platform, userAgent = navigator.userAgent): DesktopPlatform {
  const value = `${platform} ${userAgent}`.toLowerCase();
  if (value.includes("win")) {
    return "windows";
  }
  if (value.includes("mac")) {
    return "macos";
  }
  if (value.includes("linux") || value.includes("x11") || value.includes("wayland")) {
    return "linux";
  }
  return "unknown";
}

export function platformShellName(platform: DesktopPlatform) {
  if (platform === "windows") {
    return "PowerShell";
  }
  if (platform === "macos") {
    return "Terminal";
  }
  return "Terminal";
}

export function ollamaInstallCopy(platform: DesktopPlatform) {
  if (platform === "windows") {
    return "Download the Windows app, install it, and leave Ollama running in the background.";
  }
  if (platform === "macos") {
    return "Download the macOS app, install it, and leave Ollama running from the menu bar.";
  }
  if (platform === "linux") {
    return "Install Ollama for your distro, start the service, and leave it running in the background.";
  }
  return "Install Ollama for this machine and leave it running in the background.";
}
