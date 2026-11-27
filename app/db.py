from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table, Text,
    create_engine, event, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
if config.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


recipe_cookbook = Table(
    "recipe_cookbook",
    Base.metadata,
    Column("recipe_id", ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("cookbook_id", ForeignKey("cookbooks.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def name(self) -> str:
        return self.display_name or self.username


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    servings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # One ingredient per line; a line ending in ":" is a section header.
    ingredients: Mapped[str] = mapped_column(Text, default="")
    # Steps separated by line breaks.
    instructions: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")  # comma separated
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    image: Mapped[str] = mapped_column(String(300), default="")  # file name in uploads
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(20), default="standard", server_default="standard")  # standard | bread
    bread: Mapped[str] = mapped_column(Text, default="", server_default="")  # JSON spec, see bread.py
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    cookbooks: Mapped[list["Cookbook"]] = relationship(secondary=recipe_cookbook, back_populates="recipes")
    logs: Mapped[list["CookLog"]] = relationship(back_populates="recipe", order_by="CookLog.cooked_on.desc()")

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def total_minutes(self) -> int | None:
        if self.prep_minutes is None and self.cook_minutes is None:
            return None
        return (self.prep_minutes or 0) + (self.cook_minutes or 0)

    @property
    def steps(self) -> list[str]:
        return [s.strip() for s in self.instructions.splitlines() if s.strip()]


class Cookbook(Base):
    __tablename__ = "cookbooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="#c2410c")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recipes: Mapped[list[Recipe]] = relationship(
        secondary=recipe_cookbook, back_populates="cookbooks", order_by="Recipe.title"
    )


class CookLog(Base):
    """One entry in the cooking calendar: what was cooked, when, for whom."""
    __tablename__ = "cook_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="")  # used when no recipe is linked
    cooked_on: Mapped[date] = mapped_column(Date, index=True)
    guests: Mapped[str] = mapped_column(String(500), default="")  # "for whom"
    notes: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recipe: Mapped[Recipe | None] = relationship(back_populates="logs")
    user: Mapped[User | None] = relationship()

    @property
    def label(self) -> str:
        return self.recipe.title if self.recipe else (self.title or "Untitled")


class MealPlan(Base):
    __tablename__ = "meal_plan"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    meal: Mapped[str] = mapped_column(String(20), default="dinner")
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    servings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooked: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped[Recipe | None] = relationship()

    @property
    def label(self) -> str:
        return self.recipe.title if self.recipe else (self.note or "Untitled")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(String(300), default="")  # e.g. "for: Lasagne"
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# Columns added after v1.0. create_all() does not alter existing tables, so add them by hand.
NEW_COLUMNS = {
    "recipes": {
        "kind": "VARCHAR(20) NOT NULL DEFAULT 'standard'",
        "bread": "TEXT NOT NULL DEFAULT ''",
    },
}


def init_db() -> None:
    from sqlalchemy import inspect, text
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_setting(db, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
