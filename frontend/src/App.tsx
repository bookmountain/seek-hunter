import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { InsightsPage } from "@/pages/InsightsPage";
import { JobsPage } from "@/pages/JobsPage";
import { RunsPage } from "@/pages/RunsPage";
import { SearchesPage } from "@/pages/SearchesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TailorPage } from "@/pages/TailorPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<JobsPage key="active" view="active" />} />
          <Route path="excluded" element={<JobsPage key="excluded" view="excluded" />} />
          <Route path="searches" element={<SearchesPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="runs" element={<RunsPage />} />
          <Route path="jobs/:id/tailor" element={<TailorPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
