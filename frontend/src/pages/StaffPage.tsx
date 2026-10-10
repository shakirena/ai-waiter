import { PlaceholderPage } from "../components/PlaceholderPage";

// Заглушка панели официанта (/staff). Лента заказов появится в #21.
export default function StaffPage() {
  return (
    <PlaceholderPage
      testId="staff-page"
      title="Официант"
      description="Здесь будет лента заказов и вызовов от гостей."
    />
  );
}
