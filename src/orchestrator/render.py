"""Jinja2 template rendering for session prompts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

from orchestrator.config import CLAUDE_HOME, SessionType

if TYPE_CHECKING:
    from orchestrator.context import SessionContext

TEMPLATES_DIR = Path(__file__).parent / "prompts"


class PromptRenderer:
    """Loads and renders Jinja2 prompt templates."""

    def __init__(self) -> None:
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_system_prompt(
        self,
        ctx: SessionContext,
        session_type: SessionType,
    ) -> str:
        """Render the system prompt template with session context."""
        template = self._env.get_template("system.md.j2")
        return template.render(
            session_header_style=session_type.session_header_style,
            session_name=ctx.session_name,
            current_time=ctx.current_time,
            current_time_tz=ctx.current_time_tz,
            today_date=ctx.today_date,
            claude_home=str(CLAUDE_HOME),
            time_context=ctx.time_context,
            weather=ctx.weather,
            helsinki_light=ctx.helsinki_light,
            day_counter=ctx.day_counter,
            ambient_state=ctx.ambient_state,
            visitor_check=ctx.visitor_check,
            news_check=ctx.news_check,
            gifts_check=ctx.gifts_check,
            directories=ctx.directories,
            file_summary=ctx.file_summary,
            recent_thought=ctx.recent_thought,
            memory_content=ctx.memory_content,
            memory_echoes=ctx.memory_echoes,
        )

    def render_user_prompt(
        self,
        session_type: SessionType,
        ctx: SessionContext,
        visitor_msg: str = "",
        sender_name: str = "dinesh",
        letters_context: str = "",
    ) -> str:
        """Render the user prompt template for the given session type."""
        template = self._env.get_template(session_type.user_prompt_template)

        # Parse telegram image prefix: [image:/path]message
        image_path = ""
        caption = ""
        msg_text = visitor_msg

        if session_type.name == "telegram" and visitor_msg:
            match = re.match(r"^\[image:([^\]]+)\](.*)", visitor_msg, re.DOTALL)
            if match:
                image_path = match.group(1)
                msg_text = match.group(2).strip()
                caption = msg_text
                # Clear msg_text for the template logic — image_path is set
                visitor_msg = ""

        sender_display = sender_name[0].upper() + sender_name[1:]

        return template.render(
            session_name=ctx.session_name,
            current_time=ctx.current_time,
            today_date=ctx.today_date,
            prompt_file_content=ctx.prompt_file_content,
            visitor_msg=msg_text if not image_path else visitor_msg,
            sender_display=sender_display,
            image_path=image_path,
            caption=caption,
            letters_context=letters_context,
        )
