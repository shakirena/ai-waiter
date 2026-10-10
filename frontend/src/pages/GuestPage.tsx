import { useParams } from "react-router-dom";

import { PlaceholderPage } from "../components/PlaceholderPage";

// Заглушка интерфейса гостя (/t/:token). Чат и корзина появятся в #13.
export default function GuestPage() {
  const { token = "" } = useParams();

  return (
    <PlaceholderPage
      testId="guest-page"
      title="Гость"
      description="Здесь будет чат с ИИ-официантом: меню, корзина и заказ."
    >
      <p className="text-sm text-gray-500">
        Код стола:{" "}
        <span data-testid="guest-table-token" className="font-mono break-all">
          {token}
        </span>
      </p>
    </PlaceholderPage>
  );
}
