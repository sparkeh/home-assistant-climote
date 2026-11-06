"""Regression tests built from responses captured from the live Climote service.

Run from the repo root (needs homeassistant installed):
    python -m unittest discover tests
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer
from homeassistant.components.climate import HVACAction, HVACMode

from custom_components.climote import climote_service
from custom_components.climote.climate import ClimoteClimate
from custom_components.climote.climote_service import (
    ClimoteError,
    ClimoteRefreshTimeout,
    ClimoteService,
)
from custom_components.climote.sensor import ClimoteBoostRemaining

REPORT_BOOSTING = {"burner": 0, "timeRemaining": 30, "status": "5"}
REPORT_STOPPED = {"burner": 0, "timeRemaining": -1, "status": "5"}
REPORT_IDLE = {"burner": 0, "timeRemaining": None, "status": None}
CACHED_BOOSTING = {"burner": 0, "status": 5, "boost": 30, "hold": "00"}
CACHED_STOPPED = {"burner": 0, "temperature": "00", "thermostat": 0}
CACHED_IDLE = {"burner": 0, "hold": "00", "boost": "00"}

LOGIN_PAGE = '<form id="loginForm"></form>'
HOME_PAGE = '<input name="cs_token_rf" value="fresh-token" />'


def _entity(zone: dict) -> SimpleNamespace:
    return SimpleNamespace(
        _zone_data=zone,
        _zone_id=2,
        coordinator=SimpleNamespace(data={"zone2": zone}),
    )


class TestZoneState(unittest.TestCase):
    def test_hvac_mode_handles_both_status_formats(self) -> None:
        mode = ClimoteClimate.hvac_mode.fget
        self.assertEqual(mode(_entity(REPORT_BOOSTING)), HVACMode.HEAT)
        self.assertEqual(mode(_entity(CACHED_BOOSTING)), HVACMode.HEAT)
        self.assertEqual(mode(_entity(REPORT_STOPPED)), HVACMode.OFF)
        self.assertEqual(mode(_entity(REPORT_IDLE)), HVACMode.OFF)
        self.assertEqual(mode(_entity(CACHED_STOPPED)), HVACMode.OFF)
        self.assertEqual(mode(_entity(CACHED_IDLE)), HVACMode.OFF)

    def test_hvac_action_follows_boost_and_web_ui_codes(self) -> None:
        action = ClimoteClimate.hvac_action.fget
        self.assertEqual(action(_entity(CACHED_BOOSTING)), HVACAction.HEATING)
        # The web UI labels burner code 1 "Timer on, burner off".
        self.assertEqual(action(_entity({"burner": 1})), HVACAction.IDLE)
        self.assertEqual(action(_entity({"burner": 3})), HVACAction.HEATING)

    def test_boost_remaining_handles_both_status_formats(self) -> None:
        value = ClimoteBoostRemaining.native_value.fget
        self.assertEqual(value(_entity(REPORT_BOOSTING)), 30)
        self.assertEqual(value(_entity(CACHED_BOOSTING)), 30)
        self.assertEqual(value(_entity(REPORT_STOPPED)), 0)
        self.assertEqual(value(_entity(CACHED_IDLE)), 0)


class TestBoostValues(unittest.IsolatedAsyncioTestCase):
    async def test_old_saved_durations_become_web_form_values(self) -> None:
        for saved, sent in (("0.5", "0.5"), ("1.0", "1"), ("6.0", "6"), ("9.0", "6")):
            service = ClimoteService("1", "u", "p", default_boost_duration=saved)
            self.assertEqual(service.get_zone_boost_duration(2), sent)
            await service.close()


class FakeClimote(unittest.IsolatedAsyncioTestCase):
    """A local stand-in for climote.climote.ie that records posted forms."""

    async def asyncSetUp(self) -> None:
        self.session_valid = True
        self.posts: list[dict] = []
        self.force_replies: list[str] = []
        self.report = '{"zone2": {"status": "5"}}'

        async def login(_: web.Request) -> web.Response:
            self.session_valid = True
            return web.Response(text=HOME_PAGE, content_type="text/html")

        async def login_page(_: web.Request) -> web.Response:
            return web.Response(text=LOGIN_PAGE, content_type="text/html")

        async def command(request: web.Request) -> web.Response:
            if not self.session_valid:
                raise web.HTTPFound("/login-page")
            self.posts.append(dict(await request.post()))
            return web.Response(text="ok", content_type="text/html")

        async def force(_: web.Request) -> web.Response:
            return web.Response(text=self.force_replies.pop(0))

        async def waiting(_: web.Request) -> web.Response:
            return web.Response(text=self.report)

        async def cached(_: web.Request) -> web.Response:
            return web.Response(text=self.cached_reply)

        app = web.Application()
        app.router.add_post("/login", login)
        app.router.add_get("/login-page", login_page)
        app.router.add_post("/command", command)
        app.router.add_post("/force", force)
        app.router.add_get("/force", cached)
        app.router.add_post("/waiting", waiting)
        self.server = TestServer(app)
        await self.server.start_server()

        for name, path in (
            ("_LOGIN_URL", "/login"),
            ("_BOOST_URL", "/command"),
            ("_SET_TEMP_URL", "/command"),
            ("_STATUS_URL", "/force"),
            ("_STATUS_RESPONSE_URL", "/waiting"),
        ):
            patcher = patch.object(
                climote_service, name, str(self.server.make_url(path))
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(climote_service, "_STATUS_POLL_INTERVAL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.service = ClimoteService("1", "u", "p")
        self.service._token = "old-token"
        self.service.logged_in = True

    async def asyncTearDown(self) -> None:
        await self.service.close()
        await self.server.close()

    async def test_cached_status_is_decoded_twice(self) -> None:
        self.cached_reply = '"{\\"zone2\\":{\\"status\\":5,\\"boost\\":30}}"'
        self.assertEqual(
            await self.service.async_get_status(),
            {"zone2": {"status": 5, "boost": 30}},
        )

    async def test_cached_status_without_a_report_is_none(self) -> None:
        for reply in ("0", '"0"', "<html>"):
            self.cached_reply = reply
            self.assertIsNone(await self.service.async_get_status())

    async def test_commands_use_the_web_form_values(self) -> None:
        await self.service.async_turn_off(2)
        await self.service.async_set_target_temperature(1, 19.0)
        self.assertEqual(self.posts[0]["zoneIds[2]"], "stop")
        self.assertEqual(self.posts[1]["temp-set-input[1]"], "19")

    async def test_expired_session_logs_in_again_and_resends(self) -> None:
        self.session_valid = False
        await self.service.async_boost(2)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]["cs_token_rf"], "fresh-token")

    async def test_command_raises_when_the_session_cannot_be_restored(self) -> None:
        self.session_valid = False
        with patch.object(self.service, "async_login", return_value=False):
            with self.assertRaises(ClimoteError):
                await self.service.async_boost(2)

    async def test_refresh_ignores_a_report_from_before_the_command(self) -> None:
        self.force_replies = ['"{\\"stale\\": 1}"', '"\\"awaiting response\\""']
        self.assertEqual(
            await self.service.async_request_status_refresh(),
            {"zone2": {"status": "5"}},
        )
        self.assertEqual(self.force_replies, [])

    async def test_refresh_gives_up_if_the_hub_is_never_asked(self) -> None:
        self.force_replies = ['"{\\"stale\\": 1}"'] * 3
        with patch.object(climote_service, "_STATUS_POLL_TIMEOUT", 0):
            with self.assertRaises(ClimoteRefreshTimeout):
                await self.service.async_request_status_refresh()


if __name__ == "__main__":
    unittest.main()
