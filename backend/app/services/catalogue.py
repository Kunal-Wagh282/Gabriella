"""Catalogue reads. Everything here comes straight from PostgreSQL, the source of truth."""

from collections import defaultdict

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFound
from app.db.models import (
    Brand,
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
    Store,
)
from app.schemas.catalogue import (
    BrandOut,
    CategoryNode,
    CategoryRef,
    ColourFacet,
    ColourSibling,
    Facets,
    ImageOut,
    ProductDetail,
    ProductFilters,
    ProductSummary,
    SizeAvailability,
    SortKey,
    StoreStock,
    ValueCount,
    VariantOut,
)
from app.schemas.common import Page

SORTS = {
    "relevance": (Product.popularity.desc(), Product.id),  # without a query, same as featured
    "featured": (Product.popularity.desc(), Product.id),
    "newest": (Product.created_at.desc(), Product.id),
    "price_asc": (Product.price.asc(), Product.id),
    "price_desc": (Product.price.desc(), Product.id),
}


async def _category_ids(session: AsyncSession, slugs: list[str]) -> list[int]:
    """Resolve slugs to leaf category IDs, expanding parent groups to their children."""
    rows = (await session.execute(select(Category.id, Category.parent_id, Category.slug))).all()
    by_slug = {slug: cid for cid, _, slug in rows}
    children: dict[int, list[int]] = defaultdict(list)
    for cid, parent, _ in rows:
        if parent is not None:
            children[parent].append(cid)
    ids: set[int] = set()
    for slug in slugs:
        if (cid := by_slug.get(slug)) is not None:
            ids.add(cid)
            ids.update(children.get(cid, []))
    return list(ids)


def variant_in_stock(store_id: int | None):  # noqa: ANN201 - SQL expression
    """EXISTS clause: the correlated variant has stock at the store (or anywhere)."""
    conds = [Inventory.variant_id == ProductVariant.id, Inventory.on_hand > 0]
    if store_id is not None:
        conds.append(Inventory.store_id == store_id)
    return exists().where(*conds)


async def apply_filters(session: AsyncSession, stmt: Select, f: ProductFilters) -> Select:
    stmt = stmt.where(Product.is_active.is_(True))
    if f.category:
        stmt = stmt.where(Product.category_id.in_(await _category_ids(session, f.category)))
    if f.gender:
        stmt = stmt.where(Product.gender.in_(f.gender))
    if f.brand:
        stmt = stmt.where(Product.brand.has(Brand.slug.in_(f.brand)))
    if f.colour:
        lowered = [c.lower() for c in f.colour]
        stmt = stmt.where(
            or_(func.lower(Product.colour).in_(lowered), Product.colour_family.in_(lowered))
        )
    if f.style:
        stmt = stmt.where(Product.style_tags.overlap(f.style))
    if f.occasion:
        stmt = stmt.where(Product.occasions.overlap(f.occasion))
    if f.min_price is not None:
        stmt = stmt.where(Product.price >= f.min_price)
    if f.max_price is not None:
        stmt = stmt.where(Product.price <= f.max_price)
    if f.on_sale:
        stmt = stmt.where(Product.mrp > Product.price)
    if f.size or f.in_stock:
        variant_conds = [
            ProductVariant.product_id == Product.id,
            ProductVariant.is_active.is_(True),
        ]
        if f.size:
            variant_conds.append(ProductVariant.size.in_(f.size))
        if f.in_stock:
            variant_conds.append(variant_in_stock(f.store_id))
        stmt = stmt.where(exists().where(*variant_conds))
    return stmt


async def size_availability(
    session: AsyncSession, product_ids: list[int], store_id: int | None
) -> dict[int, list[SizeAvailability]]:
    if not product_ids:
        return {}
    join_cond = and_(Inventory.variant_id == ProductVariant.id, Inventory.on_hand > 0)
    if store_id is not None:
        join_cond = and_(join_cond, Inventory.store_id == store_id)
    rows = await session.execute(
        select(
            ProductVariant.product_id,
            ProductVariant.id,
            ProductVariant.size,
            func.count(Inventory.store_id) > 0,
        )
        .outerjoin(Inventory, join_cond)
        .where(ProductVariant.product_id.in_(product_ids), ProductVariant.is_active.is_(True))
        .group_by(ProductVariant.id)
        .order_by(ProductVariant.product_id, ProductVariant.size_rank)
    )
    out: dict[int, list[SizeAvailability]] = defaultdict(list)
    for product_id, variant_id, size, in_stock in rows.all():
        out[product_id].append(
            SizeAvailability(variant_id=variant_id, size=size, in_stock=in_stock)
        )
    return out


