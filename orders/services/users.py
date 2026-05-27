import logging

from django.db import DatabaseError, connection

logger = logging.getLogger(__name__)


def sync_user_login(email: str):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, platform, last_login_at)
                VALUES (%s, 0, CURRENT_TIMESTAMP)
                ON CONFLICT (email)
                DO UPDATE SET last_login_at = CURRENT_TIMESTAMP
                """,
                [normalized_email],
            )
    except DatabaseError:
        logger.exception("Could not sync login to custom users table for %s", normalized_email)


def mark_user_paid(email: str):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, platform, status, last_login_at)
                VALUES (%s, 0, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (email)
                DO UPDATE SET status = 1
                """,
                [normalized_email],
            )
    except DatabaseError:
        logger.exception("Could not mark custom users table paid for %s", normalized_email)
