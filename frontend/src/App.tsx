import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import NotFoundPage from "./pages/NotFoundPage";

// Три интерфейса одного приложения (ТЗ 8). Каждый загружается отдельным чанком,
// чтобы гость не скачивал код панели официанта и админки.
const GuestPage = lazy(() => import("./pages/GuestPage"));
const StaffPage = lazy(() => import("./pages/StaffPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));

function PageLoading() {
  return (
    <div
      data-testid="page-loading"
      role="status"
      className="flex min-h-dvh items-center justify-center px-4 text-gray-500"
    >
      Загрузка…
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Routes>
        <Route path="/t/:token/*" element={<GuestPage />} />
        <Route path="/staff/*" element={<StaffPage />} />
        <Route path="/admin/*" element={<AdminPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  );
}
