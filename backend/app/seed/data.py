"""Демо-данные сида (ADR-7.12): вымышленное заведение «Demo Restoran».

Все значения придуманы: названия, цены, составы и токены не относятся к реальному заведению.
Модуль — только данные и чистые функции, к БД не обращается (это делает ``app.seed.loader``).

Идентификаторы:

- у сущностей с естественным ключом (залы, столы, категории, позиции, аллергены, строки
  корзины) ``id`` генерирует приложение (UUIDv7), а повторный запуск находит строку по
  естественному ключу;
- у сущностей без естественного ключа (заведение, визит, сообщения, заказ, строки заказа,
  событие заказа) ``id`` фиксированный — ``demo_id(...)`` (UUIDv5 от постоянного пространства
  имён), поэтому повторный запуск их не дублирует.

QR-токены столов детерминированы и годятся только для разработки: сид отказывается работать
при ``APP_ENV=prod``. Азербайджанские названия нужно проверить носителю языка (ТЗ AI-6).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.models.enums import DEFAULT_PRICE_TIER, Lang, MessageRole, TableType, WeightUnit

# Постоянное пространство имён для UUIDv5 демо-сущностей (значение произвольное, не секрет).
DEMO_NAMESPACE: Final = uuid.UUID("5eed0000-7a1e-4d0e-8a00-00000000d3e0")


def demo_id(name: str) -> uuid.UUID:
    """Фиксированный UUID демо-сущности по её имени (одинаков на любой машине)."""
    return uuid.uuid5(DEMO_NAMESPACE, name)


DEMO_TENANT_ID: Final = demo_id("tenant")
VIP_PRICE_TIER: Final = "vip"


@dataclass(frozen=True, slots=True)
class TenantSeed:
    id: uuid.UUID
    name: str
    currency: str
    timezone: str
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HallSeed:
    key: str
    name: str
    sort_key: str


@dataclass(frozen=True, slots=True)
class TableSeed:
    hall: str  # HallSeed.key
    name: str
    qr_token: str
    type: TableType = TableType.TABLE
    price_tier: str = DEFAULT_PRICE_TIER
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CategorySeed:
    external_id: str
    pos_name: str
    name_az: str
    name_ru: str
    sort_key: str


@dataclass(frozen=True, slots=True)
class DishSeed:
    """Позиция меню: кассовые поля (``pos_name``, цены, наличие) и данные админа (мета, аллергены).

    ``allergens_verified = False`` — состав аллергенов неизвестен, даже если список заполнен (AI-2).
    """

    external_id: str
    category: str  # CategorySeed.external_id
    pos_name: str
    prices: Mapping[str, Decimal]
    name_az: str
    name_ru: str
    description_az: str
    description_ru: str
    sort_key: str
    station: str
    allergens_verified: bool = False
    allergens: tuple[str, ...] = ()
    spice_level: int | None = None
    prep_minutes: int | None = None
    weight_amount: Decimal | None = None
    weight_unit: WeightUnit | None = None
    tags: tuple[str, ...] = ()
    is_available: bool = True
    is_hidden: bool = False


@dataclass(frozen=True, slots=True)
class CartLineSeed:
    dish: str  # DishSeed.external_id
    qty: int
    comment: str = ""


@dataclass(frozen=True, slots=True)
class MessageSeed:
    id: uuid.UUID
    role: MessageRole
    text: str


@dataclass(frozen=True, slots=True)
class OrderLineSeed:
    id: uuid.UUID
    dish: str  # DishSeed.external_id
    qty: int
    comment: str = ""


@dataclass(frozen=True, slots=True)
class VisitSeed:
    id: uuid.UUID
    table_token: str  # TableSeed.qr_token
    lang: Lang
    messages: tuple[MessageSeed, ...]
    cart: tuple[CartLineSeed, ...]


@dataclass(frozen=True, slots=True)
class OrderSeed:
    id: uuid.UUID
    idempotency_key: uuid.UUID
    created_event_id: uuid.UUID
    lines: tuple[OrderLineSeed, ...]


TENANT: Final = TenantSeed(
    id=DEMO_TENANT_ID,
    name="Demo Restoran",
    currency="AZN",
    timezone="Asia/Baku",
    languages=(Lang.AZ.value, Lang.RU.value),
)

HALLS: Final[tuple[HallSeed, ...]] = (
    HallSeed(key="main", name="Основной зал", sort_key="010"),
    HallSeed(key="terrace", name="Терраса", sort_key="020"),
)


def dev_token(number: int) -> str:
    """Детерминированный QR-токен демо-стола: base64url, 22 символа (QR_TOKEN_PATTERN), только для dev."""
    return f"demo-table-{number:02d}-dev-only"


TABLES: Final[tuple[TableSeed, ...]] = (
    TableSeed(hall="main", name="Стол 1", qr_token=dev_token(1)),
    TableSeed(hall="main", name="Стол 2", qr_token=dev_token(2)),
    TableSeed(hall="main", name="Стол 3", qr_token=dev_token(3)),
    TableSeed(
        hall="main",
        name="Кабинет VIP",
        qr_token=dev_token(4),
        type=TableType.CABIN,
        price_tier=VIP_PRICE_TIER,
    ),
    TableSeed(hall="terrace", name="Терраса 1", qr_token=dev_token(5)),
    TableSeed(hall="terrace", name="Терраса 2", qr_token=dev_token(6), is_active=False),
)

CATEGORIES: Final[tuple[CategorySeed, ...]] = (
    CategorySeed("demo-cat-salads", "Салаты", "Salatlar", "Салаты", "010"),
    CategorySeed("demo-cat-soups", "Супы", "Şorbalar", "Супы", "020"),
    CategorySeed("demo-cat-hot", "Горячие блюда", "İsti yeməklər", "Горячие блюда", "030"),
    CategorySeed("demo-cat-drinks", "Напитки", "İçkilər", "Напитки", "040"),
)


def _prices(default: str, vip: str) -> dict[str, Decimal]:
    return {DEFAULT_PRICE_TIER: Decimal(default), VIP_PRICE_TIER: Decimal(vip)}


DISHES: Final[tuple[DishSeed, ...]] = (
    DishSeed(
        external_id="demo-d01",
        category="demo-cat-salads",
        pos_name="Салат Чобан",
        prices=_prices("6.50", "8.00"),
        name_az="Çoban salatı",
        name_ru="Салат «Чобан»",
        description_az="Pomidor, xiyar, soğan və göyərti, zeytun yağı ilə.",
        description_ru="Помидоры, огурцы, лук и зелень с оливковым маслом.",
        sort_key="010",
        station="kitchen",
        allergens_verified=True,
        prep_minutes=10,
        weight_amount=Decimal("250.00"),
        weight_unit=WeightUnit.G,
        tags=("vegan",),
    ),
    DishSeed(
        external_id="demo-d02",
        category="demo-cat-salads",
        pos_name="Салат Цезарь с курицей",
        prices=_prices("11.00", "13.50"),
        name_az="Toyuqlu Sezar salatı",
        name_ru="Салат «Цезарь» с курицей",
        description_az="Kahı, toyuq filesi, suxari, pendir və sous.",
        description_ru="Салат романо, куриное филе, сухарики, сыр и соус.",
        sort_key="020",
        station="kitchen",
        allergens_verified=True,
        allergens=("gluten", "eggs", "milk", "fish", "mustard"),
        prep_minutes=15,
        weight_amount=Decimal("280.00"),
        weight_unit=WeightUnit.G,
    ),
    DishSeed(
        external_id="demo-d03",
        category="demo-cat-salads",
        pos_name="Салат из печёных баклажанов",
        prices=_prices("7.00", "8.50"),
        name_az="Bişmiş badımcan salatı",
        name_ru="Салат из печёных баклажанов",
        description_az="Közdə bişmiş badımcan, pomidor və sarımsaq.",
        description_ru="Баклажаны, печённые на углях, помидоры и чеснок.",
        sort_key="030",
        station="kitchen",
        tags=("vegetarian",),
    ),
    DishSeed(
        external_id="demo-d04",
        category="demo-cat-salads",
        pos_name="Сезонный салат",
        prices=_prices("5.50", "7.00"),
        name_az="Mövsümi salat",
        name_ru="Сезонный салат",
        description_az="Mövsümi tərəvəzlər.",
        description_ru="Сезонные овощи.",
        sort_key="040",
        station="kitchen",
        is_hidden=True,
    ),
    DishSeed(
        external_id="demo-d05",
        category="demo-cat-soups",
        pos_name="Суп чечевичный",
        prices=_prices("5.00", "6.00"),
        name_az="Mərci şorbası",
        name_ru="Чечевичный суп",
        description_az="Qırmızı mərci, kərəviz və ədviyyatlar.",
        description_ru="Красная чечевица, сельдерей и специи.",
        sort_key="010",
        station="kitchen",
        allergens_verified=True,
        allergens=("celery",),
        prep_minutes=10,
        weight_amount=Decimal("300.00"),
        weight_unit=WeightUnit.ML,
        tags=("vegetarian",),
    ),
    DishSeed(
        external_id="demo-d06",
        category="demo-cat-soups",
        pos_name="Довга",
        prices=_prices("4.50", "5.50"),
        name_az="Dovğa",
        name_ru="Довга",
        description_az="Qatıq əsasında göyərti şorbası.",
        description_ru="Кисломолочный суп с зеленью.",
        sort_key="020",
        station="kitchen",
        allergens_verified=True,
        allergens=("milk",),
        weight_amount=Decimal("300.00"),
        weight_unit=WeightUnit.ML,
        tags=("vegetarian",),
    ),
    DishSeed(
        external_id="demo-d07",
        category="demo-cat-soups",
        pos_name="Пити",
        prices=_prices("9.00", "11.00"),
        name_az="Piti",
        name_ru="Пити",
        description_az="Qoyun əti, noxud və şabalıd, saxsı qabda.",
        description_ru="Баранина, нут и каштаны в глиняном горшочке.",
        sort_key="030",
        station="kitchen",
        # Список заполнен, но не подтверждён: для ИИ состав аллергенов всё равно неизвестен (AI-2).
        allergens=("gluten",),
        prep_minutes=20,
    ),
    DishSeed(
        external_id="demo-d08",
        category="demo-cat-hot",
        pos_name="Люля-кебаб из баранины",
        prices=_prices("12.00", "14.50"),
        name_az="Quzu lülə kababı",
        name_ru="Люля-кебаб из баранины",
        description_az="Kömür üzərində bişirilmiş quzu əti, soğan və sumaq ilə.",
        description_ru="Баранина на углях, с луком и сумахом.",
        sort_key="010",
        station="grill",
        allergens_verified=True,
        spice_level=1,
        prep_minutes=25,
        weight_amount=Decimal("250.00"),
        weight_unit=WeightUnit.G,
    ),
    DishSeed(
        external_id="demo-d09",
        category="demo-cat-hot",
        pos_name="Плов с сухофруктами",
        prices=_prices("14.00", "17.00"),
        name_az="Qurudulmuş meyvəli plov",
        name_ru="Плов с сухофруктами",
        description_az="Zəfəranlı düyü, kərə yağı, qurudulmuş meyvələr və qoz.",
        description_ru="Рис с шафраном, сливочное масло, сухофрукты и орехи.",
        sort_key="020",
        station="kitchen",
        allergens_verified=True,
        allergens=("milk", "nuts"),
        prep_minutes=20,
        weight_amount=Decimal("350.00"),
        weight_unit=WeightUnit.G,
    ),
    DishSeed(
        external_id="demo-d10",
        category="demo-cat-hot",
        pos_name="Долма в виноградных листьях",
        prices=_prices("10.00", "12.00"),
        name_az="Yarpaq dolması",
        name_ru="Долма в виноградных листьях",
        description_az="Üzüm yarpağında ət və düyü, qatıq ilə.",
        description_ru="Мясо и рис в виноградных листьях, с йогуртом.",
        sort_key="030",
        station="kitchen",
        prep_minutes=15,
    ),
    DishSeed(
        external_id="demo-d11",
        category="demo-cat-hot",
        pos_name="Форель на гриле",
        prices=_prices("16.00", "19.00"),
        name_az="Qrildə alabalıq",
        name_ru="Форель на гриле",
        description_az="Bütöv alabalıq, limon və göyərti ilə.",
        description_ru="Форель целиком, с лимоном и зеленью.",
        sort_key="040",
        station="grill",
        allergens_verified=True,
        allergens=("fish",),
        prep_minutes=25,
        is_available=False,
    ),
    DishSeed(
        external_id="demo-d12",
        category="demo-cat-hot",
        pos_name="Шашлык куриный",
        prices=_prices("9.50", "11.50"),
        name_az="Toyuq kababı",
        name_ru="Куриный шашлык",
        description_az="Marinadlı toyuq budu, acı bibər ilə.",
        description_ru="Маринованное куриное бедро, с острым перцем.",
        sort_key="050",
        station="grill",
        spice_level=2,
        prep_minutes=20,
        tags=("spicy",),
    ),
    DishSeed(
        external_id="demo-d13",
        category="demo-cat-drinks",
        pos_name="Чай чёрный с чабрецом",
        prices=_prices("4.00", "5.00"),
        name_az="Kəklikotulu qara çay",
        name_ru="Чёрный чай с чабрецом",
        description_az="Armudu stəkanda, mürəbbə ilə.",
        description_ru="В стаканах армуды, с вареньем.",
        sort_key="010",
        station="bar",
        allergens_verified=True,
        weight_amount=Decimal("500.00"),
        weight_unit=WeightUnit.ML,
    ),
    DishSeed(
        external_id="demo-d14",
        category="demo-cat-drinks",
        pos_name="Компот домашний",
        prices=_prices("3.00", "3.50"),
        name_az="Ev kompotu",
        name_ru="Домашний компот",
        description_az="Mövsümi meyvələrdən.",
        description_ru="Из сезонных фруктов.",
        sort_key="020",
        station="bar",
    ),
    DishSeed(
        external_id="demo-d15",
        category="demo-cat-drinks",
        pos_name="Айран",
        prices=_prices("2.50", "3.00"),
        name_az="Ayran",
        name_ru="Айран",
        description_az="Qatıq, su və duz.",
        description_ru="Кисломолочный напиток.",
        sort_key="030",
        station="bar",
        allergens_verified=True,
        allergens=("milk",),
        weight_amount=Decimal("300.00"),
        weight_unit=WeightUnit.ML,
    ),
)

# Открытый визит за «Столом 1»: короткий диалог и корзина из двух строк.
VISIT: Final = VisitSeed(
    id=demo_id("visit"),
    table_token=dev_token(1),
    lang=Lang.RU,
    messages=(
        MessageSeed(demo_id("message-1"), MessageRole.USER, "Что посоветуете из супов?"),
        MessageSeed(
            demo_id("message-2"),
            MessageRole.ASSISTANT,
            "Попробуйте чечевичный суп: он вегетарианский и подаётся за 10 минут.",
        ),
    ),
    cart=(
        CartLineSeed(dish="demo-d05", qty=1),
        CartLineSeed(dish="demo-d13", qty=2, comment="с лимоном"),
    ),
)

# Отправленный заказ визита (статус submitted, событие created).
ORDER: Final = OrderSeed(
    id=demo_id("order"),
    idempotency_key=demo_id("order-idempotency-key"),
    created_event_id=demo_id("order-event-created"),
    lines=(
        OrderLineSeed(demo_id("order-item-1"), dish="demo-d01", qty=1),
        OrderLineSeed(demo_id("order-item-2"), dish="demo-d08", qty=2, comment="без лука"),
    ),
)


def dish_by_external_id(external_id: str) -> DishSeed:
    """Позиция сида по ``external_id``; неизвестный — ``KeyError`` (ошибка в данных сида)."""
    for dish in DISHES:
        if dish.external_id == external_id:
            return dish
    raise KeyError(external_id)


def table_by_token(qr_token: str) -> TableSeed:
    """Стол сида по токену; неизвестный — ``KeyError``."""
    for table in TABLES:
        if table.qr_token == qr_token:
            return table
    raise KeyError(qr_token)


def price_for(dish: DishSeed, price_tier: str) -> Decimal:
    """Цена позиции по тарифу; нет цены тарифа — цена ``default``."""
    return dish.prices.get(price_tier, dish.prices[DEFAULT_PRICE_TIER])


def order_total(order: OrderSeed, price_tier: str) -> Decimal:
    """Сумма заказа по ценам тарифа стола."""
    return sum((price_for(dish_by_external_id(line.dish), price_tier) * line.qty for line in order.lines), Decimal("0"))
