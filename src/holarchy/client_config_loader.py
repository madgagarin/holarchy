from logging import getLogger
from tomllib import load

from .storage.base import StorageBackend

logger = getLogger(__name__)


async def load_client_configs_to_redis(
    storage: StorageBackend,
    config_path: str = "clients.toml",
):
    """Reads client configurations from a TOML file and loads them into Redis.

    This function should be called on application startup. It populates Redis
    with both static client parameters (plan, languages, etc.) and initializes
    dynamic quota counters.
    """
    logger.info("Loading client configurations from '%s' into Redis...", config_path)
    try:
        with open(config_path, "rb") as f:
            clients_data = load(f)
    except FileNotFoundError:
        logger.warning(
            "Client config file not found at '%s'. No client configs loaded.",
            config_path,
        )
        return

    loaded_count = 0
    for client_name, config in clients_data.items():
        token = config.get("token")
        if not token:
            logger.warning(
                "Skipping client '%s' due to missing 'token' field.",
                client_name,
            )
            continue

        # Separate static config from dynamic quota values
        static_config = {k: v for k, v in config.items() if k != "monthly_attempts"}
        quota = config.get("monthly_attempts")

        try:
            # Assume these storage methods will be implemented
            await storage.save_client_config(token, static_config)
            if quota is not None and isinstance(quota, int):
                await storage.initialize_client_quota(token, quota)

            loaded_count += 1
        except Exception as e:
            logger.error(
                "Failed to load config for client '%s' (token: %s...): %s",
                client_name,
                token[:4],
                e,
            )

    logger.info("Successfully loaded %d client configurations.", loaded_count)
