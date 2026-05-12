export type SettingsSection = "general" | "profiles" | "models" | "connections" | "data" | "about";

const SETTINGS_SECTION_IDS: readonly SettingsSection[] = [
  "general",
  "profiles",
  "models",
  "connections",
  "data",
  "about",
];

export const PROFILE_SETTINGS_PATH = "/settings?section=profiles";

export function normalizeSettingsSection(value: string | null | undefined): SettingsSection {
  return SETTINGS_SECTION_IDS.includes(value as SettingsSection) ? (value as SettingsSection) : "general";
}
