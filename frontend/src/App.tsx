import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { JobsPage } from "@/pages/JobsPage";
import { RunsPage } from "@/pages/RunsPage";
import { SearchesPage } from "@/pages/SearchesPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<JobsPage key="active" view="active" />} />
          <Route path="excluded" element={<JobsPage key="excluded" view="excluded" />} />
          <Route path="searches" element={<SearchesPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="runs" element={<RunsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
