import { PlaceholderPage } from "../components/PlaceholderPage";

// Заглушка админки (/admin). Экраны настройки появятся в #27–#29.
export default function AdminPage() {
  return (
    <PlaceholderPage
      testId="admin-page"
      title="Админка"
      description="Здесь будут настройки заведения, меню, столы и персонал."
    />
  );
}
