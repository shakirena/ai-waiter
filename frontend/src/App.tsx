import { Route, Routes } from "react-router-dom";

// Заглушки маршрутов трёх интерфейсов (ТЗ 8). Экраны появятся в #13, #21, #27–#29.
export function GuestPlaceholder() {
  return <main className="p-4">Гость</main>;
}

export function StaffPlaceholder() {
  return <main className="p-4">Официант</main>;
}

export function AdminPlaceholder() {
  return <main className="p-4">Админка</main>;
}

export function NotFound() {
  return <main className="p-4">Страница не найдена</main>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/t/:token/*" element={<GuestPlaceholder />} />
      <Route path="/staff/*" element={<StaffPlaceholder />} />
      <Route path="/admin/*" element={<AdminPlaceholder />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
