"""Inline menu navigation — trojan-style layered keyboard system."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ContextTypes


class MenuPage:
    """Base class for a menu page."""

    name: str = "menu"
    back_callback: str | None = None

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        """Return (text, keyboard). Override in subclass."""
        raise NotImplementedError

    async def handle(self, query, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        """Handle callback_data from this page. Return new page key or None."""
        return None


class MenuNavigator:
    """Routes callback_data to page handlers and manages navigation stack."""

    def __init__(self, pages: dict[str, MenuPage]):
        self.pages = pages
        self._nav_stack: list[str] = []

    def build(self, page_key: str) -> tuple[str, InlineKeyboardMarkup]:
        return self.pages[page_key].build()

    async def navigate(self, query, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        """Process callback, return new page key or None to stay."""
        data = query.data
        page_key = None

        # Static nav actions
        if data == "nav:back":
            page_key = self._nav_stack.pop() if self._nav_stack else "main"
        elif data == "nav:main":
            self._nav_stack.clear()
            page_key = "main"
        elif data.startswith("page:"):
            page_key = data[5:]
        elif data in self.pages:
            result = await self.pages[data].handle(query, context)
            if result and result != data:
                self._nav_stack.append(data)
                page_key = result
        else:
            # Unknown callback — ask current page
            if self._nav_stack:
                current = self._nav_stack[-1]
                if current in self.pages:
                    page_key = await self.pages[current].handle(query, context)

        if page_key and page_key in self.pages:
            return page_key
        return None

    def push(self, page_key: str):
        self._nav_stack.append(page_key)

    def pop(self) -> str | None:
        """Pop last page from stack. Returns page key or None."""
        if self._nav_stack:
            return self._nav_stack.pop()
        return None


def make_back_button(back_to: str) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton("◀️ Back", callback_data=f"page:{back_to}")]]


def make_row(*buttons: InlineKeyboardButton) -> list[InlineKeyboardButton]:
    return list(buttons)


def make_grid(rows: list[list[InlineKeyboardButton]]) -> list[list[InlineKeyboardButton]]:
    return rows
