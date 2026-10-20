"""Template context available on every page."""

import logging

from django.db import DatabaseError

from .models import SYNTHETIC_PREFIX, ProductionOrder

logger = logging.getLogger(__name__)


def app_context(request):
    try:
        has_synthetic = ProductionOrder.objects.filter(
            order_code__startswith=SYNTHETIC_PREFIX
        ).exists()
    except DatabaseError:
        logger.warning("Could not check for synthetic demonstration data.")
        has_synthetic = False
    match = getattr(request, "resolver_match", None)
    url_name = (match.url_name or "") if match else ""
    return {
        "APP_NAME": "Textile Production Intelligence",
        "has_synthetic_data": has_synthetic,
        "nav_section": url_name.split("_")[0],
    }
