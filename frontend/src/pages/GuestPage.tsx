import { useParams } from "react-router-dom";

import { GuestScreen } from "../guest/GuestScreen";

// Интерфейс гостя (/t/:token). key по токену: переход к QR другого стола внутри SPA
// начинает вход с чистого состояния (D-2 spec #9).
export default function GuestPage() {
  const { token = "" } = useParams();
  return <GuestScreen key={token} token={token} />;
}