async def summaries(
    session: AsyncSession, product_ids: list[int], store_id: int | None
) -> list[ProductSummary]:
    """Product cards for `product_ids`, in the given order, with per-size stock at the store."""
    if not product_ids:
        return []
    products = {
        p.id: p
        for p in (await session.scalars(select(Product).where(Product.id.in_(product_ids))))
        .unique()
        .all()
    }
    sizes = await size_availability(session, product_ids, store_id)
    images = await primary_images(session, product_ids)
    return [
        ProductSummary(
            id=p.id,
            slug=p.slug,
            name=p.name,
            brand=p.brand.name,
            category=p.category.name,
            gender=p.gender,  # type: ignore[arg-type]
            colour=p.colour,
            colour_hex=p.colour_hex,
            price=p.price,
            mrp=p.mrp,
            image=images.get(p.id),
            sizes=sizes.get(p.id, []),
            in_stock=any(s.in_stock for s in sizes.get(p.id, [])),
        )
        for pid in product_ids
        if (p := products.get(pid)) is not None
    ]


async def list_products(
    session: AsyncSession,
    filters: ProductFilters,
    *,
    sort: SortKey = "featured",
    page: int = 1,
    page_size: int = 24,
) -> Page[ProductSummary]:
    """Filter-only listing. Free-text queries go through `app.retrieval.search` instead."""
    base = await apply_filters(session, select(Product.id), filters)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    ids = list(
        (
            await session.scalars(
                base.order_by(*SORTS[sort]).limit(page_size).offset((page - 1) * page_size)
            )
        ).all()
    )
    items = await summaries(session, ids, filters.store_id)
    return Page(items=items, total=total, page=page, page_size=page_size)


async def primary_images(session: AsyncSession, product_ids: list[int]) -> dict[int, ImageOut]:
    if not product_ids:
        return {}
    rows = await session.scalars(
        select(ProductImage).where(
            ProductImage.product_id.in_(product_ids), ProductImage.position == 0
        )
    )
    return {img.product_id: ImageOut.model_validate(img) for img in rows}


async def resolve_product_id(session: AsyncSession, key: str) -> int:
    cond = Product.id == int(key) if key.isdigit() else Product.slug == key
    product_id = await session.scalar(select(Product.id).where(cond))
    if product_id is None:
        raise NotFound("Product not found")
    return product_id


async def get_product(
    session: AsyncSession, key: str, *, store_id: int | None = None
) -> ProductDetail:
    cond = Product.id == int(key) if key.isdigit() else Product.slug == key
    product = (
        (
            await session.scalars(
                select(Product)
                .where(cond)
                .options(selectinload(Product.images), selectinload(Product.variants))
            )
        )
        .unique()
        .one_or_none()
    )
    if product is None:
        raise NotFound("Product not found")

    variant_ids = [v.id for v in product.variants]
    stock_rows = await session.execute(
        select(Inventory.variant_id, Inventory.store_id, Store.code, Inventory.on_hand)
        .join(Store, Store.id == Inventory.store_id)
        .where(Inventory.variant_id.in_(variant_ids), Store.is_active.is_(True))
        .order_by(Store.id)
    )
    stock: dict[int, list[StoreStock]] = defaultdict(list)
    for variant_id, sid, code, on_hand in stock_rows.all():
        stock[variant_id].append(StoreStock(store_id=sid, store_code=code, on_hand=on_hand))

    siblings = await session.execute(
        select(Product.id, Product.slug, Product.colour, Product.colour_hex)
        .where(Product.style_code == product.style_code, Product.is_active.is_(True))
        .order_by(Product.id)
    )
    parent = None
    if product.category.parent_id is not None:
        parent_cat = await session.get(Category, product.category.parent_id)
        parent = CategoryRef.model_validate(parent_cat) if parent_cat else None

    def at_store(variant_id: int) -> int | None:
        if store_id is None:
            return None
        return next((s.on_hand for s in stock[variant_id] if s.store_id == store_id), 0)

    return ProductDetail(
        **{
            k: getattr(product, k)
            for k in (
                "id",
                "slug",
                "style_code",
                "name",
                "gender",
                "colour",
                "colour_hex",
                "colour_family",
                "secondary_colours",
                "pattern",
                "material",
                "fit",
                "style_tags",
                "occasions",
                "seasons",
                "formality",
                "price",
                "mrp",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            )
        },
        brand=BrandOut.model_validate(product.brand),
        category=CategoryRef.model_validate(product.category),
        parent_category=parent,
        images=[ImageOut.model_validate(i) for i in product.images],
        variants=[
            VariantOut(
                id=v.id,
                sku=v.sku,
                size=v.size,
                stock=stock[v.id],
                available_at_selected_store=at_store(v.id),
            )
            for v in product.variants
            if v.is_active
        ],
        colourways=[
            ColourSibling(id=i, slug=s, colour=c, colour_hex=h) for i, s, c, h in siblings.all()
        ],
    )


