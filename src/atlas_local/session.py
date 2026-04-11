from __future__ import annotations


def scoped_thread_id(user_id: str, thread_id: str) -> str:
    return f"{user_id}::{thread_id}"
