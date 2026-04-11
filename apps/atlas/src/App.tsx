import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";

import { AtlasShell } from "./components/AtlasShell";
import { SettingsPage } from "./pages/SettingsPage";
import { WorkspacePage } from "./pages/WorkspacePage";
import { useAtlasStore } from "./store/useAtlasStore";

const queryClient = new QueryClient();

function ThemeBridge() {
  const theme = useAtlasStore((state) => state.theme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.title = "Atlas";
  }, [theme]);

  return null;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeBridge />
      <HashRouter>
        <Routes>
          <Route element={<AtlasShell />} path="/">
            <Route element={<Navigate replace to="/workspace" />} index />
            <Route element={<WorkspacePage />} path="workspace" />
            <Route element={<SettingsPage />} path="settings" />
            <Route element={<Navigate replace to="/workspace" />} path="*" />
          </Route>
        </Routes>
      </HashRouter>
    </QueryClientProvider>
  );
}

export default App;