async def get_facets(session: AsyncSession) -> Facets:
    active = Product.is_active.is_(True)

    cat_counts = dict(
        (
            await session.execute(
                select(Product.category_id, func.count())
                .where(active)
                .group_by(Product.category_id)
            )
        ).all()
    )
    categories = (await session.scalars(select(Category).order_by(Category.position))).all()
    nodes = {
        c.id: CategoryNode(
            id=c.id, slug=c.slug, name=c.name, slot=c.slot, product_count=cat_counts.get(c.id, 0)
        )
        for c in categories
    }
    roots: list[CategoryNode] = []
    for c in categories:
        if c.parent_id is None:
            roots.append(nodes[c.id])
        else:
            nodes[c.parent_id].children.append(nodes[c.id])
            nodes[c.parent_id].product_count += nodes[c.id].product_count

    async def counts(col) -> list[ValueCount]:  # noqa: ANN001
        rows = await session.execute(
            select(col, func.count()).where(active).group_by(col).order_by(func.count().desc())
        )
        return [ValueCount(value=str(v), count=n) for v, n in rows.all()]

    async def array_counts(col) -> list[ValueCount]:  # noqa: ANN001
        tag = func.unnest(col).label("tag")
        sub = select(tag).where(active).subquery()
        rows = await session.execute(
            select(sub.c.tag, func.count()).group_by(sub.c.tag).order_by(func.count().desc())
        )
        return [ValueCount(value=v, count=n) for v, n in rows.all()]

    brand_rows = await session.execute(
        select(Brand.slug, func.count(Product.id))
        .join(Product, and_(Product.brand_id == Brand.id, active))
        .group_by(Brand.slug)
        .order_by(Brand.slug)
    )
    colour_rows = await session.execute(
        select(Product.colour, Product.colour_hex, Product.colour_family, func.count())
        .where(active)
        .group_by(Product.colour, Product.colour_hex, Product.colour_family)
        .order_by(func.count().desc())
    )
    size_rows = await session.execute(
        select(ProductVariant.size, func.min(ProductVariant.size_rank))
        .group_by(ProductVariant.size)
        .order_by(func.min(ProductVariant.size_rank))
    )
    price_min, price_max = (
        await session.execute(
            select(func.min(Product.price), func.max(Product.price)).where(active)
        )
    ).one()

    return Facets(
        categories=roots,
        brands=[ValueCount(value=s, count=n) for s, n in brand_rows.all()],
        colours=[ColourFacet(name=n, hex=h, family=f, count=c) for n, h, f, c in colour_rows.all()],
        sizes=[s for s, _ in size_rows.all()],
        genders=await counts(Product.gender),
        style_tags=await array_counts(Product.style_tags),
        occasions=await array_counts(Product.occasions),
        price_min=price_min or 0,
        price_max=price_max or 0,
    )


async def list_stores(session: AsyncSession) -> list[Store]:
    return list(
        (
            await session.scalars(
                select(Store).where(Store.is_active.is_(True)).order_by(Store.is_online, Store.city)
            )
        ).all()
    )


async def list_brands(session: AsyncSession) -> list[Brand]:
    return list((await session.scalars(select(Brand).order_by(Brand.name))).all())
