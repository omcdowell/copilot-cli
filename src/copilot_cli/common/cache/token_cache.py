import os
from typing import Optional

from copilot_cli.common.cache.string_key_value_cache import StringKeyValueCache


class TokenCache(StringKeyValueCache):
    def __init__(self, cache_path: Optional[str] = None):
        super().__init__(cache_path or os.path.join(os.getcwd(), "tokens.json"))
