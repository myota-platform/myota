"""Periodic identity retention worker."""

from __future__ import annotations

import logging
import os
import time

from identity import IdentityHandler
from myota_logging import configure_logging, log_event


interval = int(os.environ.get("MYOTA_IDENTITY_MAINTENANCE_SECONDS", "3600"))
configure_logging("myota-identity", "identity-maintenance")
try:
    while True:
        log_event(
            logging.getLogger(__name__),
            logging.INFO,
            "job.started",
            component="identity-maintenance",
            job_type="identity-retention",
        )
        with IdentityHandler.store.operation(write=True):
            removed = IdentityHandler.cleanup_expired()
        try:
            with IdentityHandler.store.operation(write=False):
                removed_profile_images = (
                    IdentityHandler.cleanup_profile_images()
                )
        except Exception as exc:
            log_event(
                logging.getLogger(__name__),
                logging.WARNING,
                "job.failed",
                component="identity-maintenance",
                job_type="profile-image-orphan-cleanup",
                error_type=type(exc).__name__,
            )
            removed_profile_images = 0
        log_event(
            logging.getLogger(__name__),
            logging.INFO,
            "job.completed",
            component="identity-maintenance",
            job_type="identity-retention",
            removed_count=removed if isinstance(removed, int) else 0,
            profile_image_objects_removed=removed_profile_images,
        )
        time.sleep(interval)
except KeyboardInterrupt:
    pass
finally:
    IdentityHandler.store.close()
