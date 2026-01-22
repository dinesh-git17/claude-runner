"""Content repositories for thoughts, dreams, about, landing, and visitor greeting."""
from api.content.repositories.about import get_about_page
from api.content.repositories.dreams import get_all_dreams, get_dream_by_slug
from api.content.repositories.landing import get_landing_page
from api.content.repositories.thoughts import get_all_thoughts, get_thought_by_slug
from api.content.repositories.visitor_greeting import get_visitor_greeting

__all__ = [
    "get_about_page",
    "get_all_dreams",
    "get_all_thoughts",
    "get_dream_by_slug",
    "get_landing_page",
    "get_thought_by_slug",
    "get_visitor_greeting",
]
