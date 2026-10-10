import type { ReactNode } from "react";

interface PlaceholderPageProps {
  /** Значение data-testid корневого элемента страницы. */
  testId: string;
  title: string;
  description: string;
  children?: ReactNode;
}

// Общий макет страниц-заглушек. Mobile-first (NFR-2): одна колонка, поля 16 px,
// ширина ограничена на больших экранах; длинный текст переносится, а не растягивает
// страницу, поэтому горизонтальной прокрутки нет и на 360 px.
export function PlaceholderPage({ testId, title, description, children }: PlaceholderPageProps) {
  return (
    <main
      data-testid={testId}
      className="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-4 px-4 py-8 text-gray-900"
    >
      <h1 data-testid={`${testId}-title`} className="text-2xl font-semibold break-words">
        {title}
      </h1>
      <p className="text-base text-gray-600 break-words">{description}</p>
      {children}
    </main>
  );
}
