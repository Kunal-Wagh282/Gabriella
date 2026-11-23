"""product full-text search

Adds a weighted tsvector to products, maintained by a trigger so it always reflects the
product row plus its brand and category names:

    A  name
    B  category, parent category, colour, brand
    C  material, fit, pattern, style tags, occasions, secondary colours, colour family
    D  description

Revision ID: 47b332fa064d
Revises: 503776a4c251
Create Date: 2026-11-08 09:39:05.170887

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '47b332fa064d'
down_revision: Union[str, Sequence[str], None] = '503776a4c251'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION products_search_document() RETURNS trigger AS $$
DECLARE
    brand_name text;
    category_name text;
    parent_name text;
BEGIN
    SELECT name INTO brand_name FROM brands WHERE id = NEW.brand_id;
    SELECT c.name, p.name INTO category_name, parent_name
      FROM categories c LEFT JOIN categories p ON p.id = c.parent_id
     WHERE c.id = NEW.category_id;

    NEW.search_document :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', concat_ws(' ',
            category_name, parent_name, NEW.colour, brand_name)), 'B') ||
        setweight(to_tsvector('english', concat_ws(' ',
            NEW.material, NEW.fit, NEW.pattern, NEW.colour_family,
            array_to_string(NEW.style_tags, ' '),
            array_to_string(NEW.occasions, ' '),
            array_to_string(NEW.secondary_colours, ' '))), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'D');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('products', sa.Column('search_document', postgresql.TSVECTOR(), nullable=True))
    op.execute(TRIGGER_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER trg_products_search_document
        BEFORE INSERT OR UPDATE OF name, brand_id, category_id, colour, colour_family, material,
            fit, pattern, style_tags, occasions, secondary_colours, description
        ON products FOR EACH ROW EXECUTE FUNCTION products_search_document()
        """
    )
    op.execute("UPDATE products SET name = name")  # backfill existing rows
    op.create_index('ix_products_search_document', 'products', ['search_document'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_products_search_document', table_name='products', postgresql_using='gin')
    op.execute("DROP TRIGGER IF EXISTS trg_products_search_document ON products")
    op.execute("DROP FUNCTION IF EXISTS products_search_document()")
    op.drop_column('products', 'search_document')
