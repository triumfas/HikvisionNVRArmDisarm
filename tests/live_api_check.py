"""Manual check of api.py against a real NVR (read-only unless --toggle is given).

  NVR_HOST=<host> NVR_USER=<user> NVR_PASS=<pass> py -3 tests/live_api_check.py [--toggle]
"""
import asyncio
import importlib.util
import os
import pathlib
import sys

import aiohttp

spec = importlib.util.spec_from_file_location(
    "api", pathlib.Path(__file__).parent.parent / "custom_components/hikvision_nvr_arm/api.py"
)
api = importlib.util.module_from_spec(spec)
sys.modules["api"] = api
spec.loader.exec_module(api)


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        c = api.HikNvrClient(session, os.environ["NVR_HOST"], 80, os.environ["NVR_USER"], os.environ["NVR_PASS"])
        print(await c.device_info())
        triggers = await c.list_triggers()
        for t in triggers:
            print(t)
        if "--toggle" in sys.argv:
            ids = [t.id for t in triggers if t.armed]
            print("disarm failed:", await c.set_armed(ids, False))
            print("armed after disarm:", [t.id for t in await c.list_triggers() if t.armed])
            print("arm failed:", await c.set_armed(ids, True))
            print("armed after arm:", [t.id for t in await c.list_triggers() if t.armed])


asyncio.run(main())
