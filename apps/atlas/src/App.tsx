import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";

import { AtlasShell } from "./components/AtlasShell";
import { AdvancedPage } from "./pages/AdvancedPage";
import { CodeRunnerPage } from "./pages/CodeRunnerPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WorkspacePage } from "./pages/WorkspacePage";
import { useAtlasStore } from "./store/useAtlasStore";

const queryClient = new QueryClient();

function ThemeBridge() {
  const theme = useAtlasStore((state) => state.theme);
  const crtScanlines = useAtlasStore((state) => state.crtScanlines);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const isCrt = theme === "crt-green" || theme === "crt-amber";
    if (isCrt && crtScanlines) {
      document.documentElement.dataset.scanlines = "on";
    } else {
      delete document.documentElement.dataset.scanlines;
    }
    document.title = "Atlas";
  }, [theme, crtScanlines]);

  return null;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeBridge />
      <HashRouter>
        <Routes>
          <Route element={<CodeRunnerPage />} path="/runner/:token" />
          <Route element={<AtlasShell />} path="/">
            <Route element={<Navigate replace to="/workspace" />} index />
            <Route element={<WorkspacePage />} path="workspace" />
            <Route element={<DiscoveryPage />} path="discovery" />
            <Route element={<AdvancedPage />} path="advanced" />
            <Route element={<SettingsPage />} path="settings" />
            <Route element={<Navigate replace to="/workspace" />} path="*" />
          </Route>
        </Routes>
      </HashRouter>
    </QueryClientProvider>
  );
}

export default App;
